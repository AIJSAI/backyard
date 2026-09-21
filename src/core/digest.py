"""The per-recipient digest builder (S-501): the digest IS the feed, provably.

build_digest assembles one email for one (member, yard) issue, and its every
content byte resolves through the audience guard AT BUILD TIME: posts via
digest_links.issue_posts (a filter over scoping.visible_posts), the joined
line's names via digest_links.issue_arrival_names (the same filter over the
same query), comment counts via scoping.visible_comments, dates via
profiles.upcoming_dates scoped to the issue's yard. This module NEVER touches
a model manager, raw SQL, or any second audience path (TM-2, T-YARD-9). That
rule is enforced by structure, not vigilance — scripts/check_digest_confinement.py
fails CI if a banned data-access token ever appears here, and the pytest twin
proves the guard non-vacuous.

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

from collections.abc import Sequence
from dataclasses import dataclass

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from . import digest_links, digesting, emailing, profiles, scoping
from .models import DigestIssue

# The upcoming-dates lookahead (S-903: "the next 7 days in my yards").
UPCOMING_DAYS = 7

# The deterministic reply separator (T-EMAIL-G2): baked into every digest as
# the first body line, so inbound stripping never guesses. A reply's text sits
# above it; the quoted digest (separator included) sits below.
REPLY_SEPARATOR = "=== reply above this line ==="


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
    # The app's own thread, anchored at the reply box. This is the reply affordance the
    # email offers, and it deliberately carries NO capability: clicking it lands on the
    # login wall and you reply as yourself. The per-post reply ADDRESS is a bearer
    # credential (T-EMAIL-2: "a forwarded digest leaks reply capabilities, so a stranger
    # or excluded relative posts as the elder"), and printing it in every digest body
    # was how it travelled. Founder decision 2026-07-29: the reply action opens the app.
    reply_url: str
    reply_address: str  # "reply-<capability>@<our domain>", or "" when absent


@dataclass(frozen=True)
class DateEntry:
    name_line: str
    kind: str  # "birthday" or "anniversary"
    date_text: str  # "March 5"; never a year, never an age


@dataclass(frozen=True)
class UpcomingDatesBlock:
    entries: tuple[DateEntry, ...]


@dataclass(frozen=True)
class ArrivalsBlock:
    """Who joined in this window, as one line after the posts (#208).

    The first Email Update a real family received had five entries, three of which were
    arrival cards; in a week when a side of the family is being invited the message would
    be almost nothing else. The cards stay in the feed exactly as they are — this is the
    message deciding that an arrival is news about the family, not an entry of its own.

    Two values rather than a finished sentence: the three surfaces that show this line
    (the text part, the HTML part, and the web copy at /d/) each write the words in their
    own template, which is where the copy guards read them.
    """

    period_text: str  # "this week" — the reader's own cadence, never a fixed word
    names_text: str  # "Nell, Sam and Dave" — first names, the way a person writes a list


@dataclass(frozen=True)
class FooterBlock:
    digest_url: str
    unsubscribe_url: str
    standing_text: str  # T-EMAIL-G3, the anti-phish constant


# The closed union (S-501's 100%-family gate). A new block type is added HERE,
# in code review, never discovered in a rendered email.
DigestBlock = HeaderBlock | PostBlock | ArrivalsBlock | UpcomingDatesBlock | FooterBlock
_BLOCK_UNION = (HeaderBlock, PostBlock, ArrivalsBlock, UpcomingDatesBlock, FooterBlock)


@dataclass(frozen=True)
class DigestEmail:
    subject: str
    text: str
    html: str
    blocks: tuple[DigestBlock, ...]


class NonFamilyContent(Exception):
    """A block outside the closed union, or a link off the instance's own
    origin, tried to enter a digest. Refusing to build is the point."""


def _reply_domain() -> str:
    return settings.DEFAULT_FROM_EMAIL.rsplit("@", 1)[1]


def _family_urls_of(block: DigestBlock) -> list[str]:
    if isinstance(block, PostBlock):
        # BOTH links, so the on-origin guard covers the new one too. A reply_url left
        # out of this list would be the one link in a digest nothing checked.
        return [block.url, block.reply_url]
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
        if isinstance(block, PostBlock) and block.reply_address:
            if not block.reply_address.endswith("@" + _reply_domain()):
                raise NonFamilyContent(
                    f"reply address off the sending domain: {block.reply_address!r}"
                )


def _as_a_person_writes_a_list(names: Sequence[str]) -> str:
    """Nell / Nell and Sam / Nell, Sam and Dave. No serial comma, which is how the issue's
    own example reads and how the rest of the product writes a list of people."""
    if len(names) <= 2:
        return " and ".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def arrivals_block(issue: DigestIssue) -> ArrivalsBlock | None:
    """The joined line for one issue, or None when nobody joined in its window.

    Public, and called by the /d/ web copy as well as by the builder below: two surfaces
    showing one message must not each decide who joined and how to say it.

    The names come through digest_links, which is scoping-bound like every other read
    here, so the line can only name people this recipient may already see. The cadence
    comes through digesting, which owns the subscription: it is the reader's own setting
    rather than family content, and this module still holds no data path of its own.
    """
    names = digest_links.issue_arrival_names(issue)
    if not names:
        return None
    return ArrivalsBlock(
        period_text=digesting.cadence_period_text(issue.member),
        names_text=_as_a_person_writes_a_list(names),
    )


def build_digest(
    issue: DigestIssue,
    *,
    digest_token: str,
    unsubscribe_token: str,
    reply_addresses: dict[int, str] | None = None,
) -> DigestEmail:
    """One digest email for one (member, yard) issue, resolved live (TM-2).

    Deleted posts, narrowed audiences, and changed date visibility between
    window close and this call simply do not appear: every read below goes
    through the guard NOW. The two raw tokens are minted by the send path and
    only embedded here; the builder never touches token storage.
    """
    member = issue.member
    yard = issue.yard
    reply_map = reply_addresses or {}
    digest_url = emailing.absolute_url(f"/d/{digest_token}/")

    post_blocks = [
        PostBlock(
            author_line=(
                f"{post.author.display_name} ({post.author.kinship_name})"
                if post.author.kinship_name
                else post.author.display_name
            ),
            # "Sep 18", the product's one date shape: core/templatetags/times.py pins
            # DATE_FORMAT as "M j, Y" and every screen writes the month abbreviated. This
            # was the only surface spelling it out in full.
            date_text=timezone.localtime(post.created_at).strftime("%b %-d"),
            body=post.body,
            url=emailing.absolute_url(f"/d/{digest_token}/posts/{post.id}/"),
            # Count the member's OWN photos only (through the scoping layer, TM-2): a
            # re-hosted link-preview image is the card's picture, not a photo on the post,
            # and post-detail's gallery excludes it too, so counting it would tell a member
            # "1 photo" then show them none (security review MEDIUM-1, S-301).
            photo_count=scoping.visible_attached_media(member).filter(post=post).count(),
            reply_count=scoping.visible_comments(member).filter(post=post).count(),
            # Through emailing.absolute_url like every other outbound link, not a raw
            # f-string: the helper refuses a non-site-absolute or protocol-relative path
            # and any whitespace or control character, so one place governs how a link
            # leaves this instance. Reviewer catch on #101.
            reply_url=emailing.absolute_url(f"/posts/{post.id}/#reply"),
            reply_address=reply_map.get(post.id, ""),
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

    # The same abbreviation, and this pair also sets the SUBJECT LINE, which the glossary
    # pins as "New In <Side>: <Mon D> To <Mon D>". It read "New In Whitfield side:
    # September 12 To September 19" — the most-seen string the product sends, and the only
    # place in it using a fourth date format.
    window_start = timezone.localtime(issue.window_start).strftime("%b %-d")
    window_end = timezone.localtime(issue.window_end).strftime("%b %-d")
    window_text = f"{window_start} to {window_end}"
    # After the posts and before the dates: the posts are what happened, the joined line
    # is who arrived while it did, and the dates are what is still coming.
    arrivals = arrivals_block(issue)
    blocks: tuple[DigestBlock, ...] = (
        HeaderBlock(yard_name=yard.name, window_text=window_text),
        *post_blocks,
        *((arrivals,) if arrivals else ()),
        *((UpcomingDatesBlock(entries=date_entries),) if date_entries else ()),
        FooterBlock(
            digest_url=digest_url,
            unsubscribe_url=emailing.absolute_url(f"/digest/unsubscribe/{unsubscribe_token}/"),
            standing_text=emailing.STANDING_FOOTER,
        ),
    )
    validate_blocks(blocks)

    context = {
        "separator": REPLY_SEPARATOR,
        "header": blocks[0],
        "post_blocks": post_blocks,
        "arrivals": arrivals,
        "dates_block": next((b for b in blocks if isinstance(b, UpcomingDatesBlock)), None),
        "footer": blocks[-1],
    }
    return DigestEmail(
        # Belt (#37 review LOW-4): DigestEmail is header-safe as a VALUE, not
        # only when the send seam happens to strip it.
        # The subject is what a relative sees in their inbox list, so it says what is
        # inside: which side, and the days it covers. Title Case like every other subject,
        # except for the side's own name, which is a word a relative typed and is never
        # re-cased. The window is written out again here rather than reusing `window_text`
        # because that one sits inside a sentence in the body and this one is a heading.
        subject=emailing.strip_control(f"New In {yard.name}: {window_start} To {window_end}"),
        text=render_to_string("core/email/digest.txt", context),
        html=render_to_string("core/email/digest.html", context),
        blocks=blocks,
    )
