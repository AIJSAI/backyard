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
    if pod.owner_id != actor.id:
        raise PodActionNotAllowed("Only the pod owner can set the house rule.")
    pod.house_rule = house_rule.strip()[:200]
    pod.save(update_fields=["house_rule"])


def leave_pod(*, member: Member, pod: Pod) -> None:
    """Leave a pod silently (S-205): drop the membership and any mute, no broadcast."""
    PodMembership.objects.filter(member=member, pod=pod).delete()
    PodMute.objects.filter(member=member, pod=pod).delete()


def set_muted(*, member: Member, pod: Pod, muted: bool) -> None:
    """Mute or unmute a pod for this member only (S-205). Silent to everyone else."""
    if muted:
        PodMute.objects.get_or_create(member=member, pod=pod)
    else:
        PodMute.objects.filter(member=member, pod=pod).delete()


def muted_pod_ids(member: Member) -> set[int]:
    """The pods this member has muted, to drop from their feed."""
    return set(member.pod_mutes.values_list("pod_id", flat=True))
