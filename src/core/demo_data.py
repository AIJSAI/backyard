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
from core.models import Comment, MediaAsset, Member, Pod, Post, Reaction, Yard

# What `scripts/demo_seed.py` stamps on everything it creates. A different generator should
# use a different marker so the two can be removed independently.
SEED_MARKER = "demo"

# The three models that carry the marker. Everything else is reached by cascade from these.
_MARKED_MODELS = (Yard, Pod, Member)


class DemoDataError(RuntimeError):
    """Refused: the requested wipe would have reached something a real person made."""


def _require_a_real_marker(marker: str) -> str:
    """A blank marker is the one value that must never be allowed through.

    `seeded_by` defaults to `""`, which is what EVERY row a real person creates carries.
    So `wipe("")` — or `--marker ""`, or `--marker "  "` — selects the entire family and
    deletes it. The scoped wipe would have shipped with the unscoped one hiding inside its
    own parameter, which is a worse version of the defect this module replaced: it looks
    safe at every call site and is armed by an empty string.

    Caught in review. It is the first thing every entry point does now.
    """
    cleaned = marker.strip()
    if not cleaned:
        raise DemoDataError(
            "Refusing to act on a blank marker. `seeded_by` is empty on everything a real "
            "person created, so a blank marker selects the whole family. Pass the marker "
            f"the seed stamps ({SEED_MARKER!r}), or the one your own generator uses."
        )
    return cleaned


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
    marker = _require_a_real_marker(marker)
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

    # The half that was missing, and it was the whole point.
    #
    # Checking only the three MARKED models cannot fire: selection is by marker, so the
    # closure never contains an unmarked root. Meanwhile the destruction travels through
    # `Post.pod`, `Comment.post`, `Reaction.post` and `MediaAsset.post` — none of which
    # carry a marker, none of which were inspected. A real person's posts and photographs
    # inside a fixture pod were deleted with no refusal and no distinguishable count.
    #
    # Measured before this fix, with a real relative in a fixture pod AND their own
    # household (so the stranding guard passed too): "wipe refused? False · their POST
    # survives: False · photo rows: 0 · comments: 0". That is somebody's holiday
    # photographs, gone, from a command whose entire job is not to do that.
    #
    # Authorship is the test, because it is the only thing that distinguishes real content
    # from fixture content: `Post` has no marker of its own, and giving it one would put a
    # column on the hottest table in the schema to answer a question its author already
    # answers.
    doomed_members = {member.pk for member in collected.get(Member, [])}
    authored: tuple[tuple[Any, str, str], ...] = (
        (Post, "author_id", "post"),
        (Comment, "author_id", "reply"),
        (Reaction, "member_id", "reaction"),
    )
    for authored_model, attribute, noun in authored:
        for instance in collected.get(authored_model, []):
            if getattr(instance, attribute) not in doomed_members:
                trespass.append(
                    f"a {noun} written by someone real ({authored_model.__name__} pk={instance.pk})"
                )

    if trespass:
        raise DemoDataError(
            "Refusing to wipe: the deletion would reach objects that are not marked "
            f"`seeded_by={marker!r}`, i.e. things a real person made — "
            f"{', '.join(trespass[:10])}.\n\nSomething real is living inside the fixture "
            "family — most often because a person posted into a demo pod. Move or delete "
            "that content first (its author can, from the feed); this command will not "
            "decide for you which of somebody's photographs were only a rehearsal."
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
    doomed_yards = {yard.pk for yard in collected.get(Yard, [])}
    if not doomed_pods and not doomed_yards:
        return

    stranded = []
    # Loads every member at family scale, which is the right trade for a check that runs
    # once, before something irreversible.
    for member in Member.objects.exclude(pk__in=doomed_members).prefetch_related("pods__yards"):
        pods = list(member.pods.all())
        if not pods:
            # Already in no pod before this wipe — `removal.remove_member` deletes
            # memberships and KEEPS the Member row by design, so every person ever removed
            # through the S-702 flow looks stranded here. `set() <= anything` is True, so
            # the first version of this check blocked every future wipe permanently on the
            # strength of one departed ex — and told the operator to "put them in a
            # household of their own first", which would hand a removed person their yard
            # visibility back. This wipe is not what stranded them.
            continue
        surviving_pods = [pod for pod in pods if pod.pk not in doomed_pods]
        if not surviving_pods:
            stranded.append(member)
            continue
        # A pod survives, but its YARDS may not. Yard membership is derived — it is the
        # union of the yards of a member's pods (`scoping.member_yard_ids`) — so deleting a
        # fixture yard leaves a real household attached to nothing and its members
        # resolving nobody, including themselves. Reachable today: `invite_household` lets
        # an admin put a real household into a demo yard. Measured before this fix: yards
        # `set()`, and `visible_members(reed).filter(pk=reed.pk)` empty.
        surviving_yards = {
            yard.pk
            for pod in surviving_pods
            for yard in pod.yards.all()
            if yard.pk not in doomed_yards
        }
        if not surviving_yards:
            stranded.append(member)

    if stranded:
        names = ", ".join(f"{member.display_name} (pk={member.pk})" for member in stranded[:10])
        raise DemoDataError(
            f"Refusing to wipe: {names} would be left in no pod at all. A member in no pod "
            "belongs to no yard and resolves nobody, including themselves — no feed, no "
            "directory, and no self-service way back. Give them a household (and a side of "
            f"the family) that is not marked `seeded_by={marker!r}`, then wipe. Members who "
            "were ALREADY in no pod — anyone removed through the S-702 flow — are not "
            "counted here; this wipe is not what stranded them."
        )


def preview(marker: str = SEED_MARKER) -> Counter[str]:
    """Rows that `wipe()` would delete, per model. Touches nothing."""
    marker = _require_a_real_marker(marker)
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
    marker = _require_a_real_marker(marker)
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
