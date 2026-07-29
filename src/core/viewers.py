"""Who is asking — resolved from any credential that already grants read access.

Three credentials can read family content, and every one of them was built to reach the
same posts through the same audience query:

* a signed-in member's session (the member app),
* a live elder session, minted by exchanging an elder token at ``/t/<token>/`` (S-102),
* a per-issue digest token in the URL at ``/d/<token>/`` (S-501, ADR-003 rule 1).

Until now only the first could fetch a media byte, because ``serve_media`` was
``@login_required``. That silently made the product's central promise undeliverable: a
token-only elder has ``user_id = NULL`` by design (TM-10 forbids her an account), so
every photo on every post she could already read returned 404 — and the digest email's
deep link landed on a page whose images were equally unreachable. She got captions.

**This widens authentication, never authorization.** A resolver answers only *who is
asking*; what that viewer may see stays the one audience query (``scoping.visible_media``
over ``visible_posts``). The threat model already reasoned about this reach: T-TOKEN-1
assesses a leaked elder link as exposing "kids' media", which is only true if the elder
can fetch media at all.

A credential can also carry a CEILING, and ``Reader`` keeps that ceiling attached to the
credential rather than leaving it to each caller to remember. A digest token
authenticates its own member but must never become a general read credential for that
member's other yards and other weeks — ``digest_views`` has always enforced that with the
issue-slice check, and ``Reader.visible_media`` applies the same narrowing so the media
path cannot be the one hole in it.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q, QuerySet
from django.http import Http404, HttpRequest

from . import digest_links, scoping
from .models import DigestIssue, MediaAsset, Member

# Mirrors elder_views. Duplicated deliberately rather than imported: elder_views imports
# scoping and would create a cycle through media_views, and these two keys are the
# session contract, not an implementation detail.
_ELDER_SESSION_MEMBER = "elder_member_id"
_ELDER_SESSION_GENERATION = "elder_generation"


@dataclass(frozen=True)
class Reader:
    """A resolved viewer: the member, plus whatever ceiling their credential carries.

    ``digest_issue`` is set only for a digest token, and it is the capability ceiling
    from ``digest_views``: that token reaches its own issue's slice and nothing else.
    """

    member: Member
    digest_issue: DigestIssue | None = None

    def visible_media(self) -> QuerySet[MediaAsset]:
        """The media this reader may fetch: the one audience query, narrowed by any
        ceiling the credential carries.

        Without the narrowing a digest token would widen into a general media credential
        for every yard and every week that member can see — strictly more than the page
        the token was minted to render, and the exact widening ``digest_post_view``
        documents as forbidden.
        """
        assets = scoping.visible_media(self.member)
        if self.digest_issue is not None:
            issue_posts = digest_links.issue_posts(self.digest_issue)
            # Both attachment shapes must be narrowed. Filtering on `post__in` alone
            # would let a digest token fetch the photos on any REPLY that member can
            # see, in any yard and any week — exactly the widening this narrowing
            # exists to prevent, reintroduced through the S-404 path.
            assets = assets.filter(Q(post__in=issue_posts) | Q(comment__post__in=issue_posts))
        return assets


def _reader_from_login(request: HttpRequest) -> Reader | None:
    if not request.user.is_authenticated or request.user.pk is None:
        return None
    member = Member.objects.filter(user_id=request.user.pk).first()
    return None if member is None else Reader(member)


def _reader_from_elder_session(request: HttpRequest) -> Reader | None:
    """The member behind a live elder session, with the ADR-003 generation re-check.

    The generation is re-read from the member NOW and compared with the snapshot taken
    at exchange, so one revocation act ends the session mid-flight — a stale cookie
    cannot outlive the token it came from.
    """
    member_id = request.session.get(_ELDER_SESSION_MEMBER)
    if not member_id:
        return None
    member = Member.objects.filter(pk=member_id).first()
    if member is None:
        return None
    if request.session.get(_ELDER_SESSION_GENERATION) != member.token_generation:
        return None
    return Reader(member)


def _reader_from_digest_token(raw_token: str | None) -> Reader | None:
    """The member a digest token was minted for, ceilinged to that token's own issue.

    ``digest_links.resolve`` performs the generation check and the expiry check; both
    failure shapes collapse to None here so the caller answers one byte-identical 404.
    """
    if not raw_token:
        return None
    try:
        token = digest_links.resolve(raw_token)
    except (digest_links.DigestLinkInvalid, digest_links.DigestLinkExpired):
        return None
    return Reader(token.member, digest_issue=token.issue)


def resolve_reader(request: HttpRequest, digest_token: str | None = None) -> Reader:
    """The Reader behind ANY read credential on this request, or the bare 404.

    Order is deliberate: a signed-in member wins, so a member who also happens to hold
    an elder session or a digest link is always themselves, at their own full reach,
    and never someone else at someone else's.
    """
    for candidate in (
        _reader_from_login(request),
        _reader_from_elder_session(request),
        _reader_from_digest_token(digest_token),
    ):
        if candidate is not None:
            return candidate
    raise Http404
