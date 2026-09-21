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
from .models import DigestIssue, DigestToken, Member, Post

# Link fetches that arrive almost immediately after minting are scanners
# (Outlook SafeLinks, AV prefetch), not people; stamping them would systematically
# OVERCOUNT presence in exactly the managed-mailbox elder segment the metric
# exists to measure (#40 review MEDIUM-3; docs/metrics.md promises undercounts).
SCANNER_GRACE = datetime.timedelta(minutes=10)

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
    now = timezone.now()
    if token.first_used_at is None and now - token.created_at > SCANNER_GRACE:
        # The one-time open proxy (S-705): a single stamp, never an open log.
        # Fetches inside SCANNER_GRACE are delivery-time scanners, ignored.
        DigestToken.objects.filter(pk=token.pk, first_used_at__isnull=True).update(
            first_used_at=now
        )
    return token


def in_yard_posts_q(yard_id: int) -> models.Q:
    """THE in-yard predicate: a post belongs to a yard's slice if it addresses
    that yard, or is pod-only in a pod of that yard. The digest slice and the
    metrics rollup both consume this one Q so the definition cannot drift into
    a second implementation (#40 review MEDIUM-1, the TM-2 pattern)."""
    return models.Q(audience_yards=yard_id) | models.Q(
        audience_yards__isnull=True, pod__yards=yard_id
    )


def window_slice(
    member: Member,
    yard_id: int,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
) -> models.QuerySet[Post]:
    """Everything one (member, yard, window) slice covers, arrival cards included.

    The audience half of the definition, in one place: the two windows below differ
    only in which kind of post they keep, so neither can drift into a second idea of
    what this member may see in this yard over these days.

    This, not `window_posts`, is the CAPABILITY CEILING a digest token opens onto
    (digest_views.digest_post_view). An arrival card is no longer an entry in the
    message, but the messages already sitting in relatives' inboxes link to the ones
    they listed, those links live for three weeks, and a post the reader can see in
    their own feed must not answer a still-valid link with the guard's 404. What
    changed is what a message SAYS, not what its holder may read.
    """
    return (
        scoping.visible_posts(member)
        .filter(in_yard_posts_q(yard_id))
        .filter(created_at__gte=window_start, created_at__lt=window_end)
        .distinct()
    )


def window_posts(
    member: Member,
    yard_id: int,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
) -> models.QuerySet[Post]:
    """The posts one (member, yard, window) slice covers, resolved live.

    Split out of `issue_posts` so the send path can ask "is there anything to
    send?" BEFORE it creates a DigestIssue row. Asking through `issue_posts`
    would have meant minting the issue first and deleting it again on an empty
    window, which is the shape that leaves half-state behind when a run dies.
    One query definition either way, so the email and the is-it-empty check can
    never disagree about what the window contains.

    ARRIVAL CARDS ARE NOT POSTS HERE (#208), and that is load-bearing twice over.
    They are not entries in the email or in its web copy — the window's joiners get
    one line instead — and a window holding nothing but arrivals is an empty window,
    so it still sends nothing at all. "If nobody posted, nothing is sent" is what
    How It Works promises a family, and somebody joining is not somebody posting.
    """
    return window_slice(member, yard_id, window_start, window_end).filter(is_arrival=False)


def window_arrivals(
    member: Member,
    yard_id: int,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
) -> models.QuerySet[Post]:
    """The arrival cards one (member, yard, window) slice covers, resolved live.

    The other half of the same slice, through the same audience query: a card this
    member could not see is not in it, so the line built from these names can only
    ever name people they already know about. A member on one side of a bridging
    household never learns a name from the other side through it.
    """
    return window_slice(member, yard_id, window_start, window_end).filter(is_arrival=True)


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
    return window_posts(issue.member, issue.yard_id, issue.window_start, issue.window_end)


def issue_arrivals(issue: DigestIssue) -> models.QuerySet[Post]:
    """The arrival cards one issue covers, resolved live (the mirror of issue_posts)."""
    return window_arrivals(issue.member, issue.yard_id, issue.window_start, issue.window_end)


def issue_slice(issue: DigestIssue) -> models.QuerySet[Post]:
    """Everything one issue's window covers: what its token may open, entry or not."""
    return window_slice(issue.member, issue.yard_id, issue.window_start, issue.window_end)


def issue_arrival_names(issue: DigestIssue) -> tuple[str, ...]:
    """Who joined in this issue's window, first names, in the order they arrived.

    `Member.short_name` is the first word of the name they chose, which is how a family
    says a list of people; a blank display name falls back to words rather than leaving a
    hole in the sentence, the same fallback the feed's reactor line uses.

    Deduplicated by member: one person can hold two cards inside one window (they joined a
    household and a group from two links), and a line naming somebody twice reads as a bug.
    """
    names: list[str] = []
    seen: set[int] = set()
    for card in issue_arrivals(issue).select_related("author").order_by("created_at", "id"):
        if card.author_id in seen:
            continue
        seen.add(card.author_id)
        full = card.author.display_name.strip() or "A member"
        short = card.author.short_name
        # A member removed with "Keep Their Posts, Without Their Name" is called "A family
        # member" (removal.ANONYMOUS_NAME), whose first word is "A": the one display name
        # whose short form is not a name at all. Anything under two characters is written
        # out in full instead, which is also the right answer for a one-letter first name.
        names.append(short if len(short) > 1 else full)
    return tuple(names)
