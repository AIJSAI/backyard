"""Commenting on a post (wave 2), the substrate for wave 4's email replies (S-502).

A comment has no audience of its own: anyone who can see the post may comment, and
the comment is visible to exactly the post's audience through the one query
(scoping.visible_comments over scoping.visible_posts). This service owns the
write-side integrity the read query cannot: a member may only comment on a post
they can actually see, so a crafted request cannot attach a comment to a post in a
yard they are not in. It is the comment analog of the post audience-integrity
invariant. Delete is author-only and soft, mirroring the post lifecycle.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from . import scoping
from .models import Comment, Member, Post


class CommentNotAllowed(PermissionDenied):
    """The author cannot comment on a post they cannot see."""


class NotYourComment(PermissionDenied):
    """Only the author may delete their own comment."""


def create_comment(*, author: Member, post: Post, body: str, via_email: bool = False) -> Comment:
    """Create a comment after confirming the author may see the post.

    The view resolves the post through the guard first; this re-checks
    independently so a non-guard caller cannot attach a comment to a post outside
    the author's audience (defense in depth).
    """
    if not scoping.visible_posts(author).filter(id=post.id).exists():
        raise CommentNotAllowed("You can only comment on a post you can see.")
    comment = Comment.objects.create(author=author, post=post, body=body, via_email=via_email)
    # Fired here rather than at the two call sites (the web composer and the inbound-email
    # path), so the one opt-in cannot be honoured on one route and forgotten on the other,
    # and a future third route gets it for free.
    #
    # Deferred to the WORKER, on commit, and never run inline. ATOMIC_REQUESTS wraps the
    # view, so an inline send held the member's write transaction open across a whole SMTP
    # conversation: EMAIL_TIMEOUT bounds each socket operation but not the sum, so a
    # degraded mail server outruns gunicorn's timeout, the worker is killed mid-view, the
    # transaction rolls back and the member LOSES THE REPLY THEY WROTE. on_commit also
    # fixes the ordering — mail for a comment that never committed — and keeps the
    # edge-facing web process free of outbound connections, the same rule that put the
    # link-preview fetch on the worker (S-725, TS-CO-4).
    from .tasks import notify_reply_task

    transaction.on_commit(lambda: notify_reply_task.defer(comment_id=comment.pk))
    return comment


def delete_comment(*, actor: Member, comment: Comment) -> None:
    """Soft-delete the actor's own comment and hard-purge its media. Author-only;
    idempotent.

    The purge lives HERE rather than in the view, unlike the post path, and
    deliberately: `removal._delete_content` reaches comments through a bulk queryset
    and never touches a view, so a view-level purge would leave a removed member's
    reply photographs on the volume while telling them their content was gone
    (T-MEDIA-6, S-702). In the service it cannot be forgotten by a new caller.
    """
    if comment.author_id != actor.id:
        raise NotYourComment("You can only delete your own comment.")
    if comment.deleted_at is not None:
        return
    from . import media

    media.purge_comment_media(comment)
    comment.deleted_at = timezone.now()
    comment.save(update_fields=["deleted_at"])
