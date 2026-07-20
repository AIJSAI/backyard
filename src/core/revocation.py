"""The TM-1 credential registry and revocation handler.

Every bearer capability the system mints is revoked here, in one atomic act, never
by a checklist an admin walks by hand (threat model TM-1, ADR-003). The registry
today holds the credential classes that exist: server-side sessions and invites.
Every future class (elder master tokens, per-digest tokens, signed media URLs,
reply-by-email addresses) registers here before it ships; a capability type that
does not appear in _REVOCATION_STEPS is the bug the revocation-completeness test
exists to catch.

The revocation anchor is Member.token_generation (ADR-003 rule 3): derived
credentials carry the generation they were minted under and are checked against
the member's current one at request time, so one bump kills them all on their next
use regardless of TTL. Sessions and invites are stateful rows, so they die by
deletion and voiding; generation-checked classes die by the bump.

Everything here runs inside one transaction. ATOMIC_REQUESTS wraps view calls;
callers outside a request (jobs, management commands) get the explicit
transaction.atomic below either way, so a crash mid-revocation leaves no state
where some classes are dead and others alive (TS-DJ-2's kill-test asserts this).
"""

from __future__ import annotations

from django.contrib.sessions.models import Session
from django.db import models, transaction
from django.utils import timezone

from .models import Invite, Member


def _revoke_sessions(member: Member) -> int:
    """Delete every server-side session belonging to the member's user.

    Django keys sessions by opaque session key, not user, so this decodes each
    live session's payload to find the user id. At family scale (tens of members,
    db-backed sessions pinned by TS-DJ-1) a full scan is simple and correct;
    revisit only if a session index table ever becomes worth its complexity.
    """
    if member.user_id is None:
        return 0
    target = str(member.user_id)
    doomed = [
        s.session_key
        for s in Session.objects.filter(expire_date__gte=timezone.now())
        if s.get_decoded().get("_auth_user_id") == target
    ]
    count, _ = Session.objects.filter(session_key__in=doomed).delete()
    return count


def _void_invites(member: Member) -> int:
    """Void invites the member created AND live invites reaching any pod the
    member belongs to (T-AUTH-G3: a removed ex must not re-enter through the
    original household invite someone else created)."""
    now = timezone.now()
    reachable = Invite.objects.filter(
        models.Q(created_by=member) | models.Q(pod__memberships__member=member),
        revoked_at__isnull=True,
    )
    return reachable.update(revoked_at=now)


def _bump_generation(member: Member) -> None:
    """Invalidate every generation-checked credential class at once (ADR-003)."""
    Member.objects.filter(pk=member.pk).update(token_generation=models.F("token_generation") + 1)


# The registry, in execution order. A new credential class ships by adding its
# revocation step here (and its 404-or-bounce assertion to the completeness test),
# never by adding a second handler somewhere else.
_REVOCATION_STEPS = (
    _revoke_sessions,
    _void_invites,
)


def revoke_member_credentials(member: Member) -> None:
    """The one revocation act (TM-1). Runs every registered step plus the
    generation bump in a single transaction: after it commits, every credential
    class the member held is dead on its next use; if it raises, none are.

    Fired by removal, voluntary leave, pod-leaves-yard, deceased marking, and
    any regeneration; those lifecycle flows land in their stories (S-702, S-706)
    and all call this, never their own partial subset.
    """
    with transaction.atomic():
        locked = Member.objects.select_for_update().get(pk=member.pk)
        for step in _REVOCATION_STEPS:
            step(locked)
        _bump_generation(locked)
