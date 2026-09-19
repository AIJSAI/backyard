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
   `Member` that is NOT marked, or a POST or REPLY a real person wrote, something has linked
   real data to fixture data and this stops. That is the same shape as
   `backups.restore_backup`, which refuses a database that still holds members unless
   forced — the pattern was already in this repo, one directory over, and the wipe simply
   never used it. A real person's REACTION on fixture content is the one deliberate
   exception: it goes with the post it is on and is COUNTED in the preview instead
   (`_refuse_if_it_reaches_real_data` says why, and `preview` names the line).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models.deletion import Collector
from django.utils import timezone

from core import media, pods
from core.models import Comment, MediaAsset, Member, Pod, Post, Reaction, Yard

# What `scripts/demo_seed.py` stamps on everything it creates. A different generator should
# use a different marker so the two can be removed independently.
SEED_MARKER = "demo"

# The three models that carry the marker. Everything else is reached by cascade from these.
_MARKED_MODELS = (Yard, Pod, Member)

# The one preview line that is not a model count. `_refuse_if_it_reaches_real_data` lets a
# real person's reaction through on purpose, so the dry run has to say how many are going —
# named here rather than spelled twice, because the refusal message points the operator at
# this exact line and the two drifting apart is how a receipt stops being readable.
REAL_REACTION_LABEL = "reactions by real people"

# The other preview line that is not a model count: posts and replies a real person wrote
# that were ALREADY deleted through the product before this wipe ran. They do not block
# (`_refuse_if_it_reaches_real_data` says why), so they have to be said out loud instead.
ALREADY_DELETED_LABEL = "already-deleted posts and replies by real people"


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

        # `collector.data` is NOT the closure. Django splits deletion in two: rows it must
        # instantiate, and rows it can remove with one bulk statement — the "fast deletes" —
        # which never appear in `.data` at all. Reading only `.data` made this module blind
        # to whole models. Measured on a fixture where a real relative had reacted to a
        # marked post:
        #
        #     preview() returned, NO refusal: {Yard: 1, Pod: 1, Post: 1, Member: 1}
        #     Reaction counted in preview: False
        #     wipe() receipt: {core.Reaction: 1, ...}
        #     real person's reactions AFTER: 0
        #
        # So the operator's dry run did not mention reactions, the checks above them could
        # not see them, and the receipt afterwards listed the row it had just destroyed.
        # `Reaction`, `PodMembership`, `PodMute`, `LinkPreview`, `ReplyAddress`,
        # `PodWeekMetrics` and both m2m through-tables are all fast-deleted. Materialising
        # them is affordable at family scale and is the only way the checks below see the
        # whole blast radius.
        #
        # Still load-bearing for `Reaction`, though it no longer refuses on one: the
        # `reactions by real people` line of the preview is counted off this list, so
        # reading `.data` alone would put the dry run back to saying nothing about a row it
        # is about to delete — which was the half of that measurement that mattered most.
        chunks: list[tuple[Any, list[Any]]] = [
            (collected_model, list(instances))
            for collected_model, instances in collector.data.items()
        ]
        chunks.extend((queryset.model, list(queryset)) for queryset in collector.fast_deletes)

        for collected_model, instances in chunks:
            seen = grouped.setdefault(collected_model, [])
            known = {instance.pk for instance in seen}
            seen.extend(instance for instance in instances if instance.pk not in known)
    return grouped


def _refuse_if_it_reaches_real_data(collected: dict[Any, list[Any]], marker: str) -> None:
    """Refuse if the wipe reaches an unmarked root, or anything a real person WROTE.

    Two halves. First: no marked root may cascade into an unmarked yard, pod or member.
    Vacuous today — selection is by marker, so the closure cannot contain an unmarked root
    unless a future ForeignKey creates a path. That is precisely when it matters, and it is
    cheap: this is the check that turns "we believe it is scoped" into "it is scoped, and
    the build says so if that stops being true".

    Second: no POST and no REPLY by a real person may go with it, wherever it sits. Those
    are somebody's words and somebody's photographs, their author can take them down from
    the feed, and this command will not decide for you which of them were a rehearsal.

    WHAT PROTECTS THE PHOTOGRAPHS, and it is worth naming because this guard never looks
    at a MediaAsset. It leans entirely on the S-404 constraint that an asset hangs off
    exactly one post or one comment — never free-standing, never shared between two — so a
    real person's photograph is always reachable through the post or the reply that
    carries it, and both of those ARE checked above. That is why removing `Reaction` from
    the authored tuple could not widen the blast radius to anybody's pictures: a reaction
    has no asset hanging off it. If that constraint ever loosens, this guard needs its own
    arm for MediaAsset, and this paragraph is the tripwire for whoever loosens it.

    What does NOT refuse, deliberately: a real person's REACTION on fixture content. It is
    deleted with the post it is on, and `preview()` counts it as "reactions by real people"
    so the dry run says the number before anybody types `--yes`. Three reasons:

    * It is not authorship. A reaction carries no words and no photographs — one row naming
      a member, a post and a kind — so the test this guard applies does not reach it.
    * It has no meaning once the fixture post is gone. There is no surviving object it could
      be moved to, kept beside, or exported with.
    * The refusal's own instruction could not be followed. It tells the operator to have the
      author remove their content from the feed first; a reaction is removable only from the
      screen of the post it is on, so once that post has been taken down there is no screen
      left on which that person could take theirs back — and the wipe would stay blocked by
      a row nobody can reach.

    This is narrower than it was, so it is worth being plain about the consequence: a real
    person's reaction inside the fixture family IS destroyed by this command. It is named in
    the dry run for exactly that reason.
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
    #
    # `Reaction` sat in this tuple until it was measured against the thing it was for: it
    # refused the whole wipe because somebody had tapped a heart on a FIXTURE post. It is
    # counted rather than refused now — `_reactions_by_real_people`, and the docstring above
    # for why a reaction is not authorship. A post and a reply are unchanged.
    doomed_members = {member.pk for member in collected.get(Member, [])}
    authored: tuple[tuple[Any, str, str], ...] = (
        (Post, "author_id", "post"),
        (Comment, "author_id", "reply"),
    )
    # A row that was ALREADY DELETED through the product is not something this wipe would
    # destroy: it is a tombstone. Measured on a live instance, 2026-09-19: the refusal told
    # the operator to "move or delete that content first (its author can, from the feed)",
    # the author did exactly that, and the wipe refused again on the same two posts — because
    # every delete in this product is a soft delete (`deleted_at`), this guard read the
    # unfiltered table, and so the cure it prescribed could never satisfy it. The only ways
    # left were a shell or abandoning the wipe.
    #
    # Every path that stamps `deleted_at` purges the photographs in the SAME transaction, so
    # no committed state holds a tombstone and its pictures: `commenting.delete_comment`,
    # `moderation.take_down_comment` and `removal._delete_content` purge in the SERVICE, while
    # the two POST paths purge one line later in the VIEW (`feed_views.delete_post` and
    # `feed_views.take_down_post` call `media.purge_post_media`, and ATOMIC_REQUESTS makes the
    # pair atomic) — so a future NON-VIEW caller of `posting.delete_post` or
    # `moderation.take_down_post` would stamp without purging. No reader can see a tombstone
    # (every query filters `deleted_at__isnull=True`) and the product has no restore. So the
    # tombstone is let through and COUNTED (`ALREADY_DELETED_LABEL`) — unless a media row
    # still hangs off it, in which case a path did not purge and the pictures are still real:
    # that one blocks exactly as a live post does. That condition is the backstop for the
    # view/service split above. Do not remove it, and do not "simplify" it away when the
    # purge moves.
    still_has_media = _rows_that_still_carry_media(collected)
    for authored_model, attribute, noun in authored:
        for instance in collected.get(authored_model, []):
            if (
                instance.deleted_at is not None
                and (authored_model, instance.pk) not in still_has_media
            ):
                continue
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
            "decide for you which of somebody's photographs were only a rehearsal. A post or "
            "reply that was ALREADY deleted through the product does not block, and the dry "
            f"run reports those as {ALREADY_DELETED_LABEL!r} — UNLESS it still carries a media "
            "row, which means some path stamped the deletion without purging the pictures. If "
            "a row named above is already deleted, that is what happened: it cannot be deleted "
            "a second time from the feed, so get the photographs off it (or take a backup and "
            "remove the row) rather than forcing the wipe.\n\n"
            "Reactions are not on this list and never block: a real person's reaction on "
            "fixture content is not words or photographs, it means nothing once the post it "
            "sits on is gone, and once that post is down there is no screen left on which "
            "they could remove it. It is deleted with the post, and the dry run reports it "
            f"as {REAL_REACTION_LABEL!r}."
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


def _rows_that_still_carry_media(collected: dict[Any, list[Any]]) -> set[tuple[Any, int]]:
    """(model, pk) of every post and reply in the closure that still has a media row.

    A soft-deleted row is only a tombstone if its photographs really went. Every delete path
    purges them, so this set is empty for a tombstone in practice; it exists so that a path
    which forgot to purge keeps a real person's pictures inside the refusal rather than
    inside the blast radius.
    """
    carrying: set[tuple[Any, int]] = set()
    for asset in collected.get(MediaAsset, []):
        if asset.post_id is not None:
            carrying.add((Post, asset.post_id))
        if asset.comment_id is not None:
            carrying.add((Comment, asset.comment_id))
    return carrying


def _already_deleted_by_real_people(collected: dict[Any, list[Any]]) -> list[Any]:
    """Tombstones in the closure whose author this wipe is NOT deleting.

    The rows `_refuse_if_it_reaches_real_data` lets through because they were deleted
    through the product before the wipe ran. Counted for the same reason real people's
    reactions are: a row that neither blocks nor appears anywhere is how a blast radius gets
    confirmed unseen.
    """
    doomed_members = {member.pk for member in collected.get(Member, [])}
    still_has_media = _rows_that_still_carry_media(collected)
    return [
        instance
        for model in (Post, Comment)
        for instance in collected.get(model, [])
        if instance.deleted_at is not None
        and instance.author_id not in doomed_members
        and (model, instance.pk) not in still_has_media
    ]


def _reactions_by_real_people(collected: dict[Any, list[Any]]) -> list[Any]:
    """Reactions in the closure left by somebody this wipe is NOT deleting.

    These are the rows `_refuse_if_it_reaches_real_data` deliberately does not refuse (its
    docstring says why), which is exactly why the number has to be said out loud: they are
    real people's rows, they are already inside the `core.Reaction` total where nothing
    distinguishes them, and the operator is reading the preview to decide whether to type
    `--yes`. A thing that neither blocks nor appears anywhere is how a blast radius gets
    confirmed unseen.

    The other direction is not one of these: a SEEDED member's reaction on a real person's
    post is collected too — through `Member` rather than through `Post` — and its author is
    going anyway, so it is fixture data leaving with the rest of the fixture data.
    """
    doomed_members = {member.pk for member in collected.get(Member, [])}
    return [
        reaction
        for reaction in collected.get(Reaction, [])
        if reaction.member_id not in doomed_members
    ]


def preview(marker: str = SEED_MARKER) -> Counter[str]:
    """Rows that `wipe()` would delete, per model. Touches nothing.

    Plus one line a model count cannot say: `reactions by real people`, which breaks the
    real people's reactions out of the `core.Reaction` total because they are the rows the
    refusal lets through rather than blocks.
    """
    marker = _require_a_real_marker(marker)
    collected = _collect(marker)
    _refuse_if_it_reaches_real_data(collected, marker)
    _refuse_if_it_strands_anyone(collected, marker)
    counts: Counter[str] = Counter()
    for model, instances in collected.items():
        counts[model._meta.label] = len(instances)
    counts["auth.User"] = _doomed_user_ids(marker).__len__()
    counts[REAL_REACTION_LABEL] = len(_reactions_by_real_people(collected))
    counts[ALREADY_DELETED_LABEL] = len(_already_deleted_by_real_people(collected))
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


def _files_behind(collected: dict[Any, list[Any]]) -> int:
    """How many FILES the media rows in the closure carry.

    `media._purge` returns the number of ASSETS it removed, which is its contract and is
    right for its other callers. The wipe's receipt labelled that number "files", and an
    asset carries up to four — image, thumbnail, source, video. Measured on a live rehearsal:
    the receipt said `4 files` while 8 left the disk.

    A receipt that undercounts by 2x is worse than one that omits the line: an operator
    reconciling what the command claims against what `du` says would conclude something else
    deleted the difference.
    """
    return sum(
        1
        for asset in collected.get(MediaAsset, [])
        for field in (asset.image, asset.thumbnail, asset.source, asset.video)
        if field.name
    )


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
    removed: Counter[str] = Counter()

    with transaction.atomic():
        # Collect and refuse INSIDE the transaction, and read the roots FOR UPDATE.
        #
        # Previously the closure was computed, checked, and then discarded: the delete below
        # re-queried `filter(seeded_by=marker)`, so what was inspected and what was destroyed
        # were two different reads. Anything created in between was deleted having been
        # checked by nothing — and for a photo that is not just an accounting gap, because
        # `_purge_media_files` works from the collected list, so its FILE stayed on disk
        # forever while its row vanished. That is the exact leak `_purge_media_files` exists
        # to prevent, reachable through the window rather than through the code path.
        #
        # A launch-day wipe on a live instance is precisely when somebody else may be
        # posting, so this window is not theoretical.
        for model in _MARKED_MODELS:
            # `flat=True`: the rows exist only to take the locks, so building 1-tuples is
            # work with no reader.
            list(
                model.objects.select_for_update()
                .filter(seeded_by=marker)
                .values_list("pk", flat=True)
            )
        collected = _collect(marker)
        _refuse_if_it_reaches_real_data(collected, marker)
        _refuse_if_it_strands_anyone(collected, marker)
        if not collected:
            return Counter()
        user_ids = _doomed_user_ids(marker)
        # The two lines the preview promised that are not model counts. A receipt that drops
        # them makes the dry run unreconcilable against what was actually destroyed.
        removed[REAL_REACTION_LABEL] = len(_reactions_by_real_people(collected))
        removed[ALREADY_DELETED_LABEL] = len(_already_deleted_by_real_people(collected))

        # Files first, rows second. `_purge` defers the unlink to on_commit, so a rollback
        # cannot leave live rows pointing at deleted files.
        # Both numbers, because they answer different questions and one was standing in for
        # the other. `core.MediaAsset` is counted HERE rather than falling out of the cascade
        # below: `_purge` deletes those rows itself, so by the time Member/Pod/Yard cascade
        # there are none left to report — and the preview, which reads the closure, promised
        # them. Measured on a live rehearsal: dry run said `4 core.MediaAsset`, the receipt
        # listed none at all.
        removed[MediaAsset._meta.label] = len(collected.get(MediaAsset, []))
        removed["files"] = _files_behind(collected)
        _purge_media_files(collected)

        # Which real ad-hoc pods a marked member owns, captured BEFORE the delete nulls
        # them. Afterwards there is no way to tell a pod this wipe orphaned from one that
        # was already ownerless.
        at_risk = list(
            Pod.objects.filter(
                kind=Pod.ADHOC, owner__seeded_by=marker, owner__isnull=False
            ).values_list("pk", flat=True)
        )

        # Members before pods: `Member.user` is PROTECT, and posts/comments/media/reactions
        # reach their end either way. Each `.delete()` returns per-model counts, which is
        # the receipt.
        for model in (Member, Pod, Yard):
            _, per_model = model.objects.filter(seeded_by=marker).delete()
            removed.update(per_model)

        # Ownership follows membership, here too. A seeded member may own a REAL ad-hoc
        # pod — the founder's book club, created by a fixture account during QA — and
        # `Pod.owner` is `SET_NULL`, so deleting them silently freezes that pod forever:
        # `pod.owner_id != actor.id` is the only gate on its house rule and member list, and
        # `None` never equals anybody. The receipt would not have mentioned it either, because
        # a field set to NULL is not a deletion and nothing counts it.
        #
        # Run AFTER the deletes, over the pods that survived, so succession sees the final
        # membership rather than one that is about to change.
        # Only the pods THIS wipe orphaned. Scanning every ownerless ad-hoc pod would
        # reassign ones that were already ownerless for unrelated reasons — mutating real
        # pods a demo wipe has no business touching, and inflating the receipt line the
        # operator reads to decide whether it did what they expected.
        removed["pods reassigned"] = sum(
            1
            for pod in Pod.objects.filter(pk__in=at_risk, owner__isnull=True)
            if pods.succeed_owner(pod) is not None
        )

        removed["sessions"] = _delete_sessions(user_ids)
        user_deleted, _ = get_user_model().objects.filter(pk__in=user_ids).delete()
        removed["auth.User"] = user_deleted

    return +removed
