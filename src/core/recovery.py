"""Admin-issued password recovery (BY-01): issue, resolve, redeem.

The gap this closes: email is optional at join (S-101), so a member who gave none
has no `Forgot your password?` path — and no admin control existed to fix it, so the
only cure was `manage.py changepassword` at a server shell. That is not a path a
non-technical yard admin holds.

The shape is the one this product already hands out credentials with (invites, elder
links): the admin mints a one-time link on a page, sees the raw value exactly once,
and hands it over by text or reads it out. Nothing is emailed, because the member
having no email is the whole reason they are here.

Discipline (TM-5, ADR-003, mirroring elder_tokens):

* 256-bit CSPRNG raw value, SHA-256 at rest, returned once and never stored or logged.
* One live token per member (the OneToOne), so issuing a new link kills the old one.
* Single use: redeeming stamps `used_at`, and a used row never resolves again.
* 48 hours, then dead.
* The carried generation is checked on resolve, so the TM-1 revocation act (removal,
  regeneration) kills an outstanding link like every other credential class.
* Every failure shape — unknown, expired, used, revoked by generation — raises the
  same bare RecoveryInvalid, which the view renders as the byte-identical 404, so the
  link is not an account-existence oracle (S-202 parity).

Minting refuses a non-HTTPS production base URL for the same reason elder_tokens does
(T-EDGE-1): a recovery link is a password-setting capability and must not be minted
against a base URL that would carry it in the clear.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone

from .models import Member, RecoveryToken

# Long enough to survive being read out over the phone and typed in this evening,
# short enough that a link left in a text thread is dead by the weekend.
TTL_HOURS = 48


class RecoveryRefused(Exception):
    """Minting refused: a member with no login to recover, a supervised account
    (TM-10: their parent holds them), or an insecure base URL."""


class RecoveryInvalid(Exception):
    """Unknown, expired, already used, or revoked. Carries nothing; renders as a 404."""


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _require_secure_base() -> None:
    base = settings.BASE_URL.lower()
    is_local = any(host in base for host in ("localhost", "127.0.0.1"))
    if not base.startswith("https://") and not is_local:
        raise RecoveryRefused(
            "Recovery links only mint against an https base URL in production (T-EDGE-1)."
        )


def issue(member: Member, *, issued_by: Member) -> str:
    """Mint `member`'s recovery link, replacing any prior one, and return the raw token
    exactly once — for the page that hands it over.

    Authorization is the CALLER's (permissions.can_manage_member); what this refuses is
    the two cases where the act is meaningless rather than unauthorized. A member with no
    `user` (an elder, who holds a token link instead) has no password to recover, and a
    supervised child's account is their parent's by design (TM-10), so handing a third
    party a password-setting link for it would route around the one person who controls
    it.
    """
    if member.is_supervised:
        raise RecoveryRefused("A supervised account is recovered by its parent (TM-10).")
    if member.user_id is None:
        raise RecoveryRefused("This person has no password to reset.")
    _require_secure_base()
    raw = secrets.token_urlsafe(32)  # 256 bits
    RecoveryToken.objects.update_or_create(
        member=member,
        defaults={
            "token_digest": _digest(raw),
            "minted_generation": member.token_generation,
            "issued_by": issued_by,
            "expires_at": timezone.now() + timedelta(hours=TTL_HOURS),
            # An earlier link that was already redeemed leaves used_at set on the row this
            # update_or_create reuses. Clearing it is what makes re-issuing work at all:
            # without it the fresh token would resolve as spent from the moment it is minted.
            "used_at": None,
        },
    )
    return raw


def resolve(raw: str) -> RecoveryToken:
    """The live token behind a raw value, or RecoveryInvalid.

    Read-only: loading the link never consumes it (S-101's rule for invites, for the
    same reason — a mail scanner or a link preview must not burn somebody's only way
    back in). `redeem` is the authoritative consume and re-checks everything here
    under a row lock.
    """
    if not raw:
        raise RecoveryInvalid
    token = (
        RecoveryToken.objects.select_related("member", "member__user")
        .filter(token_digest=_digest(raw))
        .first()
    )
    if token is None:
        raise RecoveryInvalid
    if token.used_at is not None:
        raise RecoveryInvalid
    if token.minted_generation != token.member.token_generation:
        raise RecoveryInvalid
    if token.expires_at <= timezone.now():
        raise RecoveryInvalid
    return token


def redeem(raw: str, new_password: str) -> None:
    """Set the member's password from a live recovery link, atomically, once.

    The row is locked and every precondition re-checked under that lock, so two
    concurrent redeems of one link resolve to exactly one password change — the same
    one-use discipline as redeem_invite.

    Changing the password rotates Django's session auth hash, so EVERY existing session
    for this account (including one an attacker may hold, which is a reason somebody
    asks for this link) is invalid on its next request. That is the same mechanism the
    break-glass reset relies on (T-RECOV-1).

    Raises ValidationError for a password Django's validators refuse, which the view
    renders as messages; the token SURVIVES that, because a rejected password is a typo,
    not an attack, and burning the link on one would lock the member out for good. The
    validation is here rather than only in the view so the service stays the mandatory
    path: there is no way to set a password through this token that skips the validators.
    """
    with transaction.atomic():
        token = (
            RecoveryToken.objects.select_for_update()
            .select_related("member", "member__user")
            .filter(token_digest=_digest(raw))
            .first()
        )
        if token is None or token.used_at is not None:
            raise RecoveryInvalid
        if token.minted_generation != token.member.token_generation:
            raise RecoveryInvalid
        if token.expires_at <= timezone.now():
            raise RecoveryInvalid
        user = token.member.user
        if user is None:  # pragma: no cover - issue() refuses a member with no login
            raise RecoveryInvalid
        validate_password(new_password, user)
        user.set_password(new_password)
        user.save(update_fields=["password"])
        RecoveryToken.objects.filter(pk=token.pk).update(used_at=timezone.now())
