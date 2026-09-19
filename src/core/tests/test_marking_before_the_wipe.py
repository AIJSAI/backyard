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

R2-5 adds the one case containment cannot see: a member who was REMOVED keeps their Member
row and loses every membership, so they are in no pod and no containment rule can reach them
— while their posts stay inside a fixture household. `--include-departed` is the narrow way
in, and the tests for it are at the foot of this file.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core import demo_data, demo_marking, removal
from core.models import Comment, Member, Pod, PodMembership, Post, Reaction, Yard

MARKER = demo_data.SEED_MARKER
User = get_user_model()


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
    selected, spared, _ = demo_marking.plan(yard_slugs=["maternal", "paternal"], marker=MARKER)

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
    selected, spared, _ = demo_marking.plan(yard_slugs=["maternal", "paternal"], marker=MARKER)

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
        *, yard_slugs: list[str], marker: str, include_departed: bool = False
    ) -> tuple[demo_marking.Selection, list[str], list[Member]]:
        selection, spared, departed = real_select(
            yard_slugs=yard_slugs, marker=marker, include_departed=include_departed
        )
        if not swapped["done"] and selection.members:
            swapped["done"] = True
            # Same COUNT, different member: drop one and add a fresh one.
            selection.members.pop()
            selection.members.append(Member.objects.create(display_name="A different person"))
        return selection, spared, departed

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


# --- R2-5: the member who was already removed -------------------------------------------
#
# Measured on the live instance, 2026-09-19, as a dry run: `mark_demo_data` selects members
# by containment, a removed member has no household, so they are never marked — and their
# posts stay inside a household that IS marked, because "keep their posts" and "remove their
# name" both keep `author_id`. `wipe_demo_data` then refuses forever with "a post written by
# someone real", and the only cure was a shell snippet, which is the act this whole module
# exists to replace.


def _removed_from(pod: Pod, *, name: str, username: str, content: str) -> tuple[Member, Post]:
    """Somebody who was in `pod`, wrote there, and was then removed through the S-702 flow.

    Returns them and the post they left behind, because after `ANONYMIZE` their display
    name is no longer theirs and a test that looked them up by name would be asserting
    about the placeholder.
    """
    user = User.objects.create_user(username=username)
    member = Member.objects.create(display_name=name, user=user)
    PodMembership.objects.create(member=member, pod=pod)
    post = Post.objects.create(author=member, pod=pod, body=f"{name} was here")
    removal.remove_member(member, content=content)
    member.refresh_from_db()
    return member, post


@pytest.mark.django_db
def test_a_removed_members_whole_footprint_inside_the_set_needs_the_flag_and_then_marks(
    an_instance_that_predates_the_marker: Instance,
) -> None:
    """Both halves of R2-5's default, on one person.

    WITHOUT the flag nothing changes except that they are LISTED, with the reason and with
    the flag named — so the operator learns it exists at the moment it would have helped,
    rather than after the wipe has refused and sent them to a shell.
    """
    world = an_instance_that_predates_the_marker
    gone, _post = _removed_from(
        world.demo_pod, name="A departed cousin", username="departed", content=removal.KEEP
    )

    selected, spared, departed = demo_marking.plan(yard_slugs=["maternal"], marker=MARKER)
    assert "A departed cousin" not in selected["Member"], (
        "they were marked without the flag, which changes what an irreversible command "
        "deletes on a plain re-run"
    )
    assert departed == []
    reasons = [reason for reason in spared if "A departed cousin" in reason]
    assert len(reasons) == 1, spared
    assert "already removed" in reasons[0], reasons[0]
    assert "--include-departed" in reasons[0], (
        f"the operator is not told the flag exists: {reasons[0]}"
    )

    selected, spared, departed = demo_marking.plan(
        yard_slugs=["maternal"], marker=MARKER, include_departed=True
    )
    assert "A departed cousin" in selected["Member"]
    assert departed == ["A departed cousin"]
    assert not any("A departed cousin" in reason for reason in spared), (
        "they are both marked and spared, so the operator is told two different things"
    )


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["post", "reply", "reaction"])
def test_one_row_outside_the_marked_households_and_they_are_never_selected(
    an_instance_that_predates_the_marker: Instance, kind: str
) -> None:
    """The other direction, and the whole safety of the rule.

    A reaction is in here beside a post and a reply on purpose. The wipe's own guard does
    NOT refuse on a real person's reaction (walk item 30) — it is not authorship — so it
    would be easy to reason that a reaction cannot tell you anything about whose person a
    row belongs to either. It can: a reaction OUTSIDE the marked households is evidence
    that this member has a life beyond the fixture family, which is exactly the question
    this rule is asking. One is enough.
    """
    world = an_instance_that_predates_the_marker
    gone, _post = _removed_from(
        world.demo_pod, name="A departed cousin", username="departed", content=removal.KEEP
    )
    elsewhere = Post.objects.create(
        author=world.visitor, pod=world.real_pod, body="a real person's post"
    )
    if kind == "post":
        Post.objects.create(author=gone, pod=world.real_pod, body="and one over here")
    elif kind == "reply":
        Comment.objects.create(post=elsewhere, author=gone, body="lovely")
    else:
        Reaction.objects.create(post=elsewhere, member=gone, kind=Reaction.HEART)

    selected, _spared, departed = demo_marking.plan(
        yard_slugs=["maternal"], marker=MARKER, include_departed=True
    )
    assert departed == [], f"a {kind} outside the marked households did not keep them out"
    assert "A departed cousin" not in selected["Member"]

    # And the flag really is what is being tested: take the outside row away and the same
    # call selects them, so this is a condition on the data rather than a dead branch.
    Post.objects.filter(author=gone, pod=world.real_pod).delete()
    Comment.objects.filter(author=gone).delete()
    Reaction.objects.filter(member=gone).delete()
    _selected, _spared, departed = demo_marking.plan(
        yard_slugs=["maternal"], marker=MARKER, include_departed=True
    )
    assert departed == ["A departed cousin"]


@pytest.mark.django_db
def test_a_soft_deleted_post_outside_still_counts_as_a_footprint(
    an_instance_that_predates_the_marker: Instance,
) -> None:
    """ "Delete their posts" stamps `deleted_at` and keeps the row, and the wipe's own
    guard reads the same unfiltered table — so a post the family can no longer see is
    still a post that is somewhere. A somewhere outside this set is still a reason not to
    touch them."""
    world = an_instance_that_predates_the_marker
    gone, _post = _removed_from(
        world.demo_pod, name="A departed cousin", username="departed", content=removal.KEEP
    )
    outside = Post.objects.create(author=gone, pod=world.real_pod, body="over here")
    outside.deleted_at = timezone.now()
    outside.save(update_fields=["deleted_at"])

    _selected, _spared, departed = demo_marking.plan(
        yard_slugs=["maternal"], marker=MARKER, include_departed=True
    )
    assert departed == [], "a soft-deleted post outside the set was treated as no post"


@pytest.mark.django_db
def test_somebody_still_in_a_household_is_not_a_departed_candidate(
    an_instance_that_predates_the_marker: Instance,
) -> None:
    """Non-vacuity for condition 1, the one that keeps the candidate set small.

    The real relative who joined a demo pod during QA still has their own household, so
    containment spares them — and the departed rule must not be a second route to the same
    person. Asserted even with a post of theirs inside the marked household, which is the
    entry ticket condition 2 asks for: the ticket is not enough on its own.
    """
    world = an_instance_that_predates_the_marker
    Post.objects.create(pod=world.demo_pod, author=world.visitor, body="a QA post")

    _selected, spared, departed = demo_marking.plan(
        yard_slugs=["maternal"], marker=MARKER, include_departed=True
    )
    assert departed == [], departed
    assert "A real visitor" not in _selected["Member"]
    assert any("A real visitor" in reason for reason in spared), spared
    assert world.visitor.pods.exists()


@pytest.mark.django_db
def test_undo_clears_a_departed_member_like_any_other_row(
    an_instance_that_predates_the_marker: Instance,
) -> None:
    """One way back, and it does not need to know which rule put a row into the set:
    `unmark` selects on the marker and on nothing else."""
    world = an_instance_that_predates_the_marker
    gone, _post = _removed_from(
        world.demo_pod, name="A departed cousin", username="departed", content=removal.KEEP
    )
    demo_marking.apply(yard_slugs=["maternal"], marker=MARKER, include_departed=True)
    gone.refresh_from_db()
    assert gone.seeded_by == MARKER, "the flag did not stamp them, so undo proves nothing"

    demo_marking.unmark(marker=MARKER)

    gone.refresh_from_db()
    assert gone.seeded_by == "", "a departed member stayed marked after --undo"
    assert demo_data.preview(MARKER) == {}, "the wipe still sees something to do"


@pytest.mark.django_db
def test_the_dry_run_names_every_departed_person_under_its_own_heading(
    an_instance_that_predates_the_marker: Instance,
) -> None:
    """They are inside the Member list as well, where nothing distinguishes them. An
    operator scanning "Member (9)" has no way to tell which of those nine are here because
    somebody removed them, and that is the group selected by the rule they just switched
    on — so it gets read on its own.

    THE HEADING NAMES THE COST. It used to say "everything they ever wrote is inside these
    sides", which is true and reads like housekeeping; what actually happens is that a
    person's Member row and their sign-in account are destroyed. `wipe_demo_data --dry-run`
    prints counts and never names, so this line is the only place these names ever appear.
    """
    world = an_instance_that_predates_the_marker
    _removed_from(
        world.demo_pod, name="A departed cousin", username="departed", content=removal.KEEP
    )

    out = io.StringIO()
    call_command(
        "mark_demo_data", "--yard", "maternal", "--include-departed", "--dry-run", stdout=out
    )
    printed = out.getvalue()
    assert (
        "Already removed, wrote only inside these sides, and blocking the wipe (1) — their "
        "Member row AND their sign-in account go:" in printed
    ), printed
    heading = printed.index("Already removed,")
    assert "A departed cousin" in printed[heading:], printed
    assert "Nothing was changed" in printed
    assert not Member.objects.filter(seeded_by=MARKER).exists(), "the dry run wrote the marker"

    # And the same run WITHOUT the flag says the name under the other heading, with the
    # flag in the sentence and the cost of using it.
    out = io.StringIO()
    call_command("mark_demo_data", "--yard", "maternal", "--dry-run", stdout=out)
    printed = out.getvalue()
    assert "blocking the wipe" not in printed
    spared = printed.index("Deliberately NOT marked:")
    assert "A departed cousin" in printed[spared:]
    assert "--include-departed" in printed[spared:]
    assert "sign-in account" in printed[spared:]


@pytest.mark.django_db
def test_the_wipe_finishes_after_people_were_removed_from_a_fixture_household(
    an_instance_that_predates_the_marker: Instance,
) -> None:
    """The whole of R2-5, end to end, as it happened on the live instance.

    Two people are removed from the fixture household, one with "keep their posts" and one
    with "remove their name" — the two choices that KEEP `author_id`. Marking by
    containment alone then leaves the wipe permanently refused on their posts. With the
    flag it finishes: their posts go with the household, their auth accounts go with them,
    and the real family is untouched.
    """
    world = an_instance_that_predates_the_marker
    kept, kept_post = _removed_from(
        world.demo_pod, name="A departed cousin", username="departed", content=removal.KEEP
    )
    nameless, nameless_post = _removed_from(
        world.demo_pod, name="Another cousin", username="alsodeparted", content=removal.ANONYMIZE
    )
    kept_user, nameless_user = kept.user_id, nameless.user_id
    assert kept_user is not None and nameless_user is not None
    real_post = Post.objects.create(
        author=world.visitor, pod=world.real_pod, body="a real person's post"
    )

    # The defect: containment alone marks the household and not the people who left it.
    demo_marking.apply(yard_slugs=["maternal"], marker=MARKER)
    with pytest.raises(demo_data.DemoDataError, match="written by someone real"):
        demo_data.wipe(MARKER)
    assert Post.objects.filter(pk=kept_post.pk).exists(), "it deleted despite refusing"
    demo_marking.unmark(marker=MARKER)

    demo_marking.apply(yard_slugs=["maternal"], marker=MARKER, include_departed=True)
    removed = demo_data.wipe(MARKER)

    assert removed, "the wipe deleted nothing, so nothing below is proven"
    for pk in (kept.pk, nameless.pk):
        assert not Member.objects.filter(pk=pk).exists(), "a departed member survived"
    for pk in (kept_post.pk, nameless_post.pk):
        assert not Post.objects.filter(pk=pk).exists(), "a departed member's post survived"
    for pk in (kept_user, nameless_user):
        assert not User.objects.filter(pk=pk).exists(), (
            "a departed member's auth account survived the wipe that deleted their member"
        )

    # The real family, every row of it.
    assert Member.objects.filter(pk=world.visitor.pk).exists(), "a real member was deleted"
    assert Member.objects.filter(pk=world.bridger.pk).exists(), "a real member was deleted"
    assert Pod.objects.filter(pk=world.real_pod.pk).exists(), "a real household was deleted"
    assert Pod.objects.filter(pk=world.bridge.pk).exists(), "a real household was deleted"
    assert Post.objects.filter(pk=real_post.pk).exists(), "a real person's post was deleted"


@pytest.mark.django_db
@pytest.mark.parametrize("how", ["removed from a real household", "never placed at all"])
def test_a_pod_less_member_who_never_wrote_anything_is_never_selected(
    an_instance_that_predates_the_marker: Instance, how: str
) -> None:
    """The hole the first version of this rule had, and the reason there is an entry ticket.

    "In no pod" plus "nothing of theirs sits outside" is passed VACUOUSLY by somebody who
    never wrote anything at all — and "in no pod" is not only what removal leaves. It is
    also what a relative removed from a REAL household on a side this run did not name
    looks like, and what an account created and never placed looks like.

    Measured in review before the ticket existed: with the flag, such a person was selected,
    and the wipe then deleted their Member row AND their auth account, under a heading
    telling the operator that everything they ever wrote was inside these sides. It also
    bought nothing: the only rows that stop the wipe are a post or a reply inside the
    closure, and this person has neither.

    Both shapes are here because they fail different halves of the old reasoning: the first
    person WAS removed (so "already removed" is true of them) and the second never was.
    """
    if how == "removed from a real household":
        # Their household is in `real`, a side this run does not name. Removal empties
        # their memberships, which is exactly the state the candidate query looks for.
        elsewhere = Pod.objects.create(name="A real household")
        elsewhere.yards.set([Yard.objects.get(slug="real")])
        user = User.objects.create_user(username="departedreal")
        person = Member.objects.create(display_name="A Real Relative", user=user)
        PodMembership.objects.create(member=person, pod=elsewhere)
        removal.remove_member(person, content=removal.KEEP)
    else:
        user = User.objects.create_user(username="neverplaced")
        person = Member.objects.create(display_name="A Real Relative", user=user)
    assert not person.pods.exists(), "fixture: they must be in no household"

    _selected, spared, departed = demo_marking.plan(
        yard_slugs=["maternal"], marker=MARKER, include_departed=True
    )
    assert departed == [], (
        "somebody who never wrote a word was selected, so the flag would delete their "
        "Member row and their sign-in account for no reason at all"
    )
    assert "A Real Relative" not in _selected["Member"]

    # ...and they are not named under "Deliberately NOT marked" either. Listing them would
    # teach the operator a flag that would not have helped, on the screen they read before
    # something irreversible.
    assert not any("A Real Relative" in reason for reason in spared), spared

    # The marking still runs and the wipe still finishes; this person simply is not in it.
    demo_marking.apply(yard_slugs=["maternal"], marker=MARKER, include_departed=True)
    person.refresh_from_db()
    assert person.seeded_by == "", "they were marked anyway"
    assert User.objects.filter(pk=user.pk).exists()


@pytest.mark.django_db
def test_a_departed_member_whose_supervised_child_is_staying_is_never_selected(
    an_instance_that_predates_the_marker: Instance,
) -> None:
    """`Member.managing_parent` is SET_NULL, so deleting a parent leaves a real child with
    nobody recorded as looking after them — and neither the preview nor the receipt would
    mention it, because a field set to NULL is not a deletion and nothing counts it.

    The child here is in a REAL household, so the marking is not taking them. The parent
    otherwise qualifies on every other condition, which is what makes this a veto rather
    than a coincidence.
    """
    world = an_instance_that_predates_the_marker
    parent, _post = _removed_from(
        world.demo_pod, name="A departed parent", username="departedparent", content=removal.KEEP
    )
    child = Member.objects.create(
        display_name="Their child", is_supervised=True, managing_parent=parent
    )
    PodMembership.objects.create(member=child, pod=world.real_pod)

    _selected, _spared, departed = demo_marking.plan(
        yard_slugs=["maternal"], marker=MARKER, include_departed=True
    )
    assert departed == [], (
        "the parent was selected while their supervised child stays in a real household, "
        "so the wipe would silently null the child's managing_parent"
    )

    # The veto is a condition on the data, not a permanent block: move the child into a
    # household this run IS marking and the parent is selected again.
    PodMembership.objects.filter(member=child).delete()
    PodMembership.objects.create(member=child, pod=world.demo_pod)
    _selected, _spared, departed = demo_marking.plan(
        yard_slugs=["maternal"], marker=MARKER, include_departed=True
    )
    assert departed == ["A departed parent"], departed


@pytest.mark.django_db
def test_a_reaction_inside_the_set_is_not_an_entry_ticket(
    an_instance_that_predates_the_marker: Instance,
) -> None:
    """A reaction is evidence AGAINST and never evidence FOR.

    It is not authorship — which is why `_refuse_if_it_reaches_real_data` stopped refusing
    on one — so it cannot be the reason somebody's account is destroyed. It is also not
    what blocks the wipe, so selecting on it would buy nothing. One OUTSIDE still keeps
    them out, which the parametrized test above covers.
    """
    world = an_instance_that_predates_the_marker
    fixture_post = Post.objects.create(
        author=world.demo_member, pod=world.demo_pod, body="the fixture post"
    )
    user = User.objects.create_user(username="onlyreacted")
    person = Member.objects.create(display_name="A Reactor", user=user)
    PodMembership.objects.create(member=person, pod=world.demo_pod)
    Reaction.objects.create(post=fixture_post, member=person, kind=Reaction.HEART)
    removal.remove_member(person, content=removal.KEEP)

    _selected, _spared, departed = demo_marking.plan(
        yard_slugs=["maternal"], marker=MARKER, include_departed=True
    )
    assert departed == [], "a reaction inside the set bought somebody a deletion"

    # A REPLY inside the set is a ticket, so the distinction being drawn is authorship and
    # not "any row at all".
    Comment.objects.create(post=fixture_post, author=person, body="lovely")
    _selected, _spared, departed = demo_marking.plan(
        yard_slugs=["maternal"], marker=MARKER, include_departed=True
    )
    assert departed == ["A Reactor"], departed
