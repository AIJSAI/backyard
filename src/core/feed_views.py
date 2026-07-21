"""The feed and the composer (S-000, S-302, S-303, S-203).

The feed is the calm chronological surface: a member's visible posts, newest
first, that ends with a you-are-caught-up state (no infinite scroll, no counts).
The composer writes a post through the audience-integrity service (core/posting),
and enforces TM-3 here: the default audience is the poster's own pod (the
narrowest), and any send broader than the pod, or spanning more than one yard,
requires an explicit confirmation that names the audience and its member count.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from . import posting, scoping
from .models import Member

# A family text post, not an essay. Bounds the stored size of a single post so a
# crafted request cannot park megabytes of text behind the composer (the wider
# ceiling is Django's DATA_UPLOAD_MAX_MEMORY_SIZE; this is the friendly limit).
_MAX_BODY = 5000


def _acting_member(request: HttpRequest) -> Member:
    if not request.user.is_authenticated or request.user.pk is None:
        raise Http404
    member = Member.objects.filter(user_id=request.user.pk).first()
    if member is None:
        raise Http404
    return member


@login_required
def feed(request: HttpRequest) -> HttpResponse:
    """The chronological feed that ends, plus the composer form."""
    member = _acting_member(request)
    posts = scoping.visible_posts(member).select_related("author", "pod")[:100]
    return render(
        request,
        "core/feed.html",
        {
            "member": member,
            "posts": posts,
            "pods": scoping.visible_pods(member),
            "yards": scoping.visible_yards(member),
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
        posting.create_post(author=member, pod=pod, audience_yards=audience_yards, body=body)
        return redirect("feed")

    # Re-render the feed with the error (rare; the composer requires a body client-side).
    posts = scoping.visible_posts(member).select_related("author", "pod")[:100]
    return render(
        request,
        "core/feed.html",
        {
            "member": member,
            "posts": posts,
            "pods": scoping.visible_pods(member),
            "yards": scoping.visible_yards(member),
            "errors": errors,
        },
    )


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
