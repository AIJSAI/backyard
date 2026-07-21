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

from core import profiles, scoping
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


def test_relation_traversal_from_own_single_yard_pod(two_yards: dict[str, object]) -> None:
    """Membership-anchored traversal from a single-yard pod stays in-yard. This is
    the SAFE anchor; the dangerous anchors (a visible bridge member, a bridge pod in
    the viewer's own yard) are covered by the scoped-traversal tests below."""
    maternal_member = two_yards["maternal_member"]
    paternal_pod = two_yards["paternal_pod"]
    assert isinstance(maternal_member, Member)
    assert isinstance(paternal_pod, Pod)

    reachable_pods: set[int] = set()
    for pod in scoping.visible_pods(maternal_member):
        for yard in pod.yards.all():
            reachable_pods.update(yard.pods.values_list("id", flat=True))
    assert paternal_pod.id not in reachable_pods


def test_raw_traversal_of_visible_bridge_member_leaks_and_is_therefore_banned(
    two_yards: dict[str, object],
) -> None:
    """The HIGH-1 canary: the maternal member legitimately sees the bridge member,
    and RAW traversal of that member's relations (member.pods -> pod.yards) reaches
    the paternal yard, because Django related managers never filter. This test pins
    the hazard so it cannot be forgotten: views must use the visible_*_of accessors,
    never raw relations of non-self objects. If this test ever fails, base-manager
    behavior changed and the scoping rule should be re-derived, not deleted."""
    maternal_member = two_yards["maternal_member"]
    bridge_member = two_yards["bridge_member"]
    paternal = two_yards["paternal"]
    assert isinstance(maternal_member, Member)
    assert isinstance(bridge_member, Member)
    assert isinstance(paternal, Yard)

    assert scoping.require_visible_member(maternal_member, bridge_member.id)
    raw_reachable_yards = {y.id for p in bridge_member.pods.all() for y in p.yards.all()}
    assert paternal.id in raw_reachable_yards  # the leak raw traversal WOULD cause

    # The scoped accessors close it: the same walk through them stays maternal-only.
    scoped_yards = set(
        scoping.visible_yards_of(maternal_member, bridge_member).values_list("id", flat=True)
    )
    assert paternal.id not in scoped_yards
    for pod in scoping.visible_pods_of(maternal_member, bridge_member):
        scoped_pod_yards = set(
            scoping.visible_yards_of_pod(maternal_member, pod).values_list("id", flat=True)
        )
        assert paternal.id not in scoped_pod_yards


def test_bridge_pod_in_own_yard_never_renders_far_yard(two_yards: dict[str, object]) -> None:
    """The second HIGH-1 anchor: the bridge pod is legitimately in the maternal
    yard, but rendering its yard list must not reveal the paternal yard."""
    maternal_member = two_yards["maternal_member"]
    maternal = two_yards["maternal"]
    paternal = two_yards["paternal"]
    assert isinstance(maternal_member, Member)
    assert isinstance(maternal, Yard)
    assert isinstance(paternal, Yard)

    for pod in maternal.pods.all():  # every pod in the viewer's own yard, bridge included
        scoped = set(
            scoping.visible_yards_of_pod(maternal_member, pod).values_list("id", flat=True)
        )
        assert paternal.id not in scoped


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
    pod_yards: dict[int, set[int]]  # pod id -> its yard ids (independent ground truth)
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
        pod_yards=yard_ids_of,
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


def test_scoped_traversal_accessors_stay_in_viewer_yards(rich: Topology) -> None:
    """The HIGH-1 property, exhaustively: for every viewer and every member they can
    see, the scoped accessors return exactly the ground-truth intersection with the
    viewer's yards, so one relation hop from any visible object never leaves them.
    Bridge members and bridge pods are the cases that bite: ab, bc, and abc are
    visible from yards their other pods reach, and the far side must never render."""
    for viewer_name, viewer in rich.members.items():
        viewer_yards = rich.ground_yards[viewer_name]
        for target_name, target in rich.members.items():
            if not (viewer_yards & rich.ground_yards[target_name]):
                continue  # not visible; require_visible_member 404s (covered above)

            expected_yards = rich.ground_yards[target_name] & viewer_yards
            actual_yards = set(
                scoping.visible_yards_of(viewer, target).values_list("id", flat=True)
            )
            assert actual_yards == expected_yards, (
                f"{viewer_name} -> {target_name}: visible_yards_of leaked or dropped"
            )

            expected_pods = {
                pod_id
                for pod_id in rich.ground_pods[target_name]
                if rich.pod_yards[pod_id] & viewer_yards
            }
            actual_pods = set(scoping.visible_pods_of(viewer, target).values_list("id", flat=True))
            assert actual_pods == expected_pods, (
                f"{viewer_name} -> {target_name}: visible_pods_of leaked or dropped"
            )

            for pod in scoping.visible_pods_of(viewer, target):
                expected_pod_yards = rich.pod_yards[pod.id] & viewer_yards
                actual_pod_yards = set(
                    scoping.visible_yards_of_pod(viewer, pod).values_list("id", flat=True)
                )
                assert actual_pod_yards == expected_pod_yards, (
                    f"{viewer_name} -> pod {pod.name}: visible_yards_of_pod leaked or dropped"
                )


def test_zero_pod_member_is_invisible_including_to_themselves(rich: Topology) -> None:
    """Deny-by-default pinned: a member in no pod (not yet placed, or removed from
    every pod) has no yards, sees nobody, is seen by nobody, and cannot resolve
    themselves. If a later wave decides self-visibility should not require a pod,
    this test is the deliberate decision point, not an accident."""
    orphan = Member.objects.create(display_name="orphan")
    assert scoping.member_yard_ids(orphan) == set()
    assert list(scoping.visible_members(orphan)) == []
    with pytest.raises(Http404):
        scoping.require_visible_member(orphan, orphan.id)
    for other in rich.members.values():
        assert orphan.id not in set(scoping.visible_members(other).values_list("id", flat=True))


def test_malformed_id_404s_like_everything_else(rich: Topology) -> None:
    """S-202 parity for garbage ids: a non-integer pk must raise the same bare 404
    as not-exists and not-yours, never a distinguishable 500."""
    viewer = rich.members["a1"]
    for bad_id in ("not-an-int", "9; DROP TABLE", ""):
        with pytest.raises(Http404):
            scoping.require_visible_member(viewer, bad_id)  # type: ignore[arg-type]
        with pytest.raises(Http404):
            scoping.require_visible_pod(viewer, bad_id)  # type: ignore[arg-type]
        with pytest.raises(Http404):
            scoping.require_visible_yard(viewer, bad_id)  # type: ignore[arg-type]


def test_family_dates_never_cross_a_yard(two_yards: dict[str, object]) -> None:
    """S-903 joins the matrix: even at its WIDEST visibility (YARD), a date never
    reaches a viewer across the yard boundary. The bridge member, who shares the
    paternal yard, is the non-vacuous positive control."""
    import datetime

    paternal_member = two_yards["paternal_member"]
    maternal_member = two_yards["maternal_member"]
    bridge_member = two_yards["bridge_member"]
    assert isinstance(paternal_member, Member)
    assert isinstance(maternal_member, Member)
    assert isinstance(bridge_member, Member)
    paternal_member.birthday_month = 7
    paternal_member.birthday_day = 4
    paternal_member.birthday_visibility = Member.YARD
    paternal_member.save()

    start = datetime.date(2026, 1, 1)
    maternal_view = profiles.upcoming_dates(maternal_member, start=start, days=366)
    bridge_view = profiles.upcoming_dates(bridge_member, start=start, days=366)
    assert paternal_member.id not in {d.member_id for d in maternal_view}
    assert paternal_member.id in {d.member_id for d in bridge_view}  # positive control
