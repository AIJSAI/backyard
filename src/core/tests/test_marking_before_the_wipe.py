"""The live instance was seeded before `seeded_by` existed, so the wipe finds nothing there.

That is correct — its demo family carries the same empty marker every real person carries.
It also means launch day had no guarded path: the remaining options were to delete those
rows by hand at a shell, or to let the wipe select unmarked data. The second is the defect
`demo_data` exists to prevent; the first is how `Pod.objects.all().delete()` came to be
written in the first place.

Mark first, then wipe. Selection is by CONTAINMENT — you name yards, and a pod is marked
only if every yard it is in was named, a member only if every pod they are in was marked.
Same shape as `_refuse_if_it_strands_anyone`, one step earlier: rather than refusing a wipe
that would strand somebody, it declines to mark them at all.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core import demo_data, demo_marking
from core.models import Member, Pod, PodMembership, Post, Yard

MARKER = demo_data.SEED_MARKER


@dataclass
class Instance:
    """Named rather than a `dict[str, object]`: the dict form types every value as `object`,
    so `world.visitor.pk` neither type-checks nor tells a reader what is in there."""

    demo_pod: Pod
    demo_member: Member
    bridge: Pod
    bridger: Member
    visitor: Member
    real_pod: Pod


@pytest.fixture
def an_instance_that_predates_the_marker() -> Instance:
    """Two demo yards, one real yard, and the three awkward cases between them."""
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    real = Yard.objects.create(name="The real side", slug="real")

    demo_pod = Pod.objects.create(name="A demo household")
    demo_pod.yards.set([maternal])
    demo_member = Member.objects.create(display_name="A fixture person")
    PodMembership.objects.create(member=demo_member, pod=demo_pod)

    # A bridging household spanning a demo yard and the real one.
    bridge = Pod.objects.create(name="The bridging household")
    bridge.yards.set([paternal, real])
    bridger = Member.objects.create(display_name="Somebody real")
    PodMembership.objects.create(member=bridger, pod=bridge)

    # A real relative who joined a demo pod during QA but has their own household too.
    real_pod = Pod.objects.create(name="Their own house")
    real_pod.yards.set([real])
    visitor = Member.objects.create(display_name="A real visitor")
    PodMembership.objects.create(member=visitor, pod=real_pod)
    PodMembership.objects.create(member=visitor, pod=demo_pod)

    return Instance(
        demo_pod=demo_pod,
        demo_member=demo_member,
        bridge=bridge,
        bridger=bridger,
        visitor=visitor,
        real_pod=real_pod,
    )


@pytest.mark.django_db
def test_a_bridging_household_is_not_marked(
    an_instance_that_predates_the_marker: Instance,
) -> None:
    """It reaches a yard you did not name, so marking it would put that side in the wipe."""
    selected, spared = demo_marking.plan(yard_slugs=["maternal", "paternal"], marker=MARKER)

    assert "The bridging household" not in selected["Pod"]
    assert any("bridging household" in reason for reason in spared), spared
    assert any("The real side" in reason for reason in spared), (
        "the operator is not told WHICH side it reaches, which is the part they need to "
        f"recognise: {spared}"
    )


@pytest.mark.django_db
def test_a_real_person_in_a_demo_pod_is_not_marked(
    an_instance_that_predates_the_marker: Instance,
) -> None:
    """One of their pods is outside the set, so as far as this is concerned they are real."""
    selected, spared = demo_marking.plan(yard_slugs=["maternal", "paternal"], marker=MARKER)

    assert "A fixture person" in selected["Member"]
    assert "A real visitor" not in selected["Member"]
    assert any("A real visitor" in reason for reason in spared), spared


@pytest.mark.django_db
def test_marking_then_wiping_removes_the_demo_family_and_nothing_else(
    an_instance_that_predates_the_marker: Instance,
) -> None:
    """The whole launch-day sequence, end to end."""
    world = an_instance_that_predates_the_marker
    Post.objects.create(pod=world.real_pod, author=world.visitor, body="a real person's post")

    demo_marking.apply(yard_slugs=["maternal"], marker=MARKER)
    demo_data.wipe(MARKER)

    assert not Yard.objects.filter(slug="maternal").exists()
    assert not Pod.objects.filter(pk=world.demo_pod.pk).exists()
    assert not Member.objects.filter(pk=world.demo_member.pk).exists()

    # Everything real survives, including the person who was in a demo pod.
    assert Member.objects.filter(pk=world.visitor.pk).exists()
    assert Member.objects.filter(pk=world.bridger.pk).exists()
    assert Pod.objects.filter(pk=world.bridge.pk).exists()
    assert Post.objects.filter(body="a real person's post").exists()


@pytest.mark.django_db
def test_marking_is_reversible_before_the_wipe(
    an_instance_that_predates_the_marker: Instance,
) -> None:
    """An operator who marks the wrong yard needs a way back that is not another
    hand-written UPDATE — and needs it before the wipe, not after."""
    demo_marking.apply(yard_slugs=["maternal"], marker=MARKER)
    assert Yard.objects.filter(seeded_by=MARKER).exists()

    demo_marking.unmark(marker=MARKER)
    assert not Yard.objects.filter(seeded_by=MARKER).exists()
    assert not Pod.objects.filter(seeded_by=MARKER).exists()
    assert not Member.objects.filter(seeded_by=MARKER).exists()
    assert demo_data.preview(MARKER) == {}, "the wipe still sees something to do"


@pytest.mark.django_db
@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_marker_is_refused(
    blank: str, an_instance_that_predates_the_marker: Instance
) -> None:
    """The same trap as the wipe's: an empty marker is what every real row carries, so
    stamping it would make the whole family wipeable."""
    with pytest.raises(demo_marking.DemoMarkingError, match="blank marker"):
        demo_marking.plan(yard_slugs=["maternal"], marker=blank)


@pytest.mark.django_db
def test_an_unknown_yard_marks_nothing_and_says_so(
    an_instance_that_predates_the_marker: Instance,
) -> None:
    """A typo in a slug must not silently mark the subset that did match."""
    with pytest.raises(demo_marking.DemoMarkingError, match="maternnal"):
        demo_marking.plan(yard_slugs=["maternal", "maternnal"], marker=MARKER)
    assert not Yard.objects.filter(seeded_by=MARKER).exists()


@pytest.mark.django_db
def test_another_generators_marker_is_never_overwritten(
    an_instance_that_predates_the_marker: Instance,
) -> None:
    """`demo_data` promises different generators can be removed independently.

    Its own docstring says "a different generator should use a different marker so the two
    can be removed independently". Silently re-stamping one with another breaks exactly
    that: somebody else's fixture set becomes removable by a marker they did not choose, and
    NOT by their own — so the command they would run reports nothing to do.

    Refused rather than spared, because a partial mark hands the operator a set they did not
    preview.
    """
    other = Yard.objects.create(name="A second fixture set", slug="other-fixture")
    Yard.objects.filter(pk=other.pk).update(seeded_by="scratch")

    with pytest.raises(demo_marking.DemoMarkingError, match="DIFFERENT marker"):
        demo_marking.plan(yard_slugs=["maternal", "other-fixture"], marker=MARKER)

    other.refresh_from_db()
    assert other.seeded_by == "scratch", "it refused and re-stamped anyway"


@pytest.mark.django_db
def test_the_consistency_check_compares_identity_not_counts(
    an_instance_that_predates_the_marker: Instance,
) -> None:
    """A set that changes while keeping its SIZE is what a count cannot see.

    The first version compared `len()`. One member swapping in for another between the
    preview and the write leaves the count identical and the blast radius different — and
    the operator confirmed the one they were shown.
    """
    swapped = {"done": False}
    real_select = demo_marking._select

    def swap_one_member_between_preview_and_write(
        *, yard_slugs: list[str], marker: str
    ) -> tuple[demo_marking.Selection, list[str]]:
        selection, spared = real_select(yard_slugs=yard_slugs, marker=marker)
        if not swapped["done"] and selection.members:
            swapped["done"] = True
            # Same COUNT, different member: drop one and add a fresh one.
            selection.members.pop()
            selection.members.append(Member.objects.create(display_name="A different person"))
        return selection, spared

    demo_marking._select = swap_one_member_between_preview_and_write
    try:
        with pytest.raises(demo_marking.DemoMarkingError, match="changed between the preview"):
            demo_marking.apply(yard_slugs=["maternal"], marker=MARKER)
    finally:
        demo_marking._select = real_select

    assert not Yard.objects.filter(seeded_by=MARKER).exists(), (
        "it refused and stamped anyway — the refusal must roll the marking back"
    )


@pytest.mark.django_db
def test_the_preview_does_not_query_per_spared_row(
    an_instance_that_predates_the_marker: Instance,
) -> None:
    """`plan()` is what an operator reads before a destructive step, and it built each
    "deliberately not marked" reason with a fresh query — an N+1 on the one command whose
    output is meant to be read carefully.

    Asserted as "does not grow with the number of spared rows" rather than against a fixed
    count, which would be a magic number that gets edited whenever it fails.
    """
    yard = Yard.objects.get(slug="maternal")
    real = Yard.objects.get(slug="real")

    def queries_after_adding(bridges: int) -> int:
        for index in range(bridges):
            pod = Pod.objects.create(name=f"Bridge {index}")
            pod.yards.set([yard, real])
        with CaptureQueriesContext(connection) as captured:
            demo_marking.plan(yard_slugs=["maternal"], marker=MARKER)
        return len(captured)

    few = queries_after_adding(2)
    many = queries_after_adding(20)
    assert many <= few + 2, (
        f"plan() ran {few} queries with 2 spared pods and {many} with 22 — it is querying "
        "per row while building the very list the operator is supposed to read"
    )
