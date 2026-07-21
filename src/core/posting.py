"""Composing a post (S-302, S-203): the write path, with audience integrity.

This is the service the composer view calls. It owns the invariant the read query
cannot (flagged in the Post model docstring, PR #21 review MEDIUM #4): a post's
pod must be one the author belongs to, and every audience yard must be one the
author belongs to. Without this an author could publish into a yard they are not
in. The read query (scoping.visible_posts) faithfully honors audience_yards, so
the check must live here, on the write.

TM-3 (the audience picker never widens silently) is split: this service enforces
the integrity and the narrowest sensible default; the composer view enforces the
confirm-on-widen step, because "did the human confirm" is request state, not a
service concern.

Edit and delete (S-302) live here too: a member may edit their own post for a
brief window and delete it at any time. Both are author-only; the view resolves
the post through the guard first, so "not visible" is a 404 and "visible but not
yours" is the 403 these raise. Delete is a soft delete (deleted_at), which the
one audience query already treats as gone for the feed and, later, the digest.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from . import scoping
from .models import Member, Pod, Post, Yard

# How long after posting a member may still edit the text. Long enough to fix a
# typo, short enough that the archive stays honest (S-302: "at least 15 minutes").
EDIT_WINDOW = timedelta(minutes=15)


class AudienceNotAllowed(PermissionDenied):
    """The requested audience is outside the author's own pods and yards."""


class NotYourPost(PermissionDenied):
    """Only the author may edit or delete their own post."""


class EditWindowClosed(PermissionDenied):
    """The brief window for editing this post has passed."""


def create_post(*, author: Member, pod: Pod, audience_yards: list[Yard], body: str) -> Post:
    """Create a post after checking the author may address this audience. Atomic.

    pod must be one of the author's pods; every audience yard must be one of the
    author's yards. A pod-only post passes an empty audience_yards list.
    """
    author_pods = scoping.member_pod_ids(author)
    author_yards = scoping.member_yard_ids(author)
    if pod.id not in author_pods:
        raise AudienceNotAllowed("You can only post to a pod you belong to.")
    for yard in audience_yards:
        if yard.id not in author_yards:
            raise AudienceNotAllowed("You can only post to a yard you belong to.")

    with transaction.atomic():
        post = Post.objects.create(author=author, pod=pod, body=body)
        if audience_yards:
            post.audience_yards.set(audience_yards)
        return post


def within_edit_window(post: Post) -> bool:
    """Whether the post is still inside its edit window (used by the view and the
    feed template to offer the edit affordance only while it will succeed)."""
    return timezone.now() - post.created_at <= EDIT_WINDOW


def edit_post(*, actor: Member, post: Post, body: str) -> Post:
    """Edit the text of the actor's own post, if still within the edit window.

    Author-only (NotYourPost) and time-boxed (EditWindowClosed). The audience and
    pod are not editable here; a member who wants a different audience deletes and
    reposts, so an already-delivered post cannot silently change who it reached.
    """
    if post.author_id != actor.id:
        raise NotYourPost("You can only edit your own post.")
    if post.deleted_at is not None:
        # Defense in depth (security review LOW-2): the view already 404s a deleted
        # post through the guard before reaching here, but the service refuses
        # independently so a future non-guard caller cannot edit a tombstoned post
        # back into the feed. Mirrors delete_post's own deleted-state guard.
        raise PermissionDenied("This post has been deleted and can no longer be edited.")
    if not within_edit_window(post):
        raise EditWindowClosed("The window for editing this post has passed.")
    post.body = body
    post.edited_at = timezone.now()
    post.save(update_fields=["body", "edited_at"])
    return post


def delete_post(*, actor: Member, post: Post) -> None:
    """Soft-delete the actor's own post. Author-only; idempotent.

    Deletion is always available (S-302). It sets deleted_at, which the single
    audience query treats as gone everywhere the feed and digest read, so the post
    stops reaching anyone through the same path that resolved it. Copies already
    carried out in sent email digests cannot be recalled; the delete confirmation
    says so in plain words.
    """
    if post.author_id != actor.id:
        raise NotYourPost("You can only delete your own post.")
    if post.deleted_at is not None:
        return
    post.deleted_at = timezone.now()
    post.save(update_fields=["deleted_at"])
