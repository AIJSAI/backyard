"""The /d/ read surface: what a digest deep link opens (S-501, TM-2, TM-5).

The token authenticates (member, issue); everything rendered resolves through
the one audience query at request time via digest_links.issue_posts and
scoping.require_visible_post, so this surface holds no authorization logic of
its own. It is read-only by construction: GET-only routes, no forms, no session
minted, and the capability ceiling is the issue's own slice (a valid token
never reaches another yard's content, the directory, or any contact field).

Every response under /d/ carries the token-link hygiene headers (TM-5) via
core.middleware.TokenSurfaceHeadersMiddleware, guard 404s and 405s included.
Expired-but-genuine links get a friendly capability-free page; unknown and
revoked tokens are the guard's byte-identical 404 (T-TOKEN-2).
"""

from __future__ import annotations

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from . import digest_links, scoping
from .models import DigestToken

# A digest page truncating an absurd week beats an unbounded render on an
# unauthenticated surface (#36 LOW-3); the feed uses the same posture.
_MAX_POSTS = 500
_MAX_COMMENTS = 500


def _resolve_or_respond(request: HttpRequest, raw_token: str) -> DigestToken | HttpResponse:
    """The token, or the correct failure response. Http404 propagates for the
    invalid/revoked shape so it is byte-identical with every other guard 404."""
    try:
        return digest_links.resolve(raw_token)
    except digest_links.DigestLinkInvalid as exc:
        raise Http404 from exc
    except digest_links.DigestLinkExpired:
        # Friendly and capability-free (T-TOKEN-2): no content, no names, just
        # the ask-your-family message. 410: honest "this link is done", and a
        # mail client prefetcher can never mistake it for live content.
        return render(request, "core/digest_link_expired.html", status=410)


@require_GET
def digest_view(request: HttpRequest, token: str) -> HttpResponse:
    """One digest issue as a web page: that yard's slice of that member's feed
    over the issue window, resolved live (deleted and narrowed content is simply
    absent from a still-valid link)."""
    resolved = _resolve_or_respond(request, token)
    if isinstance(resolved, HttpResponse):
        return resolved
    posts = (
        digest_links.issue_posts(resolved.issue)
        .select_related("author", "pod")
        .order_by("-created_at")[:_MAX_POSTS]
    )
    return render(
        request,
        "core/digest_web.html",
        {"issue": resolved.issue, "posts": posts, "token": token},
    )


@require_GET
def digest_post_view(request: HttpRequest, token: str, post_id: int) -> HttpResponse:
    """One post from a digest deep link, with its replies.

    Double-gated: the post must be visible to the member NOW (require_visible_post,
    the one guard) AND inside this issue's slice (the capability ceiling: a digest
    token never widens into a general read credential for the member's other
    yards). Outside either gate it is the same byte-identical 404.
    """
    resolved = _resolve_or_respond(request, token)
    if isinstance(resolved, HttpResponse):
        return resolved
    post = scoping.require_visible_post(resolved.member, post_id)
    if not digest_links.issue_posts(resolved.issue).filter(pk=post.pk).exists():
        raise Http404
    comments = (
        scoping.visible_comments(resolved.member)
        .filter(post=post)
        .select_related("author")
        .order_by("created_at")[:_MAX_COMMENTS]
    )
    return render(
        request,
        "core/digest_post.html",
        {"issue": resolved.issue, "post": post, "comments": comments, "token": token},
    )
