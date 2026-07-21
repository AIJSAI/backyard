"""Per-digest read links (ADR-003, TM-5): mint, resolve, and the issue slice.

The token in a digest deep link only AUTHENTICATES (this member, this issue).
Authorization never lives here: every render behind it routes through
core/scoping's one audience query at request time, so a token-specific
authorization path (the bug ADR-003 rule 5 predicts) structurally does not
exist, and deleted or narrowed content drops out of a still-valid link because
the slice is re-resolved live on every request.

Failure shapes are deliberate (T-TOKEN-2): a row that never existed and a token
killed by revocation resolve identically (DigestLinkInvalid, rendered as the
guard's byte-identical 404 — revocation never reveals that there was something
to revoke). Only a genuine token past its freshness window gets the distinct
capability-free "ask your family for a fresh one" page (DigestLinkExpired).
The generation check runs before the expiry check so a revoked-and-expired
token is still a bare 404.
"""

from __future__ import annotations

import datetime
import hashlib
import secrets

from django.db import models
from django.utils import timezone

from . import scoping
from .models import DigestIssue, DigestToken, Post

# The freshness bound. ADR-003 rule 1 commits to "weeks" so a digest opened from
# a two-week-old email still works for an elder; 21 days is the proposed default,
# recorded for founder ratification at the wave boundary. Revocation, not TTL, is
# the kill mechanism (rule 3).
DIGEST_LINK_TTL = datetime.timedelta(days=21)


class DigestLinkInvalid(Exception):
    """Unknown token or one killed by revocation. Carries nothing; renders as the
    byte-identical 404."""


class DigestLinkExpired(Exception):
    """A genuine token past its freshness window. Renders the friendly,
    capability-free page, never any content."""


def _digest(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def mint(issue: DigestIssue) -> str:
    """Mint the read token for one issue. The raw value is returned exactly once,
    to be embedded in that issue's email, and never stored."""
    raw = secrets.token_urlsafe(32)  # 256 bits
    DigestToken.objects.create(
        issue=issue,
        member=issue.member,
        token_digest=_digest(raw),
        minted_generation=issue.member.token_generation,
        expires_at=timezone.now() + DIGEST_LINK_TTL,
    )
    return raw


def resolve(raw_token: str) -> DigestToken:
    """The live token behind a raw value, or the correct failure shape.

    Order is load-bearing: generation (revocation) is checked before expiry, so a
    revoked token is a bare 404 even when it is also stale.
    """
    if not raw_token:
        raise DigestLinkInvalid
    token = (
        DigestToken.objects.select_related("member", "issue", "issue__yard")
        .filter(token_digest=_digest(raw_token))
        .first()
    )
    if token is None:
        raise DigestLinkInvalid
    if token.minted_generation != token.member.token_generation:
        raise DigestLinkInvalid  # revoked resolves exactly like never-existed
    if token.expires_at <= timezone.now():
        raise DigestLinkExpired
    if token.first_used_at is None:
        # The one-time open proxy (S-705): a single stamp, never an open log.
        DigestToken.objects.filter(pk=token.pk, first_used_at__isnull=True).update(
            first_used_at=timezone.now()
        )
    return token


def issue_posts(issue: DigestIssue) -> models.QuerySet[Post]:
    """The posts one issue covers, resolved live: a FILTER over the one audience
    query (TM-2), never a re-derivation of audience.

    Per-yard slicing (S-501: no email fuses two yards): a post is in this yard's
    issue if it addresses this yard, or is pod-only in a pod that belongs to this
    yard (the bridge household's pod-only posts appear in each side's issue; the
    pod spans, the yard never fuses). Because the base queryset is
    scoping.visible_posts evaluated NOW, a post deleted or narrowed after the
    email went out is simply absent from the still-valid link.
    """
    in_this_yard = models.Q(audience_yards=issue.yard) | models.Q(
        audience_yards__isnull=True, pod__yards=issue.yard
    )
    return (
        scoping.visible_posts(issue.member)
        .filter(in_this_yard)
        .filter(created_at__gte=issue.window_start, created_at__lt=issue.window_end)
        .distinct()
    )
