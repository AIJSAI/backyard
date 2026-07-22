"""Single-item moderation takedown (S-713).

A yard admin or instance admin can take down one post or one comment. This is the
content-level lever, distinct from the nuclear person-level ``removal.remove_member``:
the person-level lever stays remove-only in v1 (reversible member-suspend is deferred).

The takedown is scoped to what the moderator can SEE. The view resolves the item through
the read guard (scoping.require_visible_post / require_visible_comment) for the MODERATOR,
so a post in a pod the moderator does not belong to is a byte-identical 404 — a yard admin
can never take down a pod-private post the guard would not return them (the reach-vs-
visibility rule; routing those to the parent or pod is deferred post-v1). Authorization
(is_admin + visibility) is the view's job; this service records the action correctly.

Mechanism: it sets ``deleted_at`` — the same soft delete the author path uses, which the
one audience query (scoping.visible_posts) already treats as gone everywhere the feed and
digest read — and records ``moderated_by`` so a takedown is distinguishable from an author
self-delete and a future restore/audit has what it needs. It is silent: no member-visible
moderation notice exists in v1 (ratified). Idempotent.
"""

from __future__ import annotations

from django.utils import timezone

from .models import Comment, Member, Post


def take_down_post(*, moderator: Member, post: Post) -> None:
    """Take down a post on a moderator's authority. Idempotent: an already-removed post
    (author-deleted or already taken down) is left as it is, so a takedown never revives a
    tombstone's timestamp or overwrites the record of who first removed it."""
    if post.deleted_at is not None:
        return
    post.deleted_at = timezone.now()
    post.moderated_by = moderator
    post.save(update_fields=["deleted_at", "moderated_by"])


def take_down_comment(*, moderator: Member, comment: Comment) -> None:
    """Take down a comment on a moderator's authority. Idempotent, like take_down_post."""
    if comment.deleted_at is not None:
        return
    comment.deleted_at = timezone.now()
    comment.moderated_by = moderator
    comment.save(update_fields=["deleted_at", "moderated_by"])
