"""Putting an existing member into a household, and taking them out again (BY-14).

The gap, measured: a member enters a household exactly one way — by redeeming an invite,
and `invites.redeem_invite` MINTS A NEW MEMBER. `pods.add_member_to_pod` refuses a
household outright ("Members join a household pod by invite, not here"), because ad-hoc
pods are the surface it was written for. So somebody who already had an account could not
be put into a household by any route in the product: not the founder placing a relative on
a side he had just created, and not a yard admin on the day someone joined the wrong
household, an adult child moved out, or two households merged. The only route was
`scripts/demo_seed.py` piped into a shell, which also re-seeds fixture data.

Three things make this different from adding somebody to an ad-hoc pod, and all three live
here rather than in the view:

1. ISOLATION. A household carries its sides, and a member's visible sides are the union of
   the sides of their pods (`scoping.member_yard_ids`). So adding somebody to a household
   in a side they were not in hands them that side's feed, directory and photographs. The
   view's confirm step states that in plain words before it happens; `sides_gained` and
   `sides_lost` below are what it states, computed from the same membership rows the act
   changes, so the sentence cannot describe a different act.

2. STRANDING. A member in no household resolves nobody through the guard — including
   themselves — so they have no feed, no directory and no self-service way back
   (`demo_data._refuse_if_it_strands_anyone` refuses a wipe for exactly this reason). The
   last household is therefore not removable here at all; a person who is really leaving
   goes through removal (S-702), which is a different, deliberate act.

3. REVOCATION. A removal here is a membership SHRINK, and TM-1 names the shrink
   transitions as firing the one revocation act. It runs `revocation.
   revoke_for_membership_shrink` BEFORE the membership row goes, which is the H-1 ordering
   contract — the invite step resolves its scope from live memberships, so revoking after
   teardown would silently miss them. It is the shrink registry, NOT the removal one: the
   person is still here, so the invites that die are the ones reaching the sides being LOST
   (a live invite there is a re-entry route, T-AUTH-G3) plus the ones they minted, and the
   digest SUBSCRIPTION survives — killing it would end an elder's only content channel with
   no route back for anybody on the instance, which is the silent severing S-501 forbids.
   The blast radius is stated on the confirm page rather than hidden.

An ADD is a widen: it strands nothing and revokes nothing, so it does not touch the
registry. The generation bump exists to kill credentials that outlived a scope, and after
an add every credential the member holds is still inside their scope.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import QuerySet

from . import permissions, scoping
from .models import HouseholdChange, Member, Pod, Yard
from .revocation import revoke_for_membership_shrink


class HouseholdChangeRefused(Exception):
    """The act is authorized but would be wrong: a duplicate, or the last household.

    Distinct from `PermissionDenied` on purpose — the view renders these as a sentence on
    the form the admin is already looking at, because they are answerable ("pick a
    different household", "remove them instead"), where an authorization failure is not.
    """


def households_in_reach(actor: Member) -> QuerySet[Pod]:
    """The households `actor` may put people into or take them out of.

    ONE queryset, used to render both pickers AND to resolve whatever they post back, so
    the page and the act cannot disagree about what was on offer — the shape that had
    `Elder link` rendering on rows where clicking it 403d. For a yard admin it is the
    households whose sides are ALL inside their own (`can_issue_invite`'s rule, expressed
    as a query, non-vacuous in the same way): a household on the other side is simply
    absent, so naming one by hand is the same byte-identical 404 as naming one that does
    not exist (S-202). An ad-hoc group is never in reach — it is its members' own (S-204).
    """
    households = Pod.objects.filter(kind=Pod.HOUSEHOLD)
    if not permissions.is_instance_admin(actor):
        actor_yards = scoping.member_yard_ids(actor)
        outside = Yard.objects.exclude(id__in=actor_yards)
        households = households.filter(yards__id__in=actor_yards).exclude(yards__id__in=outside)
    return households.distinct().order_by("name")


def households_they_could_join(actor: Member, member: Member) -> QuerySet[Pod]:
    """What the "add them to a household" picker offers: in reach, minus the ones they are
    already in. The exclusion is only on the OFFER, not on resolution — posting a household
    they are already in earns the plain sentence below rather than a 404, because a stale
    page or two admins working at once is a mistake to explain, not an attack to stonewall.
    """
    return households_in_reach(actor).exclude(memberships__member=member)


def households_they_are_in(actor: Member, member: Member) -> QuerySet[Pod]:
    """What the "take them out of a household" list offers.

    Scoped through `households_in_reach` for the same reason the other list is: a yard
    admin must not learn that a member of their own side also belongs to a household on the
    other one. `can_manage_member` already refuses a bridging target outright (T-AUTH-G2),
    so this is the second lock, not the first.
    """
    return households_in_reach(actor).filter(memberships__member=member)


def sides_gained(member: Member, pod: Pod) -> list[Yard]:
    """The sides of the family whose posts, people and photographs this member would start
    seeing if they joined `pod`. Empty when they are already on all of them."""
    already = scoping.member_yard_ids(member)
    return [yard for yard in pod.yards.order_by("name") if yard.id not in already]


def sides_lost(member: Member, pod: Pod) -> list[Yard]:
    """The sides they would STOP seeing if they left `pod`: the ones no other pod of theirs
    keeps them in. Computed from the remaining memberships rather than from the pod, because
    a member in two households on the same side loses nothing by leaving one of them."""
    # The member's OTHER pods first, then those pods' sides. Not
    # `Yard.objects.filter(pods__memberships__member=member).exclude(pods__id=pod.id)`,
    # which reads the same and is not: `exclude` on a multi-valued relation drops every
    # side this pod belongs to, so a member in two households on ONE side would be told
    # they are losing it while leaving one of them.
    other_pods = scoping.member_pod_ids(member) - {pod.id}
    keeps = set(Yard.objects.filter(pods__id__in=other_pods).values_list("id", flat=True))
    return [yard for yard in pod.yards.order_by("name") if yard.id not in keeps]


def _require_may(actor: Member, member: Member, pod: Pod) -> None:
    """Defense in depth behind the view's own check and the scoped querysets above. The
    same shape `invite_household` uses before it mints: the authorization is re-asked
    immediately before the write, inside the transaction, so no future caller can reach the
    membership change without it."""
    if not permissions.can_change_household_membership(actor, member, pod):
        raise PermissionDenied


def check_add(member: Member, pod: Pod) -> None:
    """Refuse an add that would be a no-op. Raises `HouseholdChangeRefused`.

    Public because the view asks it BEFORE showing the confirm step — an admin should not
    be asked to confirm something that is then refused — and `add_to_household` asks it
    again inside its transaction. One rule, two call sites, no second copy to drift.
    """
    if pod.memberships.filter(member=member).exists():
        raise HouseholdChangeRefused(f"{member.display_name} is already in {pod.name}.")


def check_remove(member: Member, pod: Pod) -> None:
    """Refuse a removal that is a no-op, or that would leave them in no household at all."""
    if not pod.memberships.filter(member=member).exists():
        raise HouseholdChangeRefused(f"{member.display_name} is not in {pod.name}.")
    if is_their_last_household(member, pod):
        raise HouseholdChangeRefused(
            f"{pod.name} is {member.display_name}'s only household, and somebody in no "
            "household cannot see anyone or be seen by anyone. Put them in another "
            "household first, or remove them from the family altogether."
        )


def check_create(name: str, yards: list[Yard]) -> None:
    """Refuse a new household with no name or no side of the family."""
    if not name:
        raise HouseholdChangeRefused("Give the household a name.")
    if not yards:
        raise HouseholdChangeRefused("Pick at least one side of the family.")


def add_to_household(*, actor: Member, member: Member, pod: Pod) -> HouseholdChange:
    """Put an existing member into an existing household, and record who did it.

    The member row is locked first, the same row every other household change for this
    person locks, so they serialise. Without it two admins adding the same person at the
    same instant both pass `check_add` and the loser hits the `unique_member_pod`
    constraint — a 500 on a family-facing admin screen instead of the plain "already in"
    sentence this module promises.
    """
    with transaction.atomic():
        Member.objects.select_for_update().get(pk=member.pk)
        _require_may(actor, member, pod)
        check_add(member, pod)
        pod.memberships.create(member=member)
        return HouseholdChange.objects.create(
            member=member, pod=pod, action=HouseholdChange.ADDED, changed_by=actor
        )


def create_household_and_add(
    *, actor: Member, member: Member, name: str, yards: list[Yard]
) -> tuple[Pod, HouseholdChange]:
    """Make a new household on the named sides and put the member in it.

    The pod is created first and authorized second, inside one transaction — the shape
    `invite_household` uses, and for the same reason: `can_issue_invite` answers about a
    pod's sides, so there has to be a pod to ask about. A refusal rolls the creation back,
    so no empty household is left behind by an act that was not allowed.
    """
    check_create(name, yards)
    with transaction.atomic():
        Member.objects.select_for_update().get(pk=member.pk)
        pod = Pod.objects.create(name=name, kind=Pod.HOUSEHOLD)
        pod.yards.set(yards)
        _require_may(actor, member, pod)
        pod.memberships.create(member=member)
        record = HouseholdChange.objects.create(
            member=member, pod=pod, action=HouseholdChange.ADDED, changed_by=actor
        )
    return pod, record


def remove_from_household(*, actor: Member, member: Member, pod: Pod) -> HouseholdChange:
    """Take a member out of one household: lock, revoke, detach, record.

    The order is the H-1 ordering contract, and it is why this is not two lines in a view:
    the shrink registry resolves its side scope from LIVE memberships, so revoking after the
    row is gone would silently miss every invite reaching the side the member has just left
    — the T-AUTH-G3 re-entry route, and the exact half of TM-1's shrink promise that issue
    174 records as unbuilt.

    The MEMBER ROW IS LOCKED FIRST, and it is the same row `revocation._run_steps` locks,
    so every household change for one person serialises on it. Without the lock the
    last-household count is a read with nothing behind it: two admins taking somebody out of
    their two remaining households at the same instant each see the other's row still
    present under READ COMMITTED, each pass `check_remove`, and both deletes land — leaving
    a member in no household at all, who then resolves nobody through the guard including
    themselves. That is the one state this function exists to refuse, so the refusal has to
    hold against a race and not only against a second click.
    """
    with transaction.atomic():
        Member.objects.select_for_update().get(pk=member.pk)
        _require_may(actor, member, pod)
        check_remove(member, pod)
        # 1. Revoke while the membership still exists (H-1), because the invite scope is
        #    resolved from it, and scope the shrink to the sides actually being lost.
        losing = {yard.id for yard in sides_lost(member, pod)}
        revoke_for_membership_shrink(member, losing_yard_ids=losing)
        # 2. Then detach.
        pod.memberships.filter(member=member).delete()
        return HouseholdChange.objects.create(
            member=member, pod=pod, action=HouseholdChange.REMOVED, changed_by=actor
        )


def is_their_last_household(member: Member, pod: Pod) -> bool:
    """Would taking them out of `pod` leave them in no household at all?

    HOUSEHOLD, not pod. A member left holding only an ad-hoc group still resolves a side
    and so is not stranded in the `demo_data` sense — but they are in a state the product
    has no route out of: `create_adhoc_pod` and `add_member_to_pod` cannot make or fill a
    household, and an invite mints a NEW member rather than re-seating this one. Refusing
    on the household is the strictly safer of the two lines and the one a person can act
    on, which is why it is also the sentence the page shows.
    """
    return not (
        Pod.objects.filter(kind=Pod.HOUSEHOLD, memberships__member=member)
        .exclude(id=pod.id)
        .exists()
    )
