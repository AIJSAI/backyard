"""Stamping the marker onto fixture data that predates the marker.

`demo_data.wipe()` only ever touches rows whose `seeded_by` matches. That is what makes it
safe, and it is also why it does nothing at all on the one instance that most needs it: the
live box was seeded before `seeded_by` existed, so its demo family carries an empty marker —
which is the same value every real person carries, and correctly un-wipeable.

The remaining options were to delete those rows by hand at a shell, or to give the wipe a
way to select unmarked data. The second is the defect this module's neighbour exists to
prevent. The first is how `Pod.objects.all().delete()` came to be written in the first
place: a one-off snippet, typed once, against production, with nothing watching.

So: mark first, then wipe. Marking is reversible, previewable, and routes the actual
deletion through every refusal `demo_data` already has — the real-content check, the
stranding check, media purging, session deletion, pod-owner succession. None of which a
hand-written `.delete()` would have done.

**Selection is by CONTAINMENT, not by name.** You name yards. A pod is marked only if EVERY
yard it belongs to is one you named, and a member only if EVERY pod they belong to is one
that was marked. So:

* a bridging household spanning a demo yard and a real yard is NOT marked — it reaches real
  people, and marking it would put them in the blast radius;
* a real relative who joined a demo pod during QA but also has their own household is NOT
  marked, because one of their pods is outside the set;
* a demo member is marked only when every pod they are in is going anyway.

That rule is the same shape as `_refuse_if_it_strands_anyone`, one step earlier: instead of
refusing a wipe that would strand somebody, it declines to mark them in the first place.

**THE ONE THING CONTAINMENT CANNOT SEE: a member who was REMOVED.** `removal.remove_member`
deletes every `PodMembership` and KEEPS the Member row, by design, so their writing stays
attributable. Such a person is in no pod at all, so `filter(pods__in=pod_ids)` never returns
them and no containment rule can ever mark them — while their posts sit in a fixture
household ("keep their posts" and "remove their name" both keep `author_id`). The wipe then
refuses forever with "a post written by someone real", and the only cure was a shell, which
is the thing this module exists to avoid. Measured on the live instance, 2026-09-19.

`--include-departed` is the narrow answer, and it is opt-in because it is the one selection
rule not answerable from the household graph. A departed member joins the set only when ALL
THREE hold, and each one is there for a different reason:

1. **They are in no household and no group anywhere.** The state `remove_member` leaves, and
   one no ordinary member is ever in. This is what keeps the candidate set small.

2. **At least one POST or REPLY of theirs is INSIDE the households being marked.** This is
   the ENTRY TICKET, and the first version of this rule did not have one: it asked only that
   nothing of theirs sat outside, which a person who never wrote anything passes vacuously.
   Measured in review: a real relative removed from a REAL household on a side this run did
   not name — or an account created and never placed — was selected, and the wipe then
   deleted their Member row AND their auth account, under a heading telling the operator
   that everything they ever wrote was fixture data. It also bought nothing, because the
   only rows that block the wipe are a post or a reply inside the closure. So the ticket is
   exactly the thing the flag exists to clear, and nobody else is reachable by it.

   A REACTION is evidence AGAINST and never evidence FOR. It is not authorship — that is
   why `_refuse_if_it_reaches_real_data` stopped refusing on one — so it cannot be the
   reason somebody is deleted; but one outside the set still says this person has a life
   beyond the fixture family, which is the question condition 3 asks.

3. **Nothing of theirs sits anywhere else, and no supervised child of theirs is staying.**
   One post, reply or reaction outside the marked households — soft-deleted rows included,
   because the wipe's own guard reads the same unfiltered table — and they are never
   selected. Nor is anybody who is `managing_parent` of a supervised member the marking is
   leaving behind: that field is SET_NULL, so deleting the parent would quietly orphan a
   real child, and the preview would say nothing about it.

Without the flag, a member who meets all three is LISTED as deliberately not marked, with
the reason, so the operator learns the flag exists at the moment it would have helped rather
than after the wipe has refused. Anybody who does NOT meet them is not listed at all —
naming them would teach the operator a flag that would not have helped.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from django.db import transaction

from core.models import Comment, Member, Pod, Post, Reaction, Yard


@dataclass(frozen=True)
class Selection:
    """What a marking run would touch, by object rather than by count."""

    yards: list[Yard]
    pods: list[Pod]
    members: list[Member]

    def ids(self) -> dict[str, set[int]]:
        return {
            "Yard": {y.pk for y in self.yards},
            "Pod": {p.pk for p in self.pods},
            "Member": {m.pk for m in self.members},
        }

    def names(self) -> dict[str, list[str]]:
        return {
            "Yard": sorted(y.name for y in self.yards),
            "Pod": sorted(p.name for p in self.pods),
            "Member": sorted(m.display_name for m in self.members),
        }

    def difference_from(self, other: Selection) -> str:
        """A human sentence about how two selections differ, for the refusal message."""
        parts = []
        mine, theirs = self.ids(), other.ids()
        for model in ("Yard", "Pod", "Member"):
            added, gone = mine[model] - theirs[model], theirs[model] - mine[model]
            if added:
                parts.append(f"{len(added)} {model}(s) appeared")
            if gone:
                parts.append(f"{len(gone)} {model}(s) vanished")
        return "; ".join(parts) or "same ids, different objects"


class DemoMarkingError(RuntimeError):
    """Refused: the request would have marked something a real person depends on."""


def _departed_with_a_footprint_only_inside(pod_ids: set[int]) -> list[Member]:
    """Members in no pod who wrote INSIDE `pod_ids`, nowhere else, and orphan no child.

    The three conditions of the `--include-departed` rule, and nothing else. The module
    docstring argues each one; what is worth having here is why the ENTRY TICKET is a post
    or a reply and not "no footprint outside".

    THE FIRST VERSION ASKED ONLY THAT NOTHING SAT OUTSIDE, which a person who never wrote
    anything passes vacuously. Measured in review: a real relative removed from a REAL
    household on a side this run did not name — or an account created and never placed —
    came out selected, and the wipe then deleted their Member row AND their auth account,
    under a heading telling the operator everything they ever wrote was fixture data. It
    also bought nothing: the only rows that block the wipe are a post or a reply inside the
    closure (`_refuse_if_it_reaches_real_data`). So the ticket is exactly the obstruction
    this flag exists to clear, and nobody else is reachable by it.

    A REACTION IS EVIDENCE AGAINST AND NEVER EVIDENCE FOR. It is not authorship — that is
    why the wipe stopped refusing on one — so it must not be the reason a person is
    deleted; but one OUTSIDE still says this person has a life beyond the fixture family.

    SOFT-DELETED ROWS COUNT as a footprint. `removal` with "delete their posts" stamps
    `deleted_at` and leaves the row, so a post the family can no longer see is still
    evidence of WHERE somebody wrote: outside the set it keeps them safe, inside it is the
    proof that they were part of the fixture family. (The wipe's own guard no longer blocks
    on a tombstone — see `demo_data._refuse_if_it_reaches_real_data` — but where a person
    wrote does not change because they later deleted it.)

    A SUPERVISED CHILD WHO IS STAYING vetoes their parent. `Member.managing_parent` is
    SET_NULL, so deleting the parent would leave a real child with nobody recorded as
    looking after them, and nothing in the preview or the receipt would mention it.

    Five queries for the whole candidate set, not five per candidate: this runs inside the
    output an operator reads before an irreversible step, and `plan()` has a test that its
    query count does not grow with the size of the list it is printing.
    """
    candidates = list(Member.objects.filter(pods__isnull=True))
    if not candidates:
        return []
    candidate_ids = {member.pk for member in candidates}

    # `exclude(... __in=pod_ids)` with an EMPTY pod_ids excludes nothing, so every row
    # counts as outside — which is the correct answer when no household was marked. The
    # matching `filter(... __in=pod_ids)` returns nothing, so nobody earns a ticket either.
    outside: set[int] = set()
    outside.update(
        Post.objects.filter(author_id__in=candidate_ids)
        .exclude(pod_id__in=pod_ids)
        .values_list("author_id", flat=True)
    )
    outside.update(
        Comment.objects.filter(author_id__in=candidate_ids)
        .exclude(post__pod_id__in=pod_ids)
        .values_list("author_id", flat=True)
    )
    outside.update(
        Reaction.objects.filter(member_id__in=candidate_ids)
        .exclude(post__pod_id__in=pod_ids)
        .values_list("member_id", flat=True)
    )

    inside: set[int] = set()
    inside.update(
        Post.objects.filter(author_id__in=candidate_ids, pod_id__in=pod_ids).values_list(
            "author_id", flat=True
        )
    )
    inside.update(
        Comment.objects.filter(author_id__in=candidate_ids, post__pod_id__in=pod_ids).values_list(
            "author_id", flat=True
        )
    )

    # A supervised child the marking is NOT taking. `supervised_members` is the reverse of
    # `managing_parent`; the child is safe only if they are inside a household being marked,
    # which is the same containment test the rest of this module applies.
    keeps_a_child = set(
        Member.objects.filter(managing_parent_id__in=candidate_ids)
        .exclude(pods__id__in=pod_ids)
        .values_list("managing_parent_id", flat=True)
    )

    return [
        member
        for member in candidates
        if member.pk in inside and member.pk not in outside and member.pk not in keeps_a_child
    ]


def _select(
    *, yard_slugs: list[str], marker: str, include_departed: bool = False
) -> tuple[Selection, list[str], list[Member]]:
    """The rule, once. Returns the objects to mark, the reasons anything was spared, and
    the departed members inside the selection.

    `plan()` formats this for a terminal and `apply()` stamps it, so there is exactly one
    implementation of "what gets marked" — two readers of one rule drift, and the one inside
    the writer is the one that drifts toward marking more.
    """
    marker = marker.strip()
    if not marker:
        raise DemoMarkingError(
            "Refusing to mark with a blank marker: `seeded_by` is empty on everything a real "
            "person created, so a blank marker would make the whole family wipeable."
        )

    yards = list(Yard.objects.filter(slug__in=yard_slugs))
    missing = sorted(set(yard_slugs) - {yard.slug for yard in yards})
    if missing:
        raise DemoMarkingError(
            f"No yard with slug {missing}. Nothing was marked. List them with "
            '`manage.py shell -c "from core.models import Yard; '
            "print(list(Yard.objects.values_list('slug', flat=True)))\"`."
        )
    if not yards:
        raise DemoMarkingError("Name at least one yard with --yard.")

    yard_ids = {yard.pk for yard in yards}
    spared: list[str] = []

    # Prefetched, and the spared reasons are built from the PREFETCHED objects rather than
    # from a fresh query per item. The first version issued one `Yard.objects.filter(...)`
    # and one `Pod.objects.count()` per spared row — an N+1 in an operator-facing command
    # whose whole job is to be read before a destructive step.
    pods: list[Pod] = []
    candidate_pods = list(
        Pod.objects.filter(yards__in=yard_ids).distinct().prefetch_related("yards")
    )
    for pod in candidate_pods:
        pod_yards = list(pod.yards.all())
        outside = [yard for yard in pod_yards if yard.pk not in yard_ids]
        if not outside:
            pods.append(pod)
        else:
            spared.append(
                f"pod {pod.name!r} — also in {', '.join(y.name for y in outside)}, which you "
                "did not name. Marking it would put that side's people in the blast radius."
            )

    pod_ids = {pod.pk for pod in pods}
    members: list[Member] = []
    for member in Member.objects.filter(pods__in=pod_ids).distinct().prefetch_related("pods"):
        member_pods = list(member.pods.all())
        outside_pods = [pod for pod in member_pods if pod.pk not in pod_ids]
        if not outside_pods:
            members.append(member)
        else:
            spared.append(
                f"member {member.display_name!r} — also in "
                f"{len(outside_pods)} household(s) outside this set "
                f"({', '.join(p.name for p in outside_pods[:3])}"
                f"{'…' if len(outside_pods) > 3 else ''}), so they are a real person as far "
                "as this is concerned."
            )

    # The people containment cannot reach: removed, therefore in no pod, therefore never
    # returned by the query above — while their posts sit in a household it is about to
    # mark, where they are what stops the wipe. Selected only behind the flag, and only on
    # all three conditions; the module docstring argues each one.
    departed = _departed_with_a_footprint_only_inside(pod_ids)
    if include_departed:
        members.extend(departed)
    else:
        for member in departed:
            # ONLY the people the flag would have helped are listed. Somebody in no pod who
            # wrote nothing is not on this list, because the flag would not select them
            # either — naming them here would teach the operator a cure for a problem they
            # do not have, on the one screen they read before something irreversible.
            spared.append(
                f"member {member.display_name!r} — already removed (in no household or "
                "group), and what they wrote is inside the households above and nowhere "
                "else. They will NOT be marked, so `wipe_demo_data` will refuse on their "
                "posts; pass --include-departed to mark them too, which deletes their "
                "Member row and their sign-in account."
            )
        departed = []

    # Nothing may be re-stamped from ANOTHER marker. `demo_data` promises that different
    # generators can be removed independently — "a different generator should use a different
    # marker so the two can be removed independently" — and silently overwriting one with
    # another breaks exactly that, by making somebody else's fixture set wipeable under a
    # marker they did not choose. Refused rather than spared, because a partial mark leaves
    # the operator holding a set they did not preview.
    already = [
        f"{obj._meta.model.__name__} {obj!s} carries marker {obj.seeded_by!r}"
        for group in (yards, pods, members)
        for obj in group
        if obj.seeded_by and obj.seeded_by != marker
    ]
    if already:
        raise DemoMarkingError(
            "Refusing to re-stamp rows that already carry a DIFFERENT marker:\n  "
            + "\n  ".join(already)
            + f"\n\nMarking them {marker!r} would make another generator's fixtures "
            "removable by this marker and not by their own. Clear the other marker first "
            "(`mark_demo_data --marker <theirs> --undo --yes`) if that is really what you "
            "want, or name different yards."
        )

    return Selection(yards=yards, pods=pods, members=members), spared, departed


def plan(
    *, yard_slugs: list[str], marker: str, include_departed: bool = False
) -> tuple[dict[str, list[str]], list[str], list[str]]:
    """What would be marked, why anything adjacent was left alone, and which of the marked
    members are there because they were already removed.

    All three human-readable, because the operator reads this on a terminal at the point of
    deciding, and a count alone does not let them recognise a name that should not be there.
    The departed are named on their own as well as inside the member list: they are the one
    group selected by a rule the household graph cannot show, so the operator has to be able
    to read that group by itself.
    """
    selection, spared, departed = _select(
        yard_slugs=yard_slugs, marker=marker, include_departed=include_departed
    )
    return selection.names(), spared, sorted(member.display_name for member in departed)


def apply(*, yard_slugs: list[str], marker: str, include_departed: bool = False) -> Counter[str]:
    """Stamp the marker. Atomic, and re-runnable: marking twice is not a second act."""
    marker = marker.strip()
    previewed, _spared, _departed = _select(
        yard_slugs=yard_slugs, marker=marker, include_departed=include_departed
    )

    stamped: Counter[str] = Counter()
    with transaction.atomic():
        Yard.objects.select_for_update().filter(slug__in=yard_slugs).values_list("pk")
        # Re-selected under the lock. The comparison below is against IDENTITY, not counts:
        # a set that changes while keeping its size — one member swapping in for another
        # between the preview and the write — is exactly the case a count cannot see, and it
        # is the operator confirming a blast radius they were never shown.
        current, _, _ = _select(
            yard_slugs=yard_slugs, marker=marker, include_departed=include_departed
        )
        if current.ids() != previewed.ids():
            raise DemoMarkingError(
                "The set changed between the preview and the write:\n"
                f"  {current.difference_from(previewed)}\n"
                "Nothing has been deleted, and this marking is rolling back now. Re-run the "
                "dry run and read it again."
            )

        stamped["Yard"] = Yard.objects.filter(pk__in=current.ids()["Yard"]).update(seeded_by=marker)
        stamped["Pod"] = Pod.objects.filter(pk__in=current.ids()["Pod"]).update(seeded_by=marker)
        stamped["Member"] = Member.objects.filter(pk__in=current.ids()["Member"]).update(
            seeded_by=marker
        )
    return +stamped


def unmark(*, marker: str) -> Counter[str]:
    """Take the marker back off. The reason marking is safe to try.

    Not a formality: an operator who marks the wrong yard needs a way back that is not
    another hand-written UPDATE, and needs it before they run the wipe rather than after.

    Selects on the MARKER and on nothing else, which is why a departed member marked by
    `--include-departed` is cleared by a plain `--undo` like any other row: there is one
    way back and it does not need to know which rule put a row into the set.
    """
    marker = marker.strip()
    if not marker:
        raise DemoMarkingError("Refusing to unmark on a blank marker.")
    cleared: Counter[str] = Counter()
    with transaction.atomic():
        for model in (Yard, Pod, Member):
            cleared[model.__name__] = model.objects.filter(seeded_by=marker).update(seeded_by="")
    return +cleared
