"""Invite minting and redemption: the first bearer credential after sessions.

Rules (S-101, S-201, T-INVITE-1, T-YARD-G1, threat row TS-DJ-5):

- The raw token is 256 bits from a CSPRNG, shown once at mint, stored only as a
  SHA-256 digest. Lookup is by digest; the row never holds the secret.
- Redemption is one transaction with the invite row locked: two concurrent
  redeems of a one-use invite cannot both mint a member.
- Every failure mode (unknown, expired, revoked, exhausted) raises the same
  InviteInvalid with the same message, so nothing upstream can leak which one it
  was: the view maps it to the byte-identical 404 (S-202 parity for invites).
- Redemption records who joined from which invite (InviteRedemption), the join
  visibility S-201's hardening requires.

The rate limit on the redemption endpoint and the EmailAddress.verified rule bind
when the allauth signup surface lands (TS-DJ-5 properties 3 and 4); the service
layer here carries properties 1 and 2.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.db import models, transaction
from django.utils import timezone

from .models import Invite, InviteRedemption, Member, Pod, PodMembership

DEFAULT_TTL_DAYS = 7  # expire by default: days, not never (S-201 hardening)

# THE ONLY ROLE A LINK MAY EVER CARRY (R2-6, T-INVITE-2). A side admin reaches one side of
# the family; the family admin reaches all of them, and the only way into that role is one
# named person promoting another on the roster, where somebody's face is behind the act.
# A bearer link has no face: whoever holds it is whoever holds it.
#
# A frozenset of one rather than a bare constant, because the thing being expressed is
# "the set of roles a link may grant", and the day a second one is proposed this is where
# the argument about it has to happen.
GRANTABLE_BY_LINK = frozenset({Member.YARD_ADMIN})


class InviteInvalid(Exception):
    """Raised for every unusable invite, with one indistinguishable message."""

    MESSAGE = "invite not usable"

    def __init__(self) -> None:
        super().__init__(self.MESSAGE)


class RoleNotGrantableByLink(ValueError):
    """Refused: something asked for an invite that would hand out a role a link may not.

    Deliberately NOT an `InviteInvalid`. That exception exists to be indistinguishable —
    every unusable-invite path raises the same message so the join page cannot be used as
    an oracle for which invites exist. This is the opposite situation: it is a programming
    error, or a forged request on an ADMIN surface, where the person on the other end is
    entitled to know exactly what was refused and nothing is leaked by saying so.
    """


def _digest(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def mint_invite(
    pod: Pod,
    created_by: Member | None,
    *,
    ttl_days: int = DEFAULT_TTL_DAYS,
    max_uses: int = 8,
    grants_role: str | None = None,
) -> tuple[Invite, str]:
    """Create an invite and return it with the raw token, which exists only in
    this return value: the caller shows it once and never stores it.

    `grants_role` is None for every ordinary invite and for every call site that predates
    it. The only other value this accepts is the side-admin role, and the refusal lives
    here rather than only in the view because the authority a link carries must not depend
    on which surface minted it — a management command, a future API, or a test helper
    reaching this function gets the same cap the form gets.
    """
    if grants_role is not None and grants_role not in GRANTABLE_BY_LINK:
        raise RoleNotGrantableByLink(
            f"An invite link may grant {sorted(GRANTABLE_BY_LINK)} and nothing else, never "
            f"{grants_role!r}. A link has no face on the other end of it; the family-admin "
            "role is granted by one named person to another, on the roster."
        )
    raw = secrets.token_urlsafe(32)  # 256 bits
    invite = Invite.objects.create(
        pod=pod,
        created_by=created_by,
        token_digest=_digest(raw),
        expires_at=timezone.now() + timedelta(days=ttl_days),
        max_uses=max_uses,
        grants_role=grants_role,
    )
    return invite, raw


def inviter_of(member: Member) -> Member | None:
    """Who made the invite this member joined from, if that person is still here (BY-13).

    A plain member cannot issue invites in v1 (can_issue_invite refuses the role), and no
    page they can reach said whose job it is — so the fifth step of the member walk, invite
    someone else, could not be completed by the person who had just been invited, and the
    product never said so out loud. The name is already recorded, so answering "ask them"
    needs no new field: InviteRedemption links the member to their invite, and
    Invite.created_by is set at mint.

    None when they were not created from an invite (the founder, an elder, a supervised
    child) or when the issuer has since been removed — created_by is SET_NULL, so the
    caller falls back to a sentence that names nobody rather than rendering a blank.
    """
    redemption = (
        InviteRedemption.objects.filter(member=member)
        .select_related("invite__created_by")
        .order_by("-created_at")
        .first()
    )
    return redemption.invite.created_by if redemption is not None else None


def peek_invite(raw_token: str) -> Invite:
    """Return the invite if it is currently redeemable, else raise InviteInvalid.

    Read-only, no lock, no consume: for the join page's GET, which shows the form
    only for a live invite and 404s otherwise. The authoritative atomic consume is
    redeem_invite; a peek that passes here can still lose the race at redeem time,
    which the view handles by 404ing there too. Raises the same indistinguishable
    InviteInvalid as redeem, so the GET is not a sharper oracle than the POST.
    """
    try:
        invite = Invite.objects.get(token_digest=_digest(raw_token))
    except Invite.DoesNotExist:
        raise InviteInvalid from None
    now = timezone.now()
    if invite.revoked_at is not None or invite.expires_at <= now:
        raise InviteInvalid
    if invite.use_count >= invite.max_uses:
        raise InviteInvalid
    return invite


def redeem_invite(raw_token: str, *, display_name: str, user_id: int | None) -> Member:
    """Mint a member from an invite, atomically, or raise InviteInvalid.

    The invite row is locked for the whole transaction and every precondition is
    re-checked under that lock, so the one-use race resolves to exactly one
    member. Loading an invite URL never calls this; only the explicit join POST
    does (S-101: no membership by URL side effect).

    Caller contract (security review L-4): a user_id already linked to a Member,
    or one that does not exist, raises IntegrityError, not InviteInvalid. The
    S-101 signup view maps both to the same generic failure the redemption 404s
    with, so the byte-identical-404 guarantee holds on that edge too.

    A ROLE-GRANTING LINK (R2-6) hands its role to the FIRST person through it and to
    nobody after them, and that decision is made HERE, inside the same lock and off the
    same `use_count` read the one-use cap already uses. Two phones opening the link at the
    same instant therefore cannot both come out as the side admin: one transaction sees
    `use_count == 0` and the other sees 1, because the increment below happens before
    either releases the row. Deciding it anywhere else — in the view, after the member
    exists — would be exactly the double-redeem race this function was written to close,
    wearing a different outcome.
    """
    with transaction.atomic():
        try:
            invite = Invite.objects.select_for_update().get(token_digest=_digest(raw_token))
        except Invite.DoesNotExist:
            raise InviteInvalid from None

        now = timezone.now()
        if invite.revoked_at is not None or invite.expires_at <= now:
            raise InviteInvalid
        if invite.use_count >= invite.max_uses:
            raise InviteInvalid

        # The cap, applied again at the moment the role is handed over. The model's CHECK
        # constraint and `mint_invite` both refuse to WRITE anything but the side-admin
        # role; this refuses to APPLY anything else, so a row edited by hand at a database
        # shell — the one route that goes around both — still cannot mint a family admin.
        granted = invite.grants_role if invite.use_count == 0 else None
        role = granted if granted in GRANTABLE_BY_LINK else Member.MEMBER

        member = Member.objects.create(display_name=display_name, user_id=user_id, role=role)
        PodMembership.objects.create(member=member, pod=invite.pod)
        InviteRedemption.objects.create(invite=invite, member=member)
        Invite.objects.filter(pk=invite.pk).update(use_count=models.F("use_count") + 1)
        return member
