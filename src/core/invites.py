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


class InviteInvalid(Exception):
    """Raised for every unusable invite, with one indistinguishable message."""

    MESSAGE = "invite not usable"

    def __init__(self) -> None:
        super().__init__(self.MESSAGE)


def _digest(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def mint_invite(
    pod: Pod,
    created_by: Member | None,
    *,
    ttl_days: int = DEFAULT_TTL_DAYS,
    max_uses: int = 8,
) -> tuple[Invite, str]:
    """Create an invite and return it with the raw token, which exists only in
    this return value: the caller shows it once and never stores it."""
    raw = secrets.token_urlsafe(32)  # 256 bits
    invite = Invite.objects.create(
        pod=pod,
        created_by=created_by,
        token_digest=_digest(raw),
        expires_at=timezone.now() + timedelta(days=ttl_days),
        max_uses=max_uses,
    )
    return invite, raw


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

        member = Member.objects.create(display_name=display_name, user_id=user_id)
        PodMembership.objects.create(member=member, pod=invite.pod)
        InviteRedemption.objects.create(invite=invite, member=member)
        Invite.objects.filter(pk=invite.pk).update(use_count=models.F("use_count") + 1)
        return member
