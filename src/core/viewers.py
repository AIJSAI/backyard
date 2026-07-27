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

**This widens authentication, never authorization.** Each resolver returns a Member and
nothing else; the caller still runs the one audience query (``scoping.visible_media``
over ``visible_posts``), so what any viewer may see is unchanged. The threat model
already reasoned about this reach: T-TOKEN-1 assesses a leaked elder link as exposing
"kids' media", which is only true if the elder can fetch media at all.

The digest resolver keeps the capability ceiling from ``digest_views``: a digest token
authenticates its own member but must not become a general read credential, so the
caller pairs it with the issue-slice check.
"""

from __future__ import annotations

from django.http import Http404, HttpRequest

from . import digest_links
from .models import Member

# Mirrors elder_views. Duplicated deliberately rather than imported: elder_views imports
# scoping and would create a cycle through media_views, and these two keys are the
# session contract, not an implementation detail.
_ELDER_SESSION_MEMBER = "elder_member_id"
_ELDER_SESSION_GENERATION = "elder_generation"


def _member_from_login(request: HttpRequest) -> Member | None:
    if not request.user.is_authenticated or request.user.pk is None:
        return None
    return Member.objects.filter(user_id=request.user.pk).first()


def _member_from_elder_session(request: HttpRequest) -> Member | None:
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
    return member


def _member_from_digest_token(raw_token: str | None) -> Member | None:
    """The member a digest token was minted for, or None for anything invalid.

    ``digest_links.resolve`` performs the generation check and the expiry check; both
    failure shapes collapse to None here so the caller answers one byte-identical 404.
    """
    if not raw_token:
        return None
    try:
        return digest_links.resolve(raw_token).member
    except (digest_links.DigestLinkInvalid, digest_links.DigestLinkExpired):
        return None


def resolve_reader(request: HttpRequest, digest_token: str | None = None) -> Member:
    """The Member behind ANY read credential on this request, or the bare 404.

    Order is deliberate: a signed-in member wins, so a member who also happens to hold
    an elder session or a digest link is always themselves and never someone else.
    """
    for candidate in (
        _member_from_login(request),
        _member_from_elder_session(request),
        _member_from_digest_token(digest_token),
    ):
        if candidate is not None:
            return candidate
    raise Http404
