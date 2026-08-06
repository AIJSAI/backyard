"""Removing fixture data (the demo family) without removing anybody's family.

This module exists because the thing it replaces was four lines in a script, and the second
of them was:

    Pod.objects.all().delete()

Unscoped. Every destructive cascade in this schema passes through `Pod` — posts, comments,
media, reactions, invites, memberships, mutes, weekly metrics — so on an instance holding
real content that line is a `TRUNCATE CASCADE` of the family's history. It was documented in
four places as the step to run immediately before the first real invite, had no test, no
confirmation, no dry run, and no guard beyond one environment variable. Two more edges:

* `Member.objects.exclude(user__username="james")` was keyed to a string literal. On an
  instance whose superuser is named anything else, nothing is excluded and every Member on
  the box is deleted — including the founder's, leaving a superuser with no Member and
  `/setup/` permanently closed (it is gated on `is_superuser`, not on an admin member).
  `exclude()` across a nullable relation also keeps NULL rows, so every real elder and every
  supervised child was inside the delete set by construction.
* `User.objects.filter(username__in=["priya", "sam", "dave"])` deletes auth accounts by
  first name. "sam" and "dave" are ordinary given names.

The fix is a marker, not a cleverer query. `Yard`, `Pod` and `Member` now carry `seeded_by`,
empty by default, so anything a real person made is un-wipeable by construction — it fails
closed. Everything here selects on that one field and nothing else.

Two properties this module owes the operator, neither of which the old wipe had:

1. **It says what it will do before it does it.** `preview()` runs Django's real deletion
   collector, so the counts are the actual closure and not a guess about which FKs cascade.
2. **It refuses rather than guesses.** If the collected closure reaches a `Yard`, `Pod` or
   `Member` that is NOT marked, something has linked real data to fixture data and this
   stops. That is the same shape as `backups.restore_backup`, which refuses a database that
   still holds members unless forced — the pattern was already in this repo, one directory
   over, and the wipe simply never used it.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models.deletion import Collector
from django.utils import timezone

from core import media
from core.models import MediaAsset, Member, Pod, Yard

# What `scripts/demo_seed.py` stamps on everything it creates. A different generator should
# use a different marker so the two can be removed independently.
SEED_MARKER = "demo"

# The three models that carry the marker. Everything else is reached by cascade from these.
_MARKED_MODELS = (Yard, Pod, Member)


class DemoDataError(RuntimeError):
    """Refused: the requested wipe would have reached something a real person made."""


def _collect(marker: str) -> dict[Any, list[Any]]:
    """The real deletion closure, from Django's own collector.

    Using the collector rather than a hand-written list of related models is deliberate:
    the hand-written version is exactly the artefact that goes stale when somebody adds a
    ForeignKey, and going stale here means silently deleting more than the operator was
    shown.

    Collected per root model, because `Collector.collect()` takes instances of ONE model
    per call — hand it a mixed list and it validates the second model's instances against
    the first model's options and raises. The results are merged, not the inputs.
    """
    grouped: dict[Any, list[Any]] = {}
    for model in _MARKED_MODELS:
        roots = list(model.objects.filter(seeded_by=marker))
        if not roots:
            continue
        collector: Collector = Collector(using="default")
        collector.collect(roots)
        for collected_model, instances in collector.data.items():
            seen = grouped.setdefault(collected_model, [])
            known = {instance.pk for instance in seen}
            seen.extend(instance for instance in instances if instance.pk not in known)
    return grouped


def _refuse_if_it_reaches_real_data(collected: dict[Any, list[Any]], marker: str) -> None:
    """No marked root may cascade into an unmarked yard, pod or member.

    Vacuous today — selection is by marker, so the closure cannot contain an unmarked root
    unless a future ForeignKey creates a path. That is precisely when it matters, and it is
    cheap: this is the check that turns "we believe it is scoped" into "it is scoped, and
    the build says so if that stops being true".
    """
    trespass: list[str] = []
    for model in _MARKED_MODELS:
        for instance in collected.get(model, []):
            if getattr(instance, "seeded_by", "") != marker:
                trespass.append(f"{model.__name__}(pk={instance.pk}, name={instance!s})")
    if trespass:
        raise DemoDataError(
            "Refusing to wipe: the deletion would reach objects that are not marked "
            f"`seeded_by={marker!r}`, i.e. things a real person made — "
            f"{', '.join(trespass[:10])}. Something has linked real data to fixture data; "
            "resolve that by hand rather than deleting through it."
        )


def _refuse_if_it_strands_anyone(collected: dict[Any, list[Any]], marker: str) -> None:
    """No surviving member may be left in zero pods.

    A member in no pod belongs to no yard, and `scoping` resolves nobody for them —
    including themselves. No feed, no directory, no route back: `/setup/` is closed once a
    superuser exists, Django admin is not mounted, `create_adhoc_pod` needs a yard they no
    longer have, and `join()` redirects an authenticated user without joining. The only way
    back is a shell, or a second account.

    This is the founder-lockout defect stated as an invariant rather than as a special case
    for one username. It fires whenever a real person's only pod is a fixture pod, which is
    a thing an operator can do by accident at any time — and the old wipe did it by design,
    to everyone.
    """
    doomed_pods = {pod.pk for pod in collected.get(Pod, [])}
    doomed_members = {member.pk for member in collected.get(Member, [])}
    if not doomed_pods:
        return
    stranded = [
        member
        for member in Member.objects.exclude(pk__in=doomed_members).prefetch_related("pods")
        if {pod.pk for pod in member.pods.all()} <= doomed_pods
    ]
    if stranded:
        names = ", ".join(f"{member.display_name} (pk={member.pk})" for member in stranded[:10])
        raise DemoDataError(
            f"Refusing to wipe: {names} would be left in no pod at all. A member in no pod "
            "belongs to no yard and resolves nobody, including themselves — no feed, no "
            "directory, and no self-service way back. Put them in a household of their own "
            f"first (one that is not marked `seeded_by={marker!r}`), then wipe."
        )


def preview(marker: str = SEED_MARKER) -> Counter[str]:
    """Rows that `wipe()` would delete, per model. Touches nothing."""
    collected = _collect(marker)
    _refuse_if_it_reaches_real_data(collected, marker)
    _refuse_if_it_strands_anyone(collected, marker)
    counts: Counter[str] = Counter()
    for model, instances in collected.items():
        counts[model._meta.label] = len(instances)
    counts["auth.User"] = _doomed_user_ids(marker).__len__()
    return +counts  # drop zero entries


def _doomed_user_ids(marker: str) -> list[int]:
    """Auth accounts belonging to marked members.

    `Member.user` is PROTECT on purpose (deleting the User looks like offboarding and
    revokes nothing), so these are deleted explicitly, after their members, rather than by
    cascade. Selected through the marked Member — never by username, which is how the old
    wipe came to delete real relatives called "sam" or "dave".
    """
    return list(
        Member.objects.filter(seeded_by=marker, user__isnull=False).values_list(
            "user_id", flat=True
        )
    )


def _purge_media_files(collected: dict[Any, list[Any]]) -> int:
    """Delete the FILES for every media asset in the closure, before the rows go.

    Without this the rows vanish and the bytes stay on `/data/media` forever: there is no
    `post_delete` signal on `MediaAsset` (`signals.py` has exactly one receiver, for
    logout), a queryset `.delete()` issues bulk SQL and never calls `Model.delete()`, and
    Django has not removed `FileField` files on model delete since 1.3. The result is
    unreachable (the serving token lived in the deleted row), unpurgeable (`_purge` needs
    the rows) and invisible to every audit — while `media.py` promises the opposite.
    """
    doomed = [asset.pk for asset in collected.get(MediaAsset, [])]
    if not doomed:
        return 0
    return media._purge(MediaAsset.objects.filter(pk__in=doomed))


def _delete_sessions(user_ids: list[int]) -> int:
    """Drop live sessions for the deleted accounts.

    The old wipe cleared none, so a deleted member's cookie kept authenticating against an
    orphaned `User` row. Same decode-and-scan as `revocation._revoke_sessions`: Django keys
    sessions by opaque key rather than by user, and at family scale a full scan is correct.
    """
    if not user_ids:
        return 0
    targets = {str(user_id) for user_id in user_ids}
    doomed = [
        session.session_key
        for session in Session.objects.filter(expire_date__gte=timezone.now())
        if session.get_decoded().get("_auth_user_id") in targets
    ]
    count, _ = Session.objects.filter(session_key__in=doomed).delete()
    return count


def wipe(marker: str = SEED_MARKER) -> Counter[str]:
    """Delete every object marked `seeded_by=marker`, and nothing else.

    Returns what was removed, per model, so the caller can print a receipt rather than
    "DEMO DATA WIPED" over an unknown blast radius.
    """
    collected = _collect(marker)
    _refuse_if_it_reaches_real_data(collected, marker)
    _refuse_if_it_strands_anyone(collected, marker)
    if not collected:
        return Counter()

    removed: Counter[str] = Counter()
    user_ids = _doomed_user_ids(marker)

    with transaction.atomic():
        # Files first, rows second. `_purge` defers the unlink to on_commit, so a rollback
        # cannot leave live rows pointing at deleted files.
        removed["files"] = _purge_media_files(collected)

        # Members before pods: `Member.user` is PROTECT, and posts/comments/media/reactions
        # reach their end either way. Each `.delete()` returns per-model counts, which is
        # the receipt.
        for model in (Member, Pod, Yard):
            _, per_model = model.objects.filter(seeded_by=marker).delete()
            removed.update(per_model)

        removed["sessions"] = _delete_sessions(user_ids)
        user_deleted, _ = get_user_model().objects.filter(pk__in=user_ids).delete()
        removed["auth.User"] = user_deleted

    return +removed
