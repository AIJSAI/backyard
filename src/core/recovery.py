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
* One live token per member: issuing stamps `superseded_at` on any earlier live row, so
  the old link stops resolving and its record survives instead of being overwritten.
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

import datetime
import hashlib
import secrets
from collections.abc import MutableMapping
from datetime import timedelta
from typing import Any

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
    """Refuse to mint against a base URL that would carry the link in the clear (T-EDGE-1).

    The HOSTNAME, parsed and compared exactly -- not a substring of the whole URL.
    `"localhost" in BASE_URL` is true for `http://localhost.evil.com` and `"127.0.0.1" in
    BASE_URL` for `http://127.0.0.1.evil.com`: an attacker-registrable domain that merely
    CONTAINS the word would be classified local here, in a guard that gates a
    password-setting capability. `config.base_url_guard.is_local_url` is the one
    definition, shared with settings.py's boot check and with elder_tokens -- three
    callers asking the same question, and not three answers to drift apart.
    """
    from config.base_url_guard import is_local_url

    base = settings.BASE_URL
    if not base.lower().startswith("https://") and not is_local_url(base):
        raise RecoveryRefused(
            "Recovery links only mint against an https base URL in production (T-EDGE-1)."
        )


def is_recoverable(member: Member) -> bool:
    """Is there a password behind this member for a link to set?

    THE predicate, and the only copy of it. All three surfaces read this one: the roster's
    affordance (admin_views), the issuing page (recovery_views), and `issue` below. Three
    hand-written copies of the same three clauses is how the roster came to offer a
    "get back in" link for a removed member — the gate held in one place and not the other
    two, so the control failed at the last step instead of the first.

    * A supervised child's account is their parent's by design (TM-10).
    * A member with no `user` is an elder: she holds a token link, not a password.
    * A member whose `user` is INACTIVE has been removed (removal.py step 3). The Member
      row survives — that is what keeps their posts attributable — so they stay on the
      instance admin's roster, and a link minted for them redeems cleanly and then hands
      them to a sign-in Django will always refuse.
    """
    account = member.user
    return not member.is_supervised and account is not None and account.is_active


def issue(member: Member, *, issued_by: Member) -> str:
    """Mint `member`'s recovery link, replacing any prior one, and return the raw token
    exactly once — for the page that hands it over.

    Authorization is the CALLER's (permissions.can_manage_member); what this refuses is
    the cases where the act would be meaningless rather than unauthorized, and it refuses
    them through `is_recoverable` — the same predicate the roster and the issuing page
    read, so a control is never offered that this then declines.
    """
    if not is_recoverable(member):
        # Two refusals, ONE predicate. The message is a detail for whoever called this; the
        # rule itself has a single home, so it cannot say one thing here and another on the
        # roster.
        if member.is_supervised:
            raise RecoveryRefused("A supervised account is recovered by its parent (TM-10).")
        raise RecoveryRefused("This person has no password to reset.")
    _require_secure_base()
    raw = secrets.token_urlsafe(32)  # 256 bits
    now = timezone.now()
    with transaction.atomic():
        # One live link per member, kept by SUPERSEDING the earlier ones rather than
        # overwriting a single row. The old link stops resolving either way; the difference
        # is that its record — who issued it, when, and whether it was ever redeemed —
        # survives the next issuance instead of being cleared to make room.
        #
        # A row that is already used or already superseded is left alone: it is finished,
        # and re-stamping it would overwrite the timestamp of the event that finished it.
        RecoveryToken.objects.filter(
            member=member, used_at__isnull=True, superseded_at__isnull=True
        ).update(superseded_at=now)
        RecoveryToken.objects.create(
            member=member,
            token_digest=_digest(raw),
            minted_generation=member.token_generation,
            issued_by=issued_by,
            expires_at=now + timedelta(hours=TTL_HOURS),
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
    if token.superseded_at is not None:
        raise RecoveryInvalid
    if token.minted_generation != token.member.token_generation:
        raise RecoveryInvalid
    if token.expires_at <= timezone.now():
        raise RecoveryInvalid
    return token


# The session key `recovery_views.recover` writes after a successful redeem and
# `core.forms.LoginForm` pops on the next render of the sign-in page (walk item 2). It
# lives HERE, in the service both sides already depend on, rather than in either of them:
# the form importing a views module is a cycle waiting to happen, and two spellings of one
# key is how a prefill quietly stops working while the page still looks fine.
RECOVERED_USERNAME_KEY = "recovered_username"
# HOW LONG THE PREFILL IS HONOURED. The session key is written the moment a link is
# redeemed and popped when the sign-in form next renders — but nothing guarantees that
# render ever happens. Somebody who saves a new password and then closes the tab leaves
# their username sitting in the session of a browser that, on the shared family tablet
# this product is partly for, the next person picks up. Ten minutes is the walk from
# "Save it and sign in" to the sign-in page with room to spare, and short enough that a
# borrowed device is not carrying somebody's username around.
#
# NOT `session.set_expiry`, which was the obvious reach and is wrong here: `login()`
# cycles the session key but KEEPS its data, so a short expiry would follow them past the
# sign-in and log them out minutes after they finally got back in. The stamp is checked
# by hand instead, and the value is popped either way.
RECOVERED_USERNAME_TTL = timedelta(minutes=10)


def remember_the_recovered_username(session: MutableMapping[str, Any], username: str) -> None:
    """Record who just used a link, with the moment it happened.

    Called only after `redeem` returns, which happens only for a live, unused, unexpired,
    un-superseded token — so nothing on any failure path can put a username here.
    """
    session[RECOVERED_USERNAME_KEY] = {
        "username": username,
        "at": timezone.now().isoformat(),
    }


def take_the_recovered_username(session: MutableMapping[str, Any]) -> str:
    """The username to prefill, once, if the link was used in the last ten minutes.

    POPPED regardless of the answer: a stamp too old is a value that should not be sitting
    there at all, and leaving it would mean the next render got a second chance at it.
    """
    stored = session.pop(RECOVERED_USERNAME_KEY, None)
    if not isinstance(stored, dict):
        # Nothing, or a value from before this was a dict. Either way, no prefill.
        return ""
    username = stored.get("username") or ""
    try:
        used_at = datetime.datetime.fromisoformat(str(stored.get("at")))
    except ValueError:
        return ""
    if timezone.now() - used_at > RECOVERED_USERNAME_TTL:
        return ""
    return str(username)


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
        # No select_related on the lock. Member.user is nullable, so joining it makes a
        # LEFT OUTER JOIN and Postgres refuses `FOR UPDATE` on the nullable side of one
        # ("FOR UPDATE cannot be applied to the nullable side of an outer join"). The row
        # this needs locked is the token's anyway; the member and the user are read after.
        token = RecoveryToken.objects.select_for_update().filter(token_digest=_digest(raw)).first()
        if token is None or token.used_at is not None or token.superseded_at is not None:
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
