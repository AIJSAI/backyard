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
    return Comment.objects.create(author=author, post=post, body=body, via_email=via_email)


def delete_comment(*, actor: Member, comment: Comment) -> None:
    """Soft-delete the actor's own comment. Author-only; idempotent."""
    if comment.author_id != actor.id:
        raise NotYourComment("You can only delete your own comment.")
    if comment.deleted_at is not None:
        return
    comment.deleted_at = timezone.now()
    comment.save(update_fields=["deleted_at"])
