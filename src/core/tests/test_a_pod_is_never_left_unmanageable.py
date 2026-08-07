"""An ad-hoc pod whose owner goes away must not freeze.

`pod.owner_id != actor.id` is the only gate on `set_house_rule` and `add_member_to_pod`, and
`Pod.owner` is set at creation and nowhere else. So an owner who stops being a member leaves
the pod in one of two bad states, both measured on the product as it was:

    A) owner LEFT: owner_id=1 still_member=False
       departed owner can STILL set the house rule: YES
    B) owner DELETED: owner_id=None members=1
       set_house_rule by remaining member: PodActionNotAllowed
       add_member    by remaining member: PodActionNotAllowed

(A) is somebody keeping control of a group they walked out of. (B) is the group frozen for
every person alive, with no path back anywhere in the product — reachable through the demo
wipe, through S-702 removal, and through a member simply deleting their own account.

One rule closes both: ownership follows membership.
"""

from __future__ import annotations

import pytest

from core import demo_data, pods
from core.models import Member, Pod, PodMembership, Yard

MARKER = demo_data.SEED_MARKER


@pytest.fixture
def club() -> tuple[Pod, Member, Member]:
    yard = Yard.objects.create(name="Y", slug="y")
    house = Pod.objects.create(name="House")
    house.yards.set([yard])
    owner = Member.objects.create(display_name="The founder")
    joiner = Member.objects.create(display_name="Joined second")
    latecomer = Member.objects.create(display_name="Joined third")
    for member in (owner, joiner, latecomer):
        PodMembership.objects.create(member=member, pod=house)
    adhoc = pods.create_adhoc_pod(owner=owner, yard=yard, name="Book club")
    PodMembership.objects.create(member=joiner, pod=adhoc)
    PodMembership.objects.create(member=latecomer, pod=adhoc)
    return adhoc, owner, joiner


@pytest.mark.django_db
def test_leaving_hands_the_pod_to_the_longest_standing_member(
    club: tuple[Pod, Member, Member],
) -> None:
    adhoc, owner, joiner = club
    pods.leave_pod(member=owner, pod=adhoc)
    adhoc.refresh_from_db()

    assert adhoc.owner_id == joiner.pk, (
        "the pod did not pass to the member who has been in it longest; it went to "
        f"{adhoc.owner_id}"
    )
    # And the person who left no longer runs it.
    with pytest.raises(pods.PodActionNotAllowed):
        pods.set_house_rule(actor=owner, pod=adhoc, house_rule="I still run this")
    # While the new owner does.
    pods.set_house_rule(actor=joiner, pod=adhoc, house_rule="Tuesdays")
    adhoc.refresh_from_db()
    assert adhoc.house_rule == "Tuesdays"


@pytest.mark.django_db
def test_deleting_the_owner_hands_the_pod_on_rather_than_freezing_it(
    club: tuple[Pod, Member, Member],
) -> None:
    """`SET_NULL` is what makes this permanent: nothing counts a nulled field, so the wipe's
    receipt would not have mentioned the pod it had just made unmanageable."""
    adhoc, owner, joiner = club
    owner.delete()
    adhoc.refresh_from_db()
    assert adhoc.owner_id is None, "premise changed: the FK is no longer SET_NULL"

    assert pods.succeed_owner(adhoc) == joiner
    adhoc.refresh_from_db()

    # Both frozen capabilities work again, exercised with real inputs — adding somebody who
    # is not already in the pod, so a no-op cannot pass for a success.
    pods.set_house_rule(actor=joiner, pod=adhoc, house_rule="Still ours")
    adhoc.refresh_from_db()
    assert adhoc.house_rule == "Still ours"

    newcomer = Member.objects.create(display_name="A new reader")
    PodMembership.objects.create(member=newcomer, pod=Pod.objects.get(name="House"))
    pods.add_member_to_pod(actor=joiner, pod=adhoc, new_member=newcomer)
    assert adhoc.members.filter(pk=newcomer.pk).exists()


@pytest.mark.django_db
def test_the_wipe_does_not_leave_a_real_pod_unmanageable() -> None:
    """The route that matters on launch day: a fixture account created the founder's book
    club during QA, and clearing the demo family takes its owner with it."""
    yard = Yard.objects.create(name="Y", slug="y", seeded_by=MARKER)
    demo_pod = Pod.objects.create(name="Demo household", seeded_by=MARKER)
    demo_pod.yards.set([yard])
    seeded = Member.objects.create(display_name="A fixture person", seeded_by=MARKER)
    PodMembership.objects.create(member=seeded, pod=demo_pod)

    real_yard = Yard.objects.create(name="Real", slug="real")
    real_house = Pod.objects.create(name="Real house")
    real_house.yards.set([real_yard])
    real = Member.objects.create(display_name="A real person")
    PodMembership.objects.create(member=real, pod=real_house)
    PodMembership.objects.create(member=seeded, pod=real_house)

    # The fixture account made the club; a real person is in it.
    adhoc = pods.create_adhoc_pod(owner=seeded, yard=real_yard, name="Book club")
    PodMembership.objects.create(member=real, pod=adhoc)

    demo_data.wipe(MARKER)

    adhoc.refresh_from_db()
    assert adhoc.owner_id == real.pk, (
        "the wipe deleted the pod's owner and left it ownerless. `pod.owner_id != actor.id` "
        "gates its house rule and member list, and None never equals anybody, so the pod is "
        "frozen for everyone — and the receipt would not have mentioned it, because a nulled "
        "field is not a deletion."
    )
    pods.set_house_rule(actor=real, pod=adhoc, house_rule="Ours now")


@pytest.mark.django_db
def test_an_empty_pod_is_left_ownerless_rather_than_given_to_nobody(
    club: tuple[Pod, Member, Member],
) -> None:
    """There is no one to hand it to, and an empty pod has nothing to manage. The stale
    pointer is still cleared, so it does not name somebody who is gone."""
    adhoc, owner, joiner = club
    PodMembership.objects.filter(pod=adhoc).delete()
    assert pods.succeed_owner(adhoc) is None
    adhoc.refresh_from_db()
    assert adhoc.owner_id is None


@pytest.mark.django_db
def test_a_household_pod_is_untouched(club: tuple[Pod, Member, Member]) -> None:
    """Households have no owner by design — admins create them. Succession must not invent
    one, or a household would acquire a member who can set a house rule it cannot have."""
    house = Pod.objects.get(name="House")
    assert house.kind == Pod.HOUSEHOLD and house.owner_id is None
    assert pods.succeed_owner(house) is None
    house.refresh_from_db()
    assert house.owner_id is None


@pytest.mark.django_db
def test_s702_removal_hands_on_a_pod_the_removed_member_owned(
    club: tuple[Pod, Member, Member],
) -> None:
    """The third route, and the one an admin actually uses.

    `removal.remove_member` deletes every `PodMembership` and never touched `Pod.owner`, so
    removing somebody who owned an ad-hoc pod left it frozen for everyone still in it —
    the same state `leave_pod` and the wipe already close, reached differently.

    It was named in this branch's own description as one of three routes and wired for only
    two. Review caught the gap.
    """
    from core import removal

    adhoc, owner, joiner = club
    removal.remove_member(member=owner, content=removal.KEEP)

    adhoc.refresh_from_db()
    assert adhoc.owner_id == joiner.pk, (
        "removing the owner left the pod ownerless; nobody remaining can set its house rule "
        "or add anyone, and no reassignment path exists"
    )
    pods.set_house_rule(actor=joiner, pod=adhoc, house_rule="Ours now")


@pytest.mark.django_db
def test_the_wipe_only_reassigns_pods_it_orphaned(
    club: tuple[Pod, Member, Member],
) -> None:
    """A demo wipe must not touch a real pod that was already ownerless.

    The first version scanned every ownerless ad-hoc pod on the instance, so an unrelated
    one — ownerless for its own reasons, long before this — would be silently reassigned and
    counted in the receipt the operator reads to decide whether the wipe did what they meant.
    """
    adhoc, _owner, _joiner = club
    # A real pod that has been ownerless since before any of this.
    yard = Yard.objects.get(slug="y")
    unrelated = Pod.objects.create(name="Ownerless for its own reasons", kind=Pod.ADHOC)
    unrelated.yards.set([yard])
    bystander = Member.objects.create(display_name="A bystander")
    PodMembership.objects.create(member=bystander, pod=Pod.objects.get(name="House"))
    PodMembership.objects.create(member=bystander, pod=unrelated)

    # A wipe that has nothing to do with either.
    demo_yard = Yard.objects.create(name="Demo", slug="demo-yard", seeded_by=MARKER)
    demo_pod = Pod.objects.create(name="Demo household", seeded_by=MARKER)
    demo_pod.yards.set([demo_yard])
    seeded = Member.objects.create(display_name="Fixture", seeded_by=MARKER)
    PodMembership.objects.create(member=seeded, pod=demo_pod)

    receipt = demo_data.wipe(MARKER)

    unrelated.refresh_from_db()
    assert unrelated.owner_id is None, (
        "the wipe reassigned a real pod it did not orphan; a demo wipe has no business "
        "changing who owns somebody's book club"
    )
    assert receipt.get("pods reassigned", 0) == 0, (
        f"the receipt claims {receipt.get('pods reassigned')} pod(s) reassigned, which "
        "overstates what this wipe did"
    )
