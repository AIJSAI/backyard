"""The feed and the composer (S-000, S-302, S-303, S-203).

The feed is the calm chronological surface: a member's visible posts, newest
first, that ends with a you-are-caught-up state (no infinite scroll, no counts).
The composer writes a post through the audience-integrity service (core/posting),
and enforces TM-3 here: the default audience is the poster's own pod (the
narrowest), and any send broader than the pod, or spanning more than one yard,
requires an explicit confirmation that names the audience and its member count.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from . import commenting, link_preview, posting, scoping
from .models import Member, Post

# A family text post, not an essay. Bounds the stored size of a single post so a
# crafted request cannot park megabytes of text behind the composer (the wider
# ceiling is Django's DATA_UPLOAD_MAX_MEMORY_SIZE; this is the friendly limit).
_MAX_BODY = 5000
# A reply is shorter still.
_MAX_COMMENT = 2000
# Cap the rendered thread so a pathological number of replies cannot inflate every
# co-viewer's page (security review LOW-1). A real family thread never approaches
# this; if one ever did, the newest replies within the cap still render.
_MAX_THREAD = 500


@dataclass
class FeedItem:
    """A post as the feed shows it to one viewer: the post plus the viewer-relative
    facts the template needs. Kept as a typed value rather than attributes stapled
    onto the model instance, so the view stays type-checked."""

    post: Post
    is_own: bool
    is_editable: bool
    is_new: bool


def _acting_member(request: HttpRequest) -> Member:
    if not request.user.is_authenticated or request.user.pk is None:
        raise Http404
    member = Member.objects.filter(user_id=request.user.pk).first()
    if member is None:
        raise Http404
    return member


@login_required
def feed(request: HttpRequest) -> HttpResponse:
    """The chronological feed that ends, plus the composer form. Opening the feed
    advances the member's unread boundary (S-303)."""
    member = _acting_member(request)
    return _render_feed(request, member, advance_seen=True)


def _render_feed(
    request: HttpRequest,
    member: Member,
    *,
    advance_seen: bool,
    errors: list[str] | None = None,
) -> HttpResponse:
    """Render the feed: the member's visible posts newest-first, each marked as their
    own (and still editable) and as new-since-last-visit, with one unread boundary
    before the first already-seen post. On a real feed open (advance_seen) the
    member's last-seen marker moves to now; a re-render after a composer error does
    not advance it, so an error never silently marks the feed as read."""
    boundary = member.feed_last_seen_at
    if advance_seen:
        Member.objects.filter(pk=member.pk).update(feed_last_seen_at=timezone.now())

    items = [
        FeedItem(
            post=post,
            is_own=post.author_id == member.id,
            is_editable=post.author_id == member.id and posting.within_edit_window(post),
            is_new=boundary is not None and post.created_at > boundary,
        )
        for post in scoping.visible_posts(member).select_related("author", "pod", "link_preview")[
            :100
        ]
    ]
    first_seen_id: int | None = None
    if any(item.is_new for item in items):
        first_seen_id = next((item.post.id for item in items if not item.is_new), None)

    return render(
        request,
        "core/feed.html",
        {
            "member": member,
            "items": items,
            "pods": scoping.visible_pods(member),
            "yards": scoping.visible_yards(member),
            "first_seen_id": first_seen_id,
            "errors": errors or [],
        },
    )


@login_required
def compose(request: HttpRequest) -> HttpResponse:
    """Create a post. POST only. Enforces TM-3 confirm-on-widen and, through the
    posting service, the audience-integrity invariant."""
    member = _acting_member(request)
    if request.method != "POST":
        raise Http404

    body = request.POST.get("body", "").strip()
    # The composer defaults to the poster's own pod; the pod must be theirs.
    pod = scoping.require_visible_pod(member, _int(request.POST.get("pod_id", "")))
    # The optional audience field is parsed leniently: a stray non-integer value is
    # skipped rather than failing the whole post, and a well-formed but foreign yard
    # id is dropped by the visible_yards filter below, so neither can widen the reach.
    yard_ids = _int_ids(request.POST.getlist("audience_yards"))
    audience_yards = list(scoping.visible_yards(member).filter(id__in=yard_ids)) if yard_ids else []

    errors: list[str] = []
    if not body:
        errors.append("Write something to post.")
    elif len(body) > _MAX_BODY:
        errors.append(f"That post is a little long. Keep it under {_MAX_BODY} characters.")

    # TM-3: any audience broader than the poster's own pod (a yard send, or more
    # than one yard) must be explicitly confirmed with its name and member count.
    widening = bool(audience_yards)
    confirmed = request.POST.get("confirm_wide") == "yes"
    if widening and not confirmed and not errors:
        reach = scoping.visible_members(member).filter(pods__yards__in=audience_yards).distinct()
        return render(
            request,
            "core/compose_confirm.html",
            {
                "body": body,
                "pod": pod,
                "audience_yards": audience_yards,
                "audience_names": ", ".join(y.name for y in audience_yards),
                "member_count": reach.count(),
            },
        )

    if not errors:
        post = posting.create_post(author=member, pod=pod, audience_yards=audience_yards, body=body)
        # Best-effort preview for a link in the body. Synchronous for now (bounded by
        # the fetcher's per-hop timeout); it moves to the worker in wave 3, where the
        # SSRF-sensitive fetch belongs on its own network segment (TS-CO-4).
        link_preview.attach_to_post(post)
        return redirect("feed")

    # Re-render the feed with the error (rare; the composer requires a body client-side).
    return _render_feed(request, member, advance_seen=False, errors=errors)


@login_required
def edit_post(request: HttpRequest, post_id: int) -> HttpResponse:
    """Edit one's own post within the edit window (S-302). The post is resolved
    through the guard, so a post the member cannot see is a byte-identical 404; a
    post they can see but did not write is a 403."""
    member = _acting_member(request)
    post = scoping.require_visible_post(member, post_id)
    if post.author_id != member.id:
        raise PermissionDenied

    if request.method == "POST":
        body = request.POST.get("body", "").strip()
        errors: list[str] = []
        if not body:
            errors.append("Write something to post.")
        elif len(body) > _MAX_BODY:
            errors.append(f"That post is a little long. Keep it under {_MAX_BODY} characters.")
        if not errors:
            posting.edit_post(actor=member, post=post, body=body)
            return redirect("feed")
        return render(request, "core/edit_post.html", {"post": post, "errors": errors})

    if not posting.within_edit_window(post):
        raise PermissionDenied  # the feed hides the edit link by now; enforce it here too
    return render(request, "core/edit_post.html", {"post": post, "errors": []})


@login_required
def delete_post(request: HttpRequest, post_id: int) -> HttpResponse:
    """Delete one's own post (S-302). GET confirms, stating plainly that copies
    already sent in email digests cannot be recalled; POST performs the soft delete.
    Same guard rules as edit: 404 if not visible, 403 if visible but not yours."""
    member = _acting_member(request)
    post = scoping.require_visible_post(member, post_id)
    if post.author_id != member.id:
        raise PermissionDenied

    if request.method == "POST":
        posting.delete_post(actor=member, post=post)
        return redirect("feed")
    return render(request, "core/delete_confirm.html", {"post": post})


def _int(value: str) -> int:
    """Parse a required, single, trusted id (the pod). A missing or malformed value
    is a byte-identical 404, never a distinguishable 500 (S-202 parity)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        raise Http404 from None


def _int_ids(values: list[str]) -> list[int]:
    """Parse the optional multi-value audience field, skipping any value that is not
    an integer. Unlike a required id, one stray checkbox value should be ignored, not
    fatal; a foreign but well-formed id is still dropped later by the visible_yards
    filter, so this never widens the audience past the author's own yards."""
    out: list[int] = []
    for value in values:
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            continue
    return out


@login_required
def post_detail(request: HttpRequest, post_id: int) -> HttpResponse:
    """A post and its replies (S-202: the post resolves through the guard, so a post
    the member cannot see is a byte-identical 404). Comments are scoped by the same
    query, so only replies on a visible post render."""
    member = _acting_member(request)
    post = scoping.require_visible_post(member, post_id)
    return _render_post_detail(request, member, post)


def _render_post_detail(
    request: HttpRequest, member: Member, post: Post, errors: list[str] | None = None
) -> HttpResponse:
    comments = (
        scoping.visible_comments(member).filter(post=post).select_related("author")[:_MAX_THREAD]
    )
    return render(
        request,
        "core/post_detail.html",
        {"member": member, "post": post, "comments": comments, "errors": errors or []},
    )


@login_required
def add_comment(request: HttpRequest, post_id: int) -> HttpResponse:
    """Reply to a post the member can see (S-502 substrate). POST only. The post is
    resolved through the guard first, so a reply to a post outside the member's
    audience is a 404, and the service re-checks visibility as defense in depth."""
    member = _acting_member(request)
    post = scoping.require_visible_post(member, post_id)
    if request.method != "POST":
        raise Http404

    body = request.POST.get("body", "").strip()
    errors: list[str] = []
    if not body:
        errors.append("Write a reply.")
    elif len(body) > _MAX_COMMENT:
        errors.append(f"That reply is a little long. Keep it under {_MAX_COMMENT} characters.")
    if errors:
        return _render_post_detail(request, member, post, errors)

    commenting.create_comment(author=member, post=post, body=body)
    return redirect("post_detail", post_id=post.id)


@login_required
def delete_comment(request: HttpRequest, comment_id: int) -> HttpResponse:
    """Delete one's own comment (author-only, soft). POST only. Resolved through the
    guard, so a comment the member cannot see is a 404 and one they can see but did
    not write is a 403."""
    member = _acting_member(request)
    if request.method != "POST":
        raise Http404  # POST-only; a GET never reaches the guard, so GET is a uniform 404
    comment = scoping.require_visible_comment(member, comment_id)
    if comment.author_id != member.id:
        raise PermissionDenied
    post_id = comment.post_id
    commenting.delete_comment(actor=member, comment=comment)
    return redirect("post_detail", post_id=post_id)
