"""The per-recipient digest builder (S-501): the digest IS the feed, provably.

build_digest assembles one email for one (member, yard) issue, and its every
content byte resolves through the audience guard AT BUILD TIME: posts via
digest_links.issue_posts (a filter over scoping.visible_posts), comment counts
via scoping.visible_comments, dates via profiles.upcoming_dates scoped to the
issue's yard. This module NEVER touches a model manager, raw SQL, or any
second audience path (TM-2, T-YARD-9). That rule is enforced by
structure, not vigilance — scripts/check_digest_confinement.py fails CI if a
banned data-access token ever appears here, and the pytest twin proves the
guard non-vacuous.

The output is a CLOSED union of typed blocks. build_digest validates every
block against the union and every link against BASE_URL before returning, so a
non-family content block (a promo, a tracker, an off-origin link) is a build
failure, never an email. The digest is 100% family content, forever, verified
by a test that fails on any non-family block (S-501 acceptance, verbatim).

Purity contract: the builder takes the issue plus pre-minted raw tokens and
returns a value. It writes nothing, sends nothing, and holds no clock of its
own; the send path (next increment) owns minting, transactions, and transport.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from . import digest_links, emailing, profiles, scoping
from .models import DigestIssue

# The upcoming-dates lookahead (S-903: "the next 7 days in my yards").
UPCOMING_DAYS = 7


@dataclass(frozen=True)
class HeaderBlock:
    yard_name: str
    window_text: str


@dataclass(frozen=True)
class PostBlock:
    author_line: str  # "Nana (Ann)" — display and kinship name, never more
    date_text: str
    body: str
    url: str  # the /d/ deep link for this post
    photo_count: int  # photos degrade to the deep link until W3's signer lands
    reply_count: int


@dataclass(frozen=True)
class DateEntry:
    name_line: str
    kind: str  # "birthday" or "anniversary"
    date_text: str  # "March 5"; never a year, never an age


@dataclass(frozen=True)
class UpcomingDatesBlock:
    entries: tuple[DateEntry, ...]


@dataclass(frozen=True)
class FooterBlock:
    digest_url: str
    unsubscribe_url: str
    standing_text: str  # T-EMAIL-G3, the anti-phish constant


# The closed union (S-501's 100%-family gate). A new block type is added HERE,
# in code review, never discovered in a rendered email.
DigestBlock = HeaderBlock | PostBlock | UpcomingDatesBlock | FooterBlock
_BLOCK_UNION = (HeaderBlock, PostBlock, UpcomingDatesBlock, FooterBlock)


@dataclass(frozen=True)
class DigestEmail:
    subject: str
    text: str
    html: str
    blocks: tuple[DigestBlock, ...]


class NonFamilyContent(Exception):
    """A block outside the closed union, or a link off the instance's own
    origin, tried to enter a digest. Refusing to build is the point."""


def _family_urls_of(block: DigestBlock) -> list[str]:
    if isinstance(block, PostBlock):
        return [block.url]
    if isinstance(block, FooterBlock):
        return [block.digest_url, block.unsubscribe_url]
    return []


def validate_blocks(blocks: tuple[DigestBlock, ...]) -> None:
    """The 100%-family gate: every block is of the closed union, every link is
    on the instance's own origin. Runs inside build_digest on every build; the
    negative test proves it trips on an injected foreign block."""
    base = f"{settings.BASE_URL}/"
    for block in blocks:
        if not isinstance(block, _BLOCK_UNION):
            raise NonFamilyContent(f"block outside the closed union: {type(block).__name__}")
        for url in _family_urls_of(block):
            if not url.startswith(base):
                raise NonFamilyContent(f"off-origin link in a digest: {url!r}")


def build_digest(issue: DigestIssue, *, digest_token: str, unsubscribe_token: str) -> DigestEmail:
    """One digest email for one (member, yard) issue, resolved live (TM-2).

    Deleted posts, narrowed audiences, and changed date visibility between
    window close and this call simply do not appear: every read below goes
    through the guard NOW. The two raw tokens are minted by the send path and
    only embedded here; the builder never touches token storage.
    """
    member = issue.member
    yard = issue.yard
    digest_url = emailing.absolute_url(f"/d/{digest_token}/")

    post_blocks = [
        PostBlock(
            author_line=(
                f"{post.author.display_name} ({post.author.kinship_name})"
                if post.author.kinship_name
                else post.author.display_name
            ),
            date_text=post.created_at.strftime("%B %-d"),
            body=post.body,
            url=emailing.absolute_url(f"/d/{digest_token}/posts/{post.id}/"),
            photo_count=scoping.visible_media(member).filter(post=post).count(),
            reply_count=scoping.visible_comments(member).filter(post=post).count(),
        )
        for post in digest_links.issue_posts(issue).select_related("author").order_by("created_at")
    ]

    date_entries = tuple(
        DateEntry(
            name_line=(
                f"{d.display_name} ({d.kinship_name})" if d.kinship_name else d.display_name
            ),
            kind=d.kind,
            date_text=d.date_text,
        )
        for d in profiles.upcoming_dates(
            member,
            start=timezone.localdate(),
            days=UPCOMING_DAYS,
            within_yard=yard,
        )
    )

    window_text = (
        f"{issue.window_start.strftime('%B %-d')} to {issue.window_end.strftime('%B %-d')}"
    )
    blocks: tuple[DigestBlock, ...] = (
        HeaderBlock(yard_name=yard.name, window_text=window_text),
        *post_blocks,
        *((UpcomingDatesBlock(entries=date_entries),) if date_entries else ()),
        FooterBlock(
            digest_url=digest_url,
            unsubscribe_url=emailing.absolute_url(f"/digest/unsubscribe/{unsubscribe_token}/"),
            standing_text=emailing.STANDING_FOOTER,
        ),
    )
    validate_blocks(blocks)

    context = {
        "header": blocks[0],
        "post_blocks": post_blocks,
        "dates_block": next((b for b in blocks if isinstance(b, UpcomingDatesBlock)), None),
        "footer": blocks[-1],
    }
    return DigestEmail(
        subject=f"{yard.name}: your family digest",
        text=render_to_string("core/email/digest.txt", context),
        html=render_to_string("core/email/digest.html", context),
        blocks=blocks,
    )
