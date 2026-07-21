"""The elder master token (S-102, S-104): mint, resolve, regenerate.

The token is the product's core bet: a low-tech elder opens one link and sees
their family, no login, nothing to install. Discipline (TM-5, ADR-003): 256-bit
CSPRNG raw value that lives only in the handed-over link, SHA-256 at rest,
carried generation checked on every resolve so one revocation act kills it and
every session it ever minted. Supervised members can never hold one (TM-10).

Minting refuses a non-HTTPS production base URL (T-EDGE-1): this is the promise
settings.py has carried since Phase 1 ("token links refuse to mint against
non-HTTPS in production"), enforced here now that the token service exists. The
local plain-HTTP repro stays exempt, same as every other TM-8 posture.
"""

from __future__ import annotations

import datetime
import hashlib
import secrets

from django.conf import settings
from django.utils import timezone

from . import revocation
from .models import ElderToken, Member


class ElderTokenRefused(Exception):
    """Minting refused: supervised member (TM-10) or an insecure base URL."""


class ElderTokenInvalid(Exception):
    """Unknown, revoked, or expired. Carries nothing; renders as the bare 404."""


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _require_secure_base() -> None:
    base = settings.BASE_URL.lower()
    is_local = any(host in base for host in ("localhost", "127.0.0.1"))
    if not base.startswith("https://") and not is_local:
        raise ElderTokenRefused(
            "Token links only mint against an https base URL in production (T-EDGE-1)."
        )


def mint(member: Member, *, expires_at: datetime.datetime | None = None) -> str:
    """Mint the member's token, replacing any prior one. Returns the raw value
    exactly once, for the handover link. No expiry by default (ADR-003)."""
    if member.is_supervised:
        raise ElderTokenRefused("Token links cannot be issued to supervised members (TM-10).")
    _require_secure_base()
    raw = secrets.token_urlsafe(32)  # 256 bits
    ElderToken.objects.update_or_create(
        member=member,
        defaults={
            "token_digest": _digest(raw),
            "minted_generation": member.token_generation,
            "expires_at": expires_at,
        },
    )
    return raw


def regenerate(member: Member) -> str:
    """The total regenerate (TM-1, T-TOKEN-5): one act revokes EVERY credential
    the member holds — old token, live elder sessions, digest links, reply
    addresses — then mints fresh under the new generation."""
    revocation.revoke_member_credentials(member)
    member.refresh_from_db()
    return mint(member)


def resolve(raw: str) -> ElderToken:
    """The live token behind a raw value, or ElderTokenInvalid. Every failure
    shape (unknown, revoked by generation, expired) is the same bare exception,
    rendered as the guard's byte-identical 404 (T-TOKEN-4 parity)."""
    if not raw:
        raise ElderTokenInvalid
    token = ElderToken.objects.select_related("member").filter(token_digest=_digest(raw)).first()
    if token is None:
        raise ElderTokenInvalid
    if token.minted_generation != token.member.token_generation:
        raise ElderTokenInvalid
    if token.expires_at is not None and token.expires_at <= timezone.now():
        raise ElderTokenInvalid
    return token
