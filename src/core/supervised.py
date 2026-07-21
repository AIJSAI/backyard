"""Supervised member creation (S-703).

A supervised member is a child's account managed entirely by a parent. It has no
independent login of its own to attach an email or auth method to (TM-10:
supervised accounts cannot attach an email or a new auth method and are excluded
from self-service recovery), it is visibly flagged, and it belongs to a pod. The
managing parent is recorded so the permission model can enforce that only the
parent (or the instance admin) administers the child.

Token links are never issued to supervised members; that rule lives in the token
provisioning surface (S-104), which is a later wave, and the permission model
already blocks anyone but the parent or instance admin from acting on the child.
"""

from __future__ import annotations

from django.db import transaction

from .models import Member, Pod, PodMembership


def create_supervised_member(*, parent: Member, display_name: str, pod: Pod) -> Member:
    """Create a supervised member managed by `parent`, placed in `pod`. Atomic.

    Authorization (can the caller create this?) is the view's job via
    core.permissions.can_create_supervised; this service just builds the record
    correctly: flagged, parent-managed, no User, SUPERVISED role.
    """
    with transaction.atomic():
        child = Member.objects.create(
            display_name=display_name,
            role=Member.SUPERVISED,
            is_supervised=True,
            managing_parent=parent,
            user=None,  # no independent login; the parent manages access
            # A child's dates stay inside the household by default (S-903,
            # T-MINOR-6); the ordinary-member YARD default is too wide here.
            birthday_visibility=Member.POD,
            anniversary_visibility=Member.POD,
        )
        PodMembership.objects.create(member=child, pod=pod)
        return child
