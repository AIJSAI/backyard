"""The elder surface (S-102, S-601, S-602): one link, one big readable column.

/t/<token>/ exchanges the handed-over URL for an httpOnly session and redirects
to the clean /e/ feed (TM-5: the token never rides every request, never sits in
the address bar during use, never leaks through a referrer). The session
carries the member id plus a generation snapshot re-checked on EVERY request,
so revocation or regeneration kills a live elder session at its next click,
and the session key is cycled at exchange time against fixation.

The capability ceiling (TM-5, T-TOKEN-1) is structural: these views are the
ONLY ones that accept an elder session, and they render read, one-tap named
reactions, and nothing else. Every other surface requires a real login, which
an elder session is not, so profile edits, the directory, contact fields,
exports, and invites are unreachable by construction, not by checklist. The
elder templates extend their own base with no navigation off the surface: no
dead ends, one obvious way back to the feed (S-601).
"""

from __future__ import annotations

from django.db.models import Prefetch
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from . import elder_tokens, reacting, scoping
from .models import Member, Reaction

_SESSION_MEMBER = "elder_member_id"
_SESSION_GENERATION = "elder_generation"
_SESSION_BIG_TEXT = "elder_big_text"
_MAX_POSTS = 50


@require_GET
def enter(request: HttpRequest, token: str) -> HttpResponse:
    """Exchange the token URL for a session and land on the clean feed URL.
    Reopening the same link later works: the elder's bookmark IS the link."""
    try:
        elder_token = elder_tokens.resolve(token)
    except elder_tokens.ElderTokenInvalid as exc:
        raise Http404 from exc
    # flush(), not cycle_key() (#42 review HIGH): cycle_key rotates the key but
    # PRESERVES session data, so opening the link in a browser with a live login
    # would carry that _auth_user_id through and hand the elder surface a fully
    # authenticated session — the ceiling defeated on exactly the shared family
    # tablet this path targets. flush() starts a clean empty session (no carried
    # login, no stale elder state) and rotates the key, closing fixation too.
    request.session.flush()
    request.session[_SESSION_MEMBER] = elder_token.member_id
    request.session[_SESSION_GENERATION] = elder_token.member.token_generation
    return redirect("elder_feed")


def _elder_member(request: HttpRequest) -> Member:
    """The member behind a live elder session, or the bare 404. The generation
    snapshot is re-checked against the member NOW, so one revocation act ends
    a session mid-use; a stale session is flushed so the cookie dies too."""
    member_id = request.session.get(_SESSION_MEMBER)
    generation = request.session.get(_SESSION_GENERATION)
    if member_id is None:
        raise Http404
    member = Member.objects.filter(pk=member_id).first()
    if (
        member is None
        or member.token_generation != generation
        or not hasattr(member, "elder_token")
    ):
        request.session.flush()
        raise Http404
    return member


@require_GET
def elder_feed(request: HttpRequest) -> HttpResponse:
    """The one big readable column (S-601): the member's visible posts, large
    type, giant targets, one-tap named reactions, nowhere to get lost."""
    member = _elder_member(request)
    posts = list(
        scoping.visible_posts(member)
        .select_related("author", "pod")
        .prefetch_related(
            Prefetch("reactions", queryset=Reaction.objects.select_related("member"))
        )[:_MAX_POSTS]
    )
    my_reactions = {
        reaction.post_id
        for post in posts
        for reaction in post.reactions.all()
        if reaction.member_id == member.id
    }
    return render(
        request,
        "core/elder_feed.html",
        {
            "member": member,
            "posts": posts,
            "my_reactions": my_reactions,
            "big_text": bool(request.session.get(_SESSION_BIG_TEXT)),
        },
    )


@require_POST
def elder_react(request: HttpRequest, post_id: int) -> HttpResponse:
    """One tap, attributed by name (S-602). The guard resolves the post; the
    reaction rides the same service as the web surface, so it counts in the
    reciprocity metrics like any other."""
    member = _elder_member(request)
    post = scoping.require_visible_post(member, post_id)
    reacting.toggle_reaction(member=member, post=post, kind=Reaction.HEART)
    return redirect("elder_feed")


@require_POST
def elder_text_size(request: HttpRequest) -> HttpResponse:
    """The bigger-text toggle (S-601). A session flag, nothing stored."""
    _elder_member(request)
    request.session[_SESSION_BIG_TEXT] = not request.session.get(_SESSION_BIG_TEXT)
    return redirect("elder_feed")
