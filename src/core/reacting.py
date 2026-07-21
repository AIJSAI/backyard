"""Reacting to a post (S-304): who reacted, never a count.

A member holds at most one reaction per post. Reacting with the same kind again
toggles it off; a different kind replaces it. Like a comment, a reaction is only
allowed on a post the member can see, and this service re-checks that visibility so
a crafted request cannot react to a post outside the member's audience. There is no
tally anywhere: the model stores who reacted with what, and the UI lists names.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied

from . import scoping
from .models import Member, Post, Reaction

VALID_KINDS = frozenset(kind for kind, _label in Reaction.KIND_CHOICES)


class ReactionNotAllowed(PermissionDenied):
    """The member cannot react to a post they cannot see, or used an unknown kind."""


def toggle_reaction(*, member: Member, post: Post, kind: str) -> Reaction | None:
    """Set, change, or clear the member's reaction to a post. Returns the reaction,
    or None when the call cleared it (same kind toggled off)."""
    if kind not in VALID_KINDS:
        raise ReactionNotAllowed(f"unknown reaction {kind!r}")
    if not scoping.visible_posts(member).filter(id=post.id).exists():
        raise ReactionNotAllowed("You can only react to a post you can see.")
    existing = Reaction.objects.filter(member=member, post=post).first()
    if existing is not None and existing.kind == kind:
        existing.delete()
        return None
    reaction, _created = Reaction.objects.update_or_create(
        member=member, post=post, defaults={"kind": kind}
    )
    return reaction
