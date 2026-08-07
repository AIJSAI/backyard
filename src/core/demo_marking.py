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
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from django.db import transaction

from core.models import Member, Pod, Yard


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


def _select(*, yard_slugs: list[str], marker: str) -> tuple[Selection, list[str]]:
    """The rule, once. Returns the objects to mark and the reasons anything was spared.

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

    return Selection(yards=yards, pods=pods, members=members), spared


def plan(*, yard_slugs: list[str], marker: str) -> tuple[dict[str, list[str]], list[str]]:
    """What would be marked, and why anything adjacent was left alone.

    Both human-readable, because the operator reads this on a terminal at the point of
    deciding, and a count alone does not let them recognise a name that should not be there.
    """
    selection, spared = _select(yard_slugs=yard_slugs, marker=marker)
    return selection.names(), spared


def apply(*, yard_slugs: list[str], marker: str) -> Counter[str]:
    """Stamp the marker. Atomic, and re-runnable: marking twice is not a second act."""
    marker = marker.strip()
    previewed, _spared = _select(yard_slugs=yard_slugs, marker=marker)

    stamped: Counter[str] = Counter()
    with transaction.atomic():
        Yard.objects.select_for_update().filter(slug__in=yard_slugs).values_list("pk")
        # Re-selected under the lock. The comparison below is against IDENTITY, not counts:
        # a set that changes while keeping its size — one member swapping in for another
        # between the preview and the write — is exactly the case a count cannot see, and it
        # is the operator confirming a blast radius they were never shown.
        current, _ = _select(yard_slugs=yard_slugs, marker=marker)
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
    """
    marker = marker.strip()
    if not marker:
        raise DemoMarkingError("Refusing to unmark on a blank marker.")
    cleared: Counter[str] = Counter()
    with transaction.atomic():
        for model in (Yard, Pod, Member):
            cleared[model.__name__] = model.objects.filter(seeded_by=marker).update(seeded_by="")
    return +cleared
