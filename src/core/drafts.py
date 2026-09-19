"""An unfinished post, held across the confirmation hop (F5).

``staged_uploads`` already solved this for the PHOTOS: a wide post's files are written
server-side and the member carries a handle, because a browser form cannot round-trip a
file. Their WORDS had no such protection. Anything that left the TM-3 confirmation page
without answering it — the back button, the header nav, a phone call, a tab closing —
threw the whole post away, and the confirmation is exactly the screen a person pauses on,
because it is the one asking them to think about who will read it.

So the draft is held here for as long as its photographs are: same TTL, same session, so
the words and the pictures can never fall out of step. It is released on exactly two
events, and no others.

  * the post is CREATED — the draft has become the thing it was a draft of;
  * the member CANCELS — on the confirmation page, or from the composer's own
    "Discard Draft".

Nothing else drops it, and in particular merely rendering the feed does not: a draft that
evaporated because its owner went to look at the directory would be the same defect one
step further along.

Scope: the body, the chosen pod and the staged-upload handle. Never the audience yards —
re-ticking "the whole Whitfield side" is the one decision in the composer that must be
made deliberately every time, and a draft that silently restored it would widen a post
its author had walked away from.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.http import HttpRequest
from django.utils import timezone

from .staged_uploads import STAGING_TTL

_SESSION_KEY = "pending_draft"

# What one draft may occupy in the session. The composer's own ceiling (feed_views._MAX_BODY),
# stated by value rather than imported, to keep this module free of a view import.
MAX_DRAFT_BODY = 5000


@dataclass(frozen=True)
class PendingDraft:
    """What the composer needs to reopen on the words somebody left behind."""

    body: str
    pod_id: int | None
    handle: str | None


def hold(request: HttpRequest, *, body: str, pod_id: int | None, handle: str | None) -> None:
    """Remember an unfinished post. Overwrites any earlier one: a member composes one
    post at a time, and the newest attempt is the one they meant.

    The body is clamped before it is written. The branch that holds a draft most often is
    the ERROR branch, and "Post must be 5000 characters or fewer" is one of those errors —
    so the one input guaranteed to be over the cap was the one being copied verbatim into
    a database-backed session row and re-rendered on every feed request for the whole TTL.
    staged_uploads bounds its bytes; this is the same posture for the words.
    """
    request.session[_SESSION_KEY] = {
        "body": body[:MAX_DRAFT_BODY],
        "pod_id": pod_id,
        "handle": handle,
        "held_at": timezone.now().isoformat(),
    }


def peek(request: HttpRequest) -> PendingDraft | None:
    """The held draft, or None. Past the TTL it is dropped rather than returned.

    The TTL is the staging TTL, deliberately: past it the sweep has already collected
    the photographs, so restoring the words alone would reopen the composer on a post
    whose pictures are gone while saying nothing about it.
    """
    entry = request.session.get(_SESSION_KEY)
    if not isinstance(entry, dict):
        return None
    held_at = entry.get("held_at")
    if not isinstance(held_at, str):
        return None
    try:
        moment = datetime.datetime.fromisoformat(held_at)
    except ValueError:
        return None
    if moment < timezone.now() - STAGING_TTL:
        clear(request)
        return None
    body = entry.get("body")
    pod_id = entry.get("pod_id")
    handle = entry.get("handle")
    if not isinstance(body, str):
        return None
    return PendingDraft(
        body=body,
        pod_id=pod_id if isinstance(pod_id, int) else None,
        handle=handle if isinstance(handle, str) else None,
    )


def clear(request: HttpRequest) -> None:
    """Release the held draft. Idempotent."""
    if _SESSION_KEY in request.session:
        del request.session[_SESSION_KEY]
