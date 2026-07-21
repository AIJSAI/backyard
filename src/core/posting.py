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
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db import transaction

from . import scoping
from .models import Member, Pod, Post, Yard


class AudienceNotAllowed(PermissionDenied):
    """The requested audience is outside the author's own pods and yards."""


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
