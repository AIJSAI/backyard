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

from django.db import transaction

from core.models import Member, Pod, Yard


class DemoMarkingError(RuntimeError):
    """Refused: the request would have marked something a real person depends on."""


def plan(*, yard_slugs: list[str], marker: str) -> tuple[dict[str, list[str]], list[str]]:
    """What would be marked, and why anything adjacent was left alone.

    Returns `(selected, spared)` — both human-readable, because the operator reads this on a
    terminal at the point of deciding, and a count alone does not let them recognise a name
    that should not be there.
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
            f"No yard with slug {missing}. Nothing was marked. Check `manage.py shell -c "
            "\"from core.models import Yard; print(list(Yard.objects.values_list('slug', "
            'flat=True)))"`.'
        )
    if not yards:
        raise DemoMarkingError("Name at least one yard with --yard.")

    yard_ids = {yard.pk for yard in yards}
    spared: list[str] = []

    pods: list[Pod] = []
    for pod in Pod.objects.filter(yards__in=yard_ids).distinct().prefetch_related("yards"):
        pod_yard_ids = {yard.pk for yard in pod.yards.all()}
        if pod_yard_ids <= yard_ids:
            pods.append(pod)
        else:
            outside = Yard.objects.filter(pk__in=pod_yard_ids - yard_ids)
            spared.append(
                f"pod {pod.name!r} — also in {', '.join(y.name for y in outside)}, which you "
                "did not name. Marking it would put that side's people in the blast radius."
            )

    pod_ids = {pod.pk for pod in pods}
    members: list[Member] = []
    for member in Member.objects.filter(pods__in=pod_ids).distinct().prefetch_related("pods"):
        member_pod_ids = {pod.pk for pod in member.pods.all()}
        if member_pod_ids <= pod_ids:
            members.append(member)
        else:
            spared.append(
                f"member {member.display_name!r} — also in "
                f"{Pod.objects.filter(pk__in=member_pod_ids - pod_ids).count()} household(s) "
                "outside this set, so they are a real person as far as this is concerned."
            )

    selected = {
        "Yard": sorted(yard.name for yard in yards),
        "Pod": sorted(pod.name for pod in pods),
        "Member": sorted(member.display_name for member in members),
    }
    return selected, spared


def apply(*, yard_slugs: list[str], marker: str) -> Counter[str]:
    """Stamp the marker. Atomic, and re-runnable: marking twice is not a second act."""
    marker = marker.strip()
    selected, _spared = plan(yard_slugs=yard_slugs, marker=marker)

    stamped: Counter[str] = Counter()
    with transaction.atomic():
        yards = Yard.objects.select_for_update().filter(slug__in=yard_slugs)
        yard_ids = set(yards.values_list("pk", flat=True))

        pod_ids = [
            pod.pk
            for pod in Pod.objects.filter(yards__in=yard_ids).distinct().prefetch_related("yards")
            if {yard.pk for yard in pod.yards.all()} <= yard_ids
        ]
        member_ids = [
            member.pk
            for member in Member.objects.filter(pods__in=pod_ids)
            .distinct()
            .prefetch_related("pods")
            if {pod.pk for pod in member.pods.all()} <= set(pod_ids)
        ]

        stamped["Yard"] = Yard.objects.filter(pk__in=yard_ids).update(seeded_by=marker)
        stamped["Pod"] = Pod.objects.filter(pk__in=pod_ids).update(seeded_by=marker)
        stamped["Member"] = Member.objects.filter(pk__in=member_ids).update(seeded_by=marker)

        # INSIDE the transaction, so raising actually rolls the marking back.
        #
        # The first version of this check sat after the `with` block and its message said
        # "the marking is inside a transaction that is now rolling back" — which was false,
        # because the write had already committed. A guard whose message describes a
        # rollback that did not happen is worse than no guard: it tells the operator the
        # instance is untouched at the moment it is not.
        #
        # The plan and the act are two reads of one rule. A silent disagreement between them
        # is the operator confirming a blast radius they were never shown.
        for model, names in selected.items():
            if stamped[model] != len(names):
                raise DemoMarkingError(
                    f"marked {stamped[model]} {model} rows but the preview showed "
                    f"{len(names)}. Something changed between the preview and the write. "
                    "Nothing has been deleted, and this marking is rolling back now."
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
