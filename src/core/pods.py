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


class PodLeaveRefused(Exception):
    """The leave is allowed in principle but would strand the member.

    Not `PodActionNotAllowed`, and the distinction is the same one `households`
    draws between `HouseholdChangeRefused` and `PermissionDenied`: an authorization
    failure has nothing to say to the person, while this is answerable ("ask an admin
    to put you in a household first"), so it renders as a sentence on the page they
    are already looking at rather than as a 403.
    """


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
    back, so household membership only changes through admin removal (S-702).

    WHAT A LEAVE CAN SHRINK, read off the code rather than assumed (S9, issue 174):

    * it can never remove a HOUSEHOLD, because of the refusal above, so it can never be
      somebody's last household by that route;
    * it CAN drop a whole side of the family. `scoping.member_yard_ids` is the union of
      the sides of ALL a member's pods, ad-hoc ones included, and
      `households.sides_lost` counts an ad-hoc pod as keeping them on a side. So a member
      in a household on one side and an ad-hoc group on the other — the shape an admin
      creates by taking them out of a household they also had an ad-hoc group in — loses
      that whole side by pressing Leave;
    * it can strand somebody who holds NO household at all, who then resolves nobody
      through the guard, including themselves.

    That makes a leave a membership SHRINK exactly like `households.remove_from_household`,
    so it runs the same act in the same order, and the ordering is the H-1 contract: the
    member row is locked FIRST (the same row `revocation._run_steps` locks, so a leave and
    an admin's household change serialise against each other rather than interleaving),
    the shrink registry runs while the membership still EXISTS (its invite step resolves
    its scope from live memberships, so revoking after the delete would silently miss every
    invite reaching the side just left — the T-AUTH-G3 re-entry route), and only then does
    the row go.

    The registry is the SHRINK one, never the removal one: the member is still here, so
    their digest subscription survives and the invites that die are the ones reaching the
    sides being lost plus the ones they minted. `revoke_for_membership_shrink` carries
    both narrowings and the reasons.

    STILL NOT BUILT, named rather than implied: a pod leaving a yard, and the deceased
    flow (S-706). Neither has any implementation anywhere in this repo.
    """
    if pod.kind != Pod.ADHOC:
        raise PodActionNotAllowed(
            "You can leave an ad-hoc pod; a household is managed by an admin."
        )
    # Imported here rather than at module scope: `households` imports `permissions`, which
    # is a heavier graph than this module needs at import time, and `reply_addresses` below
    # already established the local-import idiom in this function.
    from . import households, reply_addresses, revocation

    with transaction.atomic():
        # The lock first, and it is the MEMBER row, not the membership: it is the row every
        # other membership change for this person takes, so the last-household count below
        # is a read with something behind it. Without it, two concurrent acts (this leave
        # and an admin removing them from their last household) each see the other's row
        # still present under READ COMMITTED and both land.
        Member.objects.select_for_update().get(pk=member.pk)
        if households.is_their_last_household(member, pod):
            # The sentence has to be true for the person reading it. The first version
            # said "it is the only one you are in", which is false for somebody in two
            # groups and no household — they can see one of them on the same page while
            # being told it is their only one. What is actually missing is a HOUSEHOLD,
            # which is also the only thing that answers it, so the sentence says that.
            # `help_contact_name` is the footer's helper: it reads the admin's first name
            # out of the database at render time, never out of this repository, which is
            # public. Empty falls back to the impersonal form the footer also uses.
            from .context_processors import help_contact_name

            who = help_contact_name() or "whoever looks after your family's Backyard"
            raise PodLeaveRefused(
                "You are not in a household yet, and this group is the only thing "
                "connecting you to your family. Leaving it would mean you could not see "
                f"anyone, and nobody could see you. Ask {who} to put you in a household "
                "first, and then you can leave this group whenever you like."
            )
        losing = {yard.id for yard in households.sides_lost(member, pod)}
        if losing:
            # A side of the family is going away for this member, which is the same
            # transition TM-1 names — so it fires the same one revocation act, before the
            # membership row is deleted.
            revocation.revoke_for_membership_shrink(member, losing_yard_ids=losing)
        PodMembership.objects.filter(member=member, pod=pod).delete()
        PodMute.objects.filter(member=member, pod=pod).delete()
        # Reply capabilities for this pod's posts die with the membership (S-502:
        # revoked on ANY membership change); the write path's audience re-check is
        # the second lock, this keeps the row state honest. Still run when no side was
        # lost, which is the ordinary case: leaving the cousins' group inside a side you
        # are still in narrows nothing, so nothing else should die.
        reply_addresses.void_for_pod_leave(member, pod)

        succeed_owner(pod)

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
    # so there was no path back. Inside the transaction with everything else, so a crash
    # between the delete and the succession cannot leave a departed owner in control.


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
