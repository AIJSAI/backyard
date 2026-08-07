"""Ad-hoc pods and quiet exits (S-204, S-205).

A member can carve out an ad-hoc pod inside a yard they belong to ("just us
cousins"), set a one-sentence house rule, and add existing members who share the
yard. An ad-hoc pod's posts stay in the pod: they never carry a yard audience, so
they never surface in the wider yard feed (S-204, enforced in posting.create_post).

Quiet exits (S-205): muting a pod silently hides it from the muter's own feed and
nobody else's, and leaves the pod reachable by direct link (it is a display choice,
not an authorization change). Leaving a pod deletes the membership with no broadcast,
because there is no notification path to broadcast on.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db import transaction

from . import scoping
from .models import Member, Pod, PodMembership, PodMute, Yard


class PodActionNotAllowed(PermissionDenied):
    """The member may not take this action on this pod."""


def create_adhoc_pod(*, owner: Member, yard: Yard, name: str, house_rule: str = "") -> Pod:
    """Create an ad-hoc pod in a yard the owner belongs to, with the owner as its
    first member. Raises if the owner is not in the yard."""
    if yard.id not in scoping.member_yard_ids(owner):
        raise PodActionNotAllowed("You can only create a pod in a yard you belong to.")
    with transaction.atomic():
        pod = Pod.objects.create(
            name=name.strip()[:100],
            kind=Pod.ADHOC,
            owner=owner,
            house_rule=house_rule.strip()[:200],
        )
        pod.yards.set([yard])
        PodMembership.objects.get_or_create(member=owner, pod=pod)
    return pod


def add_member_to_pod(*, actor: Member, pod: Pod, new_member: Member) -> None:
    """Owner-only: add an existing member who shares the pod's yard (S-204)."""
    if pod.kind != Pod.ADHOC:
        raise PodActionNotAllowed("Members join a household pod by invite, not here.")
    if pod.owner_id != actor.id:
        raise PodActionNotAllowed("Only the pod owner can add members.")
    pod_yard_ids = set(pod.yards.values_list("id", flat=True))
    if not (pod_yard_ids & scoping.member_yard_ids(new_member)):
        raise PodActionNotAllowed("You can only add someone who shares this pod's yard.")
    PodMembership.objects.get_or_create(member=new_member, pod=pod)


def set_house_rule(*, actor: Member, pod: Pod, house_rule: str) -> None:
    """Owner-only: set the one-sentence house rule shown at the top of the pod."""
    # Symmetry with add_member (security review INFO-1): a house rule is an ad-hoc-pod
    # concept. Household pods have no owner, so the owner check below already fails
    # closed, but guard the kind explicitly so a future household owner cannot inherit
    # this by accident.
    if pod.kind != Pod.ADHOC:
        raise PodActionNotAllowed("A household pod has no house rule.")
    if pod.owner_id != actor.id:
        raise PodActionNotAllowed("Only the pod owner can set the house rule.")
    pod.house_rule = house_rule.strip()[:200]
    pod.save(update_fields=["house_rule"])


def leave_pod(*, member: Member, pod: Pod) -> None:
    """Leave an ad-hoc pod silently (S-205): drop the membership and any mute, no
    broadcast. Restricted to ad-hoc pods (security review LOW-1): leaving a household
    pod would strip a member of their yards and lock them out with no self-service way
    back, so household membership only changes through admin removal (S-702)."""
    if pod.kind != Pod.ADHOC:
        raise PodActionNotAllowed(
            "You can leave an ad-hoc pod; a household is managed by an admin."
        )
    PodMembership.objects.filter(member=member, pod=pod).delete()
    PodMute.objects.filter(member=member, pod=pod).delete()
    # Reply capabilities for this pod's posts die with the membership (S-502:
    # revoked on ANY membership change); the write path's audience re-check is
    # the second lock, this keeps the row state honest.
    from . import reply_addresses

    reply_addresses.void_for_pod_leave(member, pod)

    # Ownership follows membership. Two states this closes, both measured:
    #
    #   A) owner LEFT: owner_id=1 still_member=False
    #      departed owner can STILL set the house rule: YES
    #   B) owner DELETED: owner_id=None members=1
    #      set_house_rule by remaining member: PodActionNotAllowed
    #      add_member    by remaining member: PodActionNotAllowed
    #
    # (A) is somebody keeping control of a group they walked out of. (B) is the group
    # frozen for good: `pod.owner_id != actor.id` is the only gate on both capabilities,
    # and `None` never equals anybody, so the house rule and the member list become
    # unreachable to every person alive. `Pod.owner` is set at creation and nowhere else,
    # so there was no path back.
    succeed_owner(pod)


def set_muted(*, member: Member, pod: Pod, muted: bool) -> None:
    """Mute or unmute a pod for this member only (S-205). Silent to everyone else."""
    if muted:
        PodMute.objects.get_or_create(member=member, pod=pod)
    else:
        PodMute.objects.filter(member=member, pod=pod).delete()


def muted_pod_ids(member: Member) -> set[int]:
    """The pods this member has muted, to drop from their feed."""
    return set(member.pod_mutes.values_list("pod_id", flat=True))


def succeed_owner(pod: Pod) -> Member | None:
    """Hand an ad-hoc pod to its longest-standing member if its owner is no longer one.

    Called wherever an owner can stop being a member: leaving (`leave_pod`), and deletion
    (`SET_NULL` on the FK, which the demo wipe reaches through a seeded member). One rule for
    both, because they produce the same broken state by different routes and a fix for only
    the route somebody happened to file is how the other one survives.

    Succession is by JOIN ORDER — the person who has been in the group longest. Not the
    creator (they are the one leaving) and not an admin (an ad-hoc pod is deliberately not an
    admin surface; `permissions.py` reads no role for any pod capability). If nobody is left,
    the pod is empty and ownerless is the honest state: there is no one to hand it to, and an
    empty pod has nothing to manage.

    Returns the new owner, or None if there was nothing to do.
    """
    if pod.kind != Pod.ADHOC:
        return None
    still_a_member = (
        pod.owner_id is not None
        and PodMembership.objects.filter(member_id=pod.owner_id, pod=pod).exists()
    )
    if still_a_member:
        return None
    successor = (
        Member.objects.filter(pod_memberships__pod=pod)
        .order_by("pod_memberships__created_at", "pod_memberships__id")
        .first()
    )
    if successor is None:
        # Empty pod. Record the absence rather than leaving a stale owner pointing at
        # somebody who is gone.
        if pod.owner_id is not None:
            pod.owner = None
            pod.save(update_fields=["owner"])
        return None
    pod.owner = successor
    pod.save(update_fields=["owner"])
    return successor
