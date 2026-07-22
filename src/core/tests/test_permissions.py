"""S-701 write/grant authorization tests.

The permission model decides who may administer whom. These tests enumerate the
role ladder, the yard-admin scope boundary (a yard-A admin must never gain a lever
over yard B through a bridging member, T-AUTH-G2), and the managing-parent rule
for supervised children (TM-10).
"""

from __future__ import annotations

import pytest

from core import permissions
from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db


def _member(pod: Pod, name: str, role: str = Member.MEMBER, **kw: object) -> Member:
    m = Member.objects.create(display_name=name, role=role, **kw)
    PodMembership.objects.create(member=m, pod=pod)
    return m


@pytest.fixture
def world() -> dict[str, object]:
    a = Yard.objects.create(name="A", slug="a")
    b = Yard.objects.create(name="B", slug="b")
    pod_a = Pod.objects.create(name="A household")
    pod_a.yards.set([a])
    pod_b = Pod.objects.create(name="B household")
    pod_b.yards.set([b])
    bridge = Pod.objects.create(name="Bridge")
    bridge.yards.set([a, b])
    return {
        "a": a,
        "b": b,
        "pod_a": pod_a,
        "pod_b": pod_b,
        "bridge": bridge,
        "instance_admin": _member(pod_a, "Instance", Member.INSTANCE_ADMIN),
        "yard_a_admin": _member(pod_a, "A-admin", Member.YARD_ADMIN),
        "member_a": _member(pod_a, "A-member"),
        "member_b": _member(pod_b, "B-member"),
        "bridging_member": _member(bridge, "Bridger"),
    }


def test_plain_members_and_pod_owners_manage_no_one(world: dict[str, object]) -> None:
    member_a = world["member_a"]
    pod_owner = _member(world["pod_a"], "Owner", Member.POD_OWNER)  # type: ignore[arg-type]
    other = world["yard_a_admin"]
    assert isinstance(member_a, Member)
    assert isinstance(other, Member)
    assert not permissions.can_manage_member(member_a, other)
    assert not permissions.can_manage_member(pod_owner, other)


def test_no_self_administration(world: dict[str, object]) -> None:
    admin = world["instance_admin"]
    assert isinstance(admin, Member)
    assert not permissions.can_manage_member(admin, admin)


def test_instance_admin_manages_anyone(world: dict[str, object]) -> None:
    admin = world["instance_admin"]
    assert isinstance(admin, Member)
    for key in ("yard_a_admin", "member_a", "member_b", "bridging_member"):
        target = world[key]
        assert isinstance(target, Member)
        assert permissions.can_manage_member(admin, target)


def test_yard_admin_manages_only_within_scope(world: dict[str, object]) -> None:
    ya = world["yard_a_admin"]
    assert isinstance(ya, Member)
    # In-yard member: yes.
    assert permissions.can_manage_member(ya, world["member_a"])  # type: ignore[arg-type]
    # Other yard's member: no (can't even see them).
    assert not permissions.can_manage_member(ya, world["member_b"])  # type: ignore[arg-type]


def test_yard_admin_cannot_reach_a_bridging_member(world: dict[str, object]) -> None:
    """T-AUTH-G2: the bridging member belongs to A and B; a yard-A admin acting on
    them would gain a lever over yard B, so only the instance admin may."""
    ya = world["yard_a_admin"]
    bridger = world["bridging_member"]
    admin = world["instance_admin"]
    assert isinstance(ya, Member)
    assert isinstance(bridger, Member)
    assert isinstance(admin, Member)
    assert not permissions.can_manage_member(ya, bridger)
    assert permissions.can_manage_member(admin, bridger)


def test_supervised_child_is_managed_by_its_parent_or_instance_admin(
    world: dict[str, object],
) -> None:
    parent = world["member_a"]
    ya = world["yard_a_admin"]
    admin = world["instance_admin"]
    assert isinstance(parent, Member)
    child = _member(
        world["pod_a"],  # type: ignore[arg-type]
        "Kid",
        Member.SUPERVISED,
        is_supervised=True,
        managing_parent=parent,
    )
    # The parent (an ordinary member) manages their own child.
    assert permissions.can_manage_member(parent, child)
    # The instance admin can too.
    assert isinstance(admin, Member)
    assert permissions.can_manage_member(admin, child)
    # A yard admin who is NOT the parent cannot touch someone else's supervised child.
    assert isinstance(ya, Member)
    assert not permissions.can_manage_member(ya, child)


def test_only_instance_admin_grants_admin_roles(world: dict[str, object]) -> None:
    admin = world["instance_admin"]
    ya = world["yard_a_admin"]
    member_a = world["member_a"]
    assert isinstance(admin, Member)
    assert isinstance(ya, Member)
    assert isinstance(member_a, Member)
    # Instance admin can promote an in-scope member to yard admin.
    assert permissions.can_assign_role(admin, member_a, Member.YARD_ADMIN)
    # A yard admin can re-role an in-scope member to a non-admin role...
    assert permissions.can_assign_role(ya, member_a, Member.POD_OWNER)
    # ...but cannot grant the admin roles.
    assert not permissions.can_assign_role(ya, member_a, Member.YARD_ADMIN)
    assert not permissions.can_assign_role(ya, member_a, Member.INSTANCE_ADMIN)


def test_yard_admin_cannot_manage_another_admin_even_in_scope(world: dict[str, object]) -> None:
    """No privilege inversion: a yard admin sharing a yard with the instance admin
    (or a peer yard admin) still cannot administer them; only the instance admin can."""
    ya = world["yard_a_admin"]
    instance = world["instance_admin"]
    peer = _member(world["pod_a"], "A-admin-2", Member.YARD_ADMIN)  # type: ignore[arg-type]
    assert isinstance(ya, Member)
    assert isinstance(instance, Member)
    assert not permissions.can_manage_member(ya, instance)
    assert not permissions.can_manage_member(ya, peer)


def test_can_create_supervised_scope(world: dict[str, object]) -> None:
    parent = world["member_a"]
    ya = world["yard_a_admin"]
    admin = world["instance_admin"]
    b_parent = world["member_b"]
    assert isinstance(parent, Member)
    assert isinstance(ya, Member)
    assert isinstance(admin, Member)
    assert isinstance(b_parent, Member)
    assert permissions.can_create_supervised(parent, parent)  # a parent for their own child
    assert permissions.can_create_supervised(admin, parent)  # instance admin on anyone's behalf
    assert permissions.can_create_supervised(ya, parent)  # yard admin in scope
    assert not permissions.can_create_supervised(ya, b_parent)  # yard admin out of scope


def test_can_issue_invite_scope(world: dict[str, object]) -> None:
    """S-201/S-701 invite authority: the instance admin into any pod; a yard admin
    only into a pod whose yards are ALL within their own; nobody below an admin."""
    admin = world["instance_admin"]
    ya = world["yard_a_admin"]
    pod_a = world["pod_a"]
    pod_b = world["pod_b"]
    bridge = world["bridge"]
    for obj in (admin, ya, pod_a, pod_b, bridge):
        assert isinstance(obj, (Member, Pod))

    # The instance admin issues into any pod, including one in a yard they are not in
    # and the bridge pod that spans two yards.
    assert permissions.can_issue_invite(admin, pod_a)  # type: ignore[arg-type]
    assert permissions.can_issue_invite(admin, pod_b)  # type: ignore[arg-type]
    assert permissions.can_issue_invite(admin, bridge)  # type: ignore[arg-type]

    # A yard-A admin issues into a pod wholly in yard A...
    assert permissions.can_issue_invite(ya, pod_a)  # type: ignore[arg-type]
    # ...but NOT into another yard's pod, nor the bridge pod that spills into yard B
    # (T-AUTH-G2: minting there would seed a member the yard-A admin cannot see).
    assert not permissions.can_issue_invite(ya, pod_b)  # type: ignore[arg-type]
    assert not permissions.can_issue_invite(ya, bridge)  # type: ignore[arg-type]


def test_pod_owner_and_member_do_not_issue_invites_in_v1(world: dict[str, object]) -> None:
    """The analysis-loop judge's HIGH finding: an ownership-keyed invite branch would
    leak a cross-scope invite, so in v1 invite authority is the two admin roles only."""
    pod_a = world["pod_a"]
    assert isinstance(pod_a, Pod)
    pod_owner = _member(pod_a, "Owner", Member.POD_OWNER)
    plain = world["member_a"]
    assert isinstance(plain, Member)
    assert not permissions.can_issue_invite(pod_owner, pod_a)
    assert not permissions.can_issue_invite(plain, pod_a)


def test_yardless_pod_is_never_issuable_by_a_yard_admin(world: dict[str, object]) -> None:
    """A pod not yet placed in a yard is a non-vacuous empty set: a yard admin cannot
    issue into it (the same guard as _target_within_actor_scope), though the instance
    admin still can."""
    ya = world["yard_a_admin"]
    admin = world["instance_admin"]
    assert isinstance(ya, Member)
    assert isinstance(admin, Member)
    orphan = Pod.objects.create(name="Not placed yet")  # no .yards.set(...)
    assert not permissions.can_issue_invite(ya, orphan)
    assert permissions.can_issue_invite(admin, orphan)
