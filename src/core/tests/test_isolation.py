"""The S-202 isolation suite.

These tests are the merge gate for yard isolation. They assert the one property
the whole design rests on: a member of one yard cannot see or infer the existence
of another yard's content, and the guard returns the same 404 whether an object
does not exist or exists but belongs to another yard (docs/security/threat-model.md
S-202, TM-1, TM-2). The suite grows with every wave; this wave covers the
structural objects (yards, pods, members) and the relation-traversal path that
ADR-004 flags as the `_base_manager` hazard.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.http import Http404

from core import scoping
from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db


def _member_in(pod: Pod, name: str) -> Member:
    member = Member.objects.create(display_name=name)
    PodMembership.objects.create(member=member, pod=pod)
    return member


@pytest.fixture
def two_yards() -> dict[str, object]:
    """Two family sides with one bridging household, the founding shape.

    maternal and paternal yards; the bridge pod belongs to both; each side also
    has a pod that belongs only to it. One member per pod.
    """
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")

    bridge = Pod.objects.create(name="Bridge household")
    bridge.yards.set([maternal, paternal])
    maternal_pod = Pod.objects.create(name="Maternal cousins")
    maternal_pod.yards.set([maternal])
    paternal_pod = Pod.objects.create(name="Paternal cousins")
    paternal_pod.yards.set([paternal])

    return {
        "maternal": maternal,
        "paternal": paternal,
        "bridge_member": _member_in(bridge, "Bridging parent"),
        "maternal_member": _member_in(maternal_pod, "Maternal cousin"),
        "paternal_member": _member_in(paternal_pod, "Paternal cousin"),
        "maternal_pod": maternal_pod,
        "paternal_pod": paternal_pod,
    }


def test_member_sees_only_their_yard(two_yards: dict[str, object]) -> None:
    maternal_member = two_yards["maternal_member"]
    assert isinstance(maternal_member, Member)
    yard_ids = scoping.member_yard_ids(maternal_member)
    assert yard_ids == {two_yards["maternal"].id}  # type: ignore[attr-defined]


def test_bridging_member_sees_both_yards(two_yards: dict[str, object]) -> None:
    bridge_member = two_yards["bridge_member"]
    assert isinstance(bridge_member, Member)
    yard_ids = scoping.member_yard_ids(bridge_member)
    assert yard_ids == {two_yards["maternal"].id, two_yards["paternal"].id}  # type: ignore[attr-defined]


def test_cross_yard_yard_fetch_404s(two_yards: dict[str, object]) -> None:
    maternal_member = two_yards["maternal_member"]
    paternal_yard = two_yards["paternal"]
    assert isinstance(maternal_member, Member)
    assert isinstance(paternal_yard, Yard)
    with pytest.raises(Http404):
        scoping.require_visible_yard(maternal_member, paternal_yard.id)


def test_cross_yard_pod_fetch_404s(two_yards: dict[str, object]) -> None:
    maternal_member = two_yards["maternal_member"]
    paternal_pod = two_yards["paternal_pod"]
    assert isinstance(maternal_member, Member)
    assert isinstance(paternal_pod, Pod)
    with pytest.raises(Http404):
        scoping.require_visible_pod(maternal_member, paternal_pod.id)


def test_cross_yard_member_fetch_404s(two_yards: dict[str, object]) -> None:
    maternal_member = two_yards["maternal_member"]
    paternal_member = two_yards["paternal_member"]
    assert isinstance(maternal_member, Member)
    assert isinstance(paternal_member, Member)
    with pytest.raises(Http404):
        scoping.require_visible_member(maternal_member, paternal_member.id)


def test_not_exists_and_not_yours_are_indistinguishable(two_yards: dict[str, object]) -> None:
    """The core S-202 property: a cross-yard object and a nonexistent one raise the
    same Http404, so the 404 leaks no existence signal."""
    maternal_member = two_yards["maternal_member"]
    paternal_yard = two_yards["paternal"]
    assert isinstance(maternal_member, Member)
    assert isinstance(paternal_yard, Yard)

    missing_id = 9_999_999
    with pytest.raises(Http404) as not_yours:
        scoping.require_visible_yard(maternal_member, paternal_yard.id)
    with pytest.raises(Http404) as not_exists:
        scoping.require_visible_yard(maternal_member, missing_id)
    # Both raise the bare Http404 the 404 handler renders identically in production.
    assert str(not_yours.value) == str(not_exists.value) == ""


def test_bridging_member_sees_both_sides_members(two_yards: dict[str, object]) -> None:
    """The bridge sees members on both sides; a single-side member sees only theirs."""
    bridge_member = two_yards["bridge_member"]
    maternal_member = two_yards["maternal_member"]
    paternal_member = two_yards["paternal_member"]
    assert isinstance(bridge_member, Member)
    assert isinstance(maternal_member, Member)
    assert isinstance(paternal_member, Member)

    bridge_visible = set(scoping.visible_members(bridge_member).values_list("id", flat=True))
    assert {maternal_member.id, paternal_member.id, bridge_member.id} <= bridge_visible

    maternal_visible = set(scoping.visible_members(maternal_member).values_list("id", flat=True))
    assert paternal_member.id not in maternal_visible


def test_relation_traversal_stays_in_yard(two_yards: dict[str, object]) -> None:
    """The ADR-004 hazard: walking a relation from an in-yard anchor must not reach
    another yard. A maternal member walking pod -> yard -> pods must never surface a
    paternal-only pod."""
    maternal_member = two_yards["maternal_member"]
    paternal_pod = two_yards["paternal_pod"]
    assert isinstance(maternal_member, Member)
    assert isinstance(paternal_pod, Pod)

    reachable_pods: set[int] = set()
    for pod in scoping.visible_pods(maternal_member):
        for yard in pod.yards.all():
            reachable_pods.update(yard.pods.values_list("id", flat=True))
    # The maternal member's own pod is single-yard, so traversal reaches only
    # maternal pods, never the paternal-only pod.
    assert paternal_pod.id not in reachable_pods


# --- Exhaustive ground-truth property tests -------------------------------------
#
# The tests above use one hand-built topology. These build a richer one (three
# yards, single-yard pods, two-yard and three-yard bridge pods, and a member in
# two pods of the same yard) and check every guard function against a ground truth
# computed independently of the code under test, for every viewer/target pair. If
# any guard leaks across a yard or drops a legitimately visible object, one of
# these fails. This is the anchor for visible_members specifically: a member is
# visible exactly when the viewer and target share at least one yard.


@dataclass
class Topology:
    members: dict[str, Member]
    ground_yards: dict[str, set[int]]  # member name -> the yard ids they belong to
    ground_pods: dict[str, set[int]]  # member name -> the pod ids they belong to
    yards: dict[str, Yard]


@pytest.fixture
def rich() -> Topology:
    a = Yard.objects.create(name="A", slug="a")
    b = Yard.objects.create(name="B", slug="b")
    c = Yard.objects.create(name="C", slug="c")

    def pod(name: str, yards: list[Yard]) -> Pod:
        p = Pod.objects.create(name=name)
        p.yards.set(yards)
        return p

    p_a = pod("pod-A", [a])
    p_b = pod("pod-B", [b])
    p_c = pod("pod-C", [c])
    p_ab = pod("pod-AB", [a, b])
    p_bc = pod("pod-BC", [b, c])
    p_abc = pod("pod-ABC", [a, b, c])
    p_a2 = pod("pod-A2", [a])  # a second single-A pod, to make a member span two A pods

    # member name -> the pods they are in
    spec: dict[str, list[Pod]] = {
        "a1": [p_a, p_a2],  # in two yard-A pods: exercises .distinct()
        "a2": [p_a],
        "b1": [p_b],
        "c1": [p_c],
        "ab": [p_ab],
        "bc": [p_bc],
        "abc": [p_abc],
    }
    yard_ids_of = {
        p.id: {y.id for y in p.yards.all()} for p in [p_a, p_b, p_c, p_ab, p_bc, p_abc, p_a2]
    }

    members: dict[str, Member] = {}
    ground_yards: dict[str, set[int]] = {}
    ground_pods: dict[str, set[int]] = {}
    for name, pods in spec.items():
        member = Member.objects.create(display_name=name)
        for p in pods:
            PodMembership.objects.create(member=member, pod=p)
        members[name] = member
        ground_pods[name] = {p.id for p in pods}
        ground_yards[name] = set().union(*(yard_ids_of[p.id] for p in pods))

    return Topology(
        members=members,
        ground_yards=ground_yards,
        ground_pods=ground_pods,
        yards={"A": a, "B": b, "C": c},
    )


def test_visible_members_is_exactly_shared_yard(rich: Topology) -> None:
    """For every ordered pair, the target is visible exactly when viewer and target
    share a yard, and require_visible_member agrees (returns the member or 404s)."""
    for viewer_name, viewer in rich.members.items():
        expected = {
            rich.members[t].id
            for t in rich.members
            if rich.ground_yards[viewer_name] & rich.ground_yards[t]
        }
        actual = set(scoping.visible_members(viewer).values_list("id", flat=True))
        assert actual == expected, f"viewer {viewer_name}: visible_members leaked or dropped"

        for target_name, target in rich.members.items():
            shares_yard = bool(rich.ground_yards[viewer_name] & rich.ground_yards[target_name])
            if shares_yard:
                assert scoping.require_visible_member(viewer, target.id).id == target.id
            else:
                with pytest.raises(Http404):
                    scoping.require_visible_member(viewer, target.id)


def test_visible_pods_is_membership_not_yard(rich: Topology) -> None:
    """A member sees exactly the pods they belong to, not every pod in their yards:
    an ad-hoc pod does not leak to a yard-mate who is not in it (S-204)."""
    for viewer_name, viewer in rich.members.items():
        actual = set(scoping.visible_pods(viewer).values_list("id", flat=True))
        assert actual == rich.ground_pods[viewer_name], f"viewer {viewer_name}: visible_pods wrong"


def test_visible_yards_is_union_of_pod_yards(rich: Topology) -> None:
    for viewer_name, viewer in rich.members.items():
        actual = set(scoping.visible_yards(viewer).values_list("id", flat=True))
        assert actual == rich.ground_yards[viewer_name], (
            f"viewer {viewer_name}: visible_yards wrong"
        )


def test_distinct_collapses_multi_pod_visibility(rich: Topology) -> None:
    """The `.distinct()` in the guard is load-bearing: member a1 is in two yard-A pods,
    so a yard-A viewer would see them twice without it, and require_visible_member's
    `.get()` would raise MultipleObjectsReturned instead of returning the member."""
    viewer = rich.members["a2"]  # yard A
    target = rich.members["a1"]  # two yard-A pods
    ids = list(scoping.visible_members(viewer).values_list("id", flat=True))
    assert ids.count(target.id) == 1
    # Would raise MultipleObjectsReturned (a 500, not a 404) if .distinct() were dropped.
    assert scoping.require_visible_member(viewer, target.id).id == target.id
