"""The TM-1 credential registry and revocation handler.

Every bearer capability the system mints is revoked here, in one atomic act, never
by a checklist an admin walks by hand (threat model TM-1, ADR-003). The registry
today holds seven classes, and every one of them has shipped: server-side sessions,
invites, digest subscriptions, per-digest tokens, reply-by-email addresses, elder
master tokens and admin-issued recovery links. Every future class registers here
before it ships; a
capability type that does not appear in _REVOCATION_STEPS is the bug the
revocation-completeness test exists to catch.

This paragraph called elder tokens, digest tokens and reply addresses "known
future classes" for months after they shipped, which is the more dangerous
direction for a registry's own description to be wrong in: a reader checking
whether a credential type is covered would have concluded it was not, and either
added a duplicate step or gone looking for the gap that was already closed.

Signed media URLs are the one entry that is still genuinely future, and they die by
the generation check rather than by a step of their own, because they carry the
generation. Password login dies by deactivating the Member's User (S-702).

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

from collections.abc import Callable

from django.contrib.sessions.models import Session
from django.db import models, transaction
from django.utils import timezone

from .models import DigestSubscription, DigestToken, Invite, Member, Yard

# Every registry entry takes the locked Member and returns a count (or None for the
# generation bump). Named so both registries below type-check without an escape hatch.
RevocationStep = Callable[[Member], object]


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
    """Void every live invite the removed member could re-enter through: ones they
    created, and ones reaching any pod in any yard they belong to.

    REMOVAL only -- the scope below is a re-entry scope, so it is not in
    _REGENERATION_STEPS. See the comment above that registry.

    Scope is pods AND yards, per the threat model's authoritative text (TM-1 at
    T-AUTH-G3: "removal lists all live invites scoped to the removed member's pods
    and yards"). Pods-only would leave a same-yard-different-pod invite live, and
    an ex who was in a family group chat could paste it back in and re-enter the
    yard. The blast radius is honest: removing a member voids outstanding invites
    to other households in their yards too, so those re-issue. At family scale that
    is cheap, and re-issuing an invite is one click; a surviving re-entry path is
    not. The yard arm subsumes the member's own pods, so pod membership needs no
    separate clause.

    Ordering contract (security review H-1): this reads the member's live
    PodMembership rows, so revoke_member_credentials MUST run while they still
    exist. The S-702 removal flow revokes first, then tears down memberships and
    makes its content decision; the assertion that it does lands with S-702.
    """
    now = timezone.now()
    member_yard_ids = Yard.objects.filter(pods__memberships__member=member).values_list(
        "id", flat=True
    )
    reachable = Invite.objects.filter(
        models.Q(created_by=member) | models.Q(pod__yards__in=member_yard_ids),
        revoked_at__isnull=True,
    )
    return reachable.update(revoked_at=now)


def _void_invites_created_by_member(member: Member) -> int:
    """Void every live invite this member MINTED: regeneration's half of _void_invites.

    An invite she issued is her own act and her own bearer secret -- she saw the raw token
    once and it is still in whatever she sent it with -- so it dies whenever her credentials
    are rotated. Rotation is what the product offers when the device or the session was
    somebody else's for a while (T-TOKEN-5), and an invite minted in that window outlives
    every credential the rotation does kill: 7 days, 8 redemptions, and a redemption mints a
    full member with a login. NOT the yard arm: invites other admins issued into her yards
    are the invited household's credential, not hers. Elders mint nothing (can_issue_invite
    is admin-only), so on the reprint-her-QR path this voids zero rows.
    """
    return Invite.objects.filter(created_by=member, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )


def _void_digest_capabilities(member: Member) -> int:
    """Void both emailed digest capabilities, WITHOUT touching the subscription itself.

    Clearing the digests kills the confirm and unsubscribe links already sitting in a
    mailbox. `enabled` is a PREFERENCE, not a bearer credential, so it is untouched here —
    backups._forced_security_replay already draws exactly this line for a restore.
    """
    # nosec B106: empty strings REVOKE the emailed capabilities — the absence of a
    # credential, not a hardcoded one.
    return DigestSubscription.objects.filter(member=member).update(  # nosec B106
        confirm_token_digest="", unsubscribe_token_digest=""
    )


def _cancel_digest_subscription(member: Member) -> int:
    """Drop the member from digest recipients and void both emailed capabilities.

    Removal only. Disabling stops every future send (due-recipient resolution filters on
    enabled + live membership); clearing the digests kills the confirm and
    unsubscribe links already sitting in a mailbox, so a removed member holds no
    live digest capability of any kind (TM-1). A send already queued dies at the
    send path's own liveness re-check inside its transaction (TS-DJ-11 shape) —
    this step makes that re-check find nothing.
    """
    # nosec B106: these empty strings REVOKE the emailed capabilities — the absence of a
    # credential, not a hardcoded one. Scoped to B106 so it suppresses one rule, not the line.
    return DigestSubscription.objects.filter(member=member).update(  # nosec B106
        enabled=False, confirm_token_digest="", unsubscribe_token_digest=""
    )


def _void_reply_addresses(member: Member) -> int:
    """Kill every reply-by-email capability immediately (TM-4/TM-1): voided is
    dead regardless of grace, and the write path's audience re-check is the
    second lock behind this row state."""
    from . import reply_addresses

    return reply_addresses.void_for_member(member)


def _void_digest_tokens(member: Member) -> int:
    """Delete the member's per-digest read links (TM-5). The generation check in
    digest_links.resolve already kills them on the bump (ADR-003 rule 3), so this
    is the registry-literal belt: the class registers its own step, and a link in
    a forwarded or compromised mailbox dies as a row too, not only as a check."""
    count, _ = DigestToken.objects.filter(member=member).delete()
    return count


def _void_elder_tokens(member: Member) -> int:
    """Delete the member's elder master token (TM-1, TM-5). The generation
    check in elder_tokens.resolve and the per-request session re-check are the
    live kill; this is the registry-literal row belt, so a revoked member holds
    no token row at all."""
    from .models import ElderToken

    count, _ = ElderToken.objects.filter(member=member).delete()
    return count


def _void_recovery_tokens(member: Member) -> int:
    """Delete the member's outstanding admin-issued recovery link (BY-01, TM-1).

    The generation check in recovery.resolve is the live kill (ADR-003 rule 3); this is
    the registry-literal row belt, the same pairing the elder and digest tokens carry, so
    a removed member has no password-setting capability sitting in anyone's text thread.
    """
    from .models import RecoveryToken

    count, _ = RecoveryToken.objects.filter(member=member).delete()
    return count


def _bump_generation(member: Member) -> None:
    """Invalidate every generation-checked credential class at once (ADR-003)."""
    Member.objects.filter(pk=member.pk).update(token_generation=models.F("token_generation") + 1)


# The registry, in execution order. A new credential class ships by adding its
# revocation step here (and its 404-or-bounce assertion to the completeness test),
# never by adding a second handler somewhere else.
_REVOCATION_STEPS: tuple[RevocationStep, ...] = (
    _revoke_sessions,
    _void_invites,
    _cancel_digest_subscription,
    _void_digest_tokens,
    _void_reply_addresses,
    _void_elder_tokens,
    _void_recovery_tokens,
)

# The same registry minus the two steps that punish a member who is still here. Both were
# found the same way, on a walk, one after the other -- which is the warning this comment
# carries: this registry is DERIVED, so any step added above lands here by default, and the
# default is removal semantics.
#
# The digest SUBSCRIPTION is left alone. Regenerating an elder's link is meant to be socially
# cheap and frequent (T-TOKEN-G1: she forwarded it, she lost the phone, reprint the QR) --
# but it ran the removal-shaped handler, which set enabled=False AND blanked both digest
# tokens. An elder has no login by design (TM-10) and digest_settings is login_required and
# self-only, so there was no way back: one click of "regenerate her link" ended her only
# content channel permanently, and silenced her reply nudges with it. That contradicts S-501
# and T-EMAIL-6, which forbid silent severing.
#
# Outstanding invites OTHER ADMINS issued are left alone; hers are not. _void_invites bundles
# two scopes. The re-entry scope -- every live invite reaching any yard she belongs to,
# whoever created it -- is right for removal and wrong here: those invites are the other
# households' credential, and on the design walk one regeneration revoked a household invite
# minted four clicks earlier, with no warning to the admin and the bare 404 for the family who
# had already been texted the link. The invites SHE created stay in the rotation, because
# regeneration is also the answer to a stolen phone or a session somebody else was driving,
# and an invite minted in that window is a re-entry route that survives every credential this
# handler kills.
_REGENERATION_STEPS: tuple[RevocationStep, ...] = tuple(
    _void_digest_capabilities
    if step is _cancel_digest_subscription
    else _void_invites_created_by_member
    if step is _void_invites
    else step
    for step in _REVOCATION_STEPS
)


def revoke_member_credentials(member: Member) -> None:
    """The one revocation act (TM-1). Runs every registered step plus the
    generation bump in a single transaction: after it commits, every credential
    class the member held is dead on its next use; if it raises, none are.

    Fired by removal, voluntary leave, pod-leaves-yard and deceased marking: the flows
    where the member is GONE. Those lifecycle flows land in their stories (S-702, S-706)
    and all call this, never their own partial subset.

    NOT for regeneration -- use regenerate_member_credentials, which keeps the digest
    subscription and the invites OTHER admins issued (it still voids the ones she minted).
    This function disables the subscription (an elder has no login to turn it back on) and
    voids invites other households still hold.

    Ordering contract (security review H-1): call this BEFORE tearing down the
    member's PodMembership rows. _void_invites resolves the yard scope from live
    memberships, so revoking after teardown would silently miss the reachable
    invites and reopen T-AUTH-G3. S-702 revokes first, then removes memberships.
    """
    _run_steps(member, _REVOCATION_STEPS)


def _void_invites_into_yards(yard_ids: set[int]) -> RevocationStep:
    """A SHRINK's invite scope: the re-entry routes into the sides being LOST, plus every
    invite the member minted themselves.

    Not `_void_invites`, which resolves its scope from every yard the member is STILL in.
    On a shrink that is the wrong set in the expensive direction: it voids outstanding
    invitations into the side the member KEEPS, so taking one person out of one household
    silently cancels another household's hand-over link on the far side of the instance —
    and, through a yard admin's own supervised child, in a yard they do not administer at
    all. The re-entry route T-AUTH-G3 cares about is an invite into the side they just left;
    an invite into a side they keep is the invited household's credential, not theirs, which
    is the same line `_REGENERATION_STEPS` already draws for the same reason.
    """

    def step(member: Member) -> int:
        return Invite.objects.filter(
            models.Q(created_by=member) | models.Q(pod__yards__id__in=yard_ids),
            revoked_at__isnull=True,
        ).update(revoked_at=timezone.now())

    return step


def revoke_for_membership_shrink(member: Member, *, losing_yard_ids: set[int]) -> None:
    """The registry for a membership SHRINK (BY-14): the member stays on the instance, but
    a side of the family goes away for them.

    DERIVED from the removal registry, like `_REGENERATION_STEPS` and with the same warning
    attached — a step added above lands here by default, with removal semantics. Two are
    narrowed, and both narrowings are named:

    * INVITES scope to the yards being LOST (see `_void_invites_into_yards`).
    * The digest SUBSCRIPTION stays enabled; only its emailed capabilities die. `enabled` is
      a PREFERENCE, `digest_settings` is login_required and self-only, and an elder has no
      login by design (TM-10) — so `_cancel_digest_subscription` on somebody who is STILL
      HERE ends their only content channel with no route back for any person on the
      instance, which S-501 and T-EMAIL-6 forbid and which `_REGENERATION_STEPS` was written
      to stop. Their reach narrows anyway: the send path re-resolves audience inside its own
      transaction (TM-2), so the next digest carries only what they may still see.

    Everything the member actually HOLDS still dies: sessions, per-digest tokens, reply
    addresses, the elder master token, recovery links, and the generation bump.
    """
    steps = tuple(
        _void_digest_capabilities
        if step is _cancel_digest_subscription
        else _void_invites_into_yards(losing_yard_ids)
        if step is _void_invites
        else step
        for step in _REVOCATION_STEPS
    )
    _run_steps(member, steps)


def regenerate_member_credentials(member: Member) -> None:
    """Every credential the member HOLDS dies -- including the invites she minted herself --
    while what belongs to the rest of the family survives: her digest subscription, and the
    invites other admins issued into her yards.

    For ROTATION: the member is still here and only her own link is being replaced. Not for a
    membership SHRINK, which has its own registry now — `revoke_for_membership_shrink` above,
    where the invite scope is the sides being LOST rather than the ones she keeps. Same
    generation bump, same single transaction as revoke_member_credentials.
    """
    _run_steps(member, _REGENERATION_STEPS)


def _run_steps(member: Member, steps: tuple[RevocationStep, ...]) -> None:
    """Run a registry of steps plus the generation bump in ONE transaction.

    Typed concretely rather than as `tuple[object, ...]` with a `type: ignore[operator]`:
    that ignore turned off exactly the check that matters here, since a non-callable
    slipping into a revocation registry is precisely the mistake that would leave a
    credential class alive.
    """
    with transaction.atomic():
        locked = Member.objects.select_for_update().get(pk=member.pk)
        for step in steps:
            step(locked)
        _bump_generation(locked)
