"""The single authorization guard for yard isolation.

Every read of a scoped object routes through this module. It is deny-by-default:
a member sees only what their pod and yard membership grants, and anything else
returns the same 404 as a route that does not exist (S-202, TM-1, TM-2). There is
no second authorization path. ADR-004 makes this the one place audience is
resolved, so as later waves land, the feed, search, the digest builder, and the
token surface consume these functions rather than reimplementing the rule. A read
handler that does not pass through here is the bug the S-202 suite exists to catch.

Yard isolation reduces to one fact: a member's visible yards are the union of the
yards of every pod they belong to. The bridging household belongs to pods in two
yards and so sees both; every other member sees exactly one.

The traversal rule, which is where the leak actually lives (ADR-004's
_base_manager hazard, security-review HIGH-1): raw relation walks on model
instances are UNSCOPED. `some_member.pods.all()` and `some_pod.yards.all()` return
everything, including the far side of a bridge, because Django's related managers
never filter. A view may walk relations only on the requesting member's own
objects; for anyone and anything else it uses the visible_*_of accessors below,
which intersect the relation with the viewer's yards. Rendering a raw relation of
a non-self object is the bug class the traversal tests exist to catch.
"""

from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models import Q
from django.http import Http404

from .models import Member, Pod, Post, Yard


def member_yard_ids(member: Member) -> set[int]:
    """Every yard the member can see: the union of the yards of all their pods."""
    return set(Yard.objects.filter(pods__memberships__member=member).values_list("id", flat=True))


def member_pod_ids(member: Member) -> set[int]:
    """Every pod the member belongs to. Pod sight comes from membership, not yard."""
    return set(member.pod_memberships.values_list("pod_id", flat=True))


def visible_yards(member: Member) -> models.QuerySet[Yard]:
    """Yards the member belongs to, scoped for list endpoints."""
    return Yard.objects.filter(pods__memberships__member=member).distinct()


def visible_pods(member: Member) -> models.QuerySet[Pod]:
    """Pods the member belongs to. Pod content is private to its members; the yard
    feed is a separate surface, so a yard-mate who is not in an ad-hoc pod does not
    see it here (S-204)."""
    return Pod.objects.filter(memberships__member=member).distinct()


def visible_members(member: Member) -> models.QuerySet[Member]:
    """Members who share at least one yard with this member: the directory scope
    (S-902). A bridging member is visible from both yards; a cross-yard member is
    not visible at all."""
    return Member.objects.filter(pods__yards__id__in=member_yard_ids(member)).distinct()


def visible_posts(member: Member) -> models.QuerySet[Post]:
    """Every post a member may see, newest first (S-303): the pod-only posts of
    pods they belong to, plus the yard posts of yards they belong to, excluding
    deleted ones. This is the ONE audience-resolution query (TM-2): the feed, the
    digest, and search all consume it, so a post scoped to a yard the member is
    not in, or to another member's ad-hoc pod, never reaches them, and the rule
    cannot drift into a second implementation."""
    pod_only = Q(audience_yards__isnull=True, pod__memberships__member=member)
    in_my_yard = Q(audience_yards__pods__memberships__member=member)
    return Post.objects.filter(deleted_at__isnull=True).filter(pod_only | in_my_yard).distinct()


def require_visible_post(member: Member, post_id: int) -> Post:
    """Return the post if the member may see it, else a byte-identical 404 (S-202)."""
    return _require(visible_posts(member), post_id)


def visible_pods_of(viewer: Member, target: Member) -> models.QuerySet[Pod]:
    """The target's pods, seen through the viewer's yards: only pods that share a
    yard with the viewer. The safe form of `target.pods.all()`, which is unscoped
    and reveals a bridge member's far-side pods (the HIGH-1 traversal leak)."""
    return Pod.objects.filter(
        memberships__member=target, yards__id__in=member_yard_ids(viewer)
    ).distinct()


def visible_yards_of(viewer: Member, target: Member) -> models.QuerySet[Yard]:
    """The yards the viewer and target share: what a profile may say about where the
    target belongs. The safe form of walking target -> pods -> yards, which would
    reveal the far side of a bridge."""
    return (
        Yard.objects.filter(pods__memberships__member=target)
        .filter(id__in=member_yard_ids(viewer))
        .distinct()
    )


def visible_yards_of_pod(viewer: Member, pod: Pod) -> models.QuerySet[Yard]:
    """A pod's yards, restricted to the viewer's own: the safe form of
    `pod.yards.all()`. A bridge pod is legitimately visible in the viewer's yard,
    but its far-side yard must never render."""
    return pod.yards.filter(id__in=member_yard_ids(viewer)).distinct()


def _require[T: models.Model](queryset: models.QuerySet[T], pk: int) -> T:
    """Fetch by pk from an already-scoped queryset, or raise the byte-identical 404.

    Catches ValueError alongside DoesNotExist so a malformed id (a non-integer pk
    from a hand-built request) yields the same 404 as an unknown object, never a
    distinguishable 500 (S-202 parity)."""
    try:
        return queryset.get(pk=pk)
    except (ObjectDoesNotExist, ValueError) as exc:
        raise Http404 from exc


def require_visible_yard(member: Member, yard_id: int) -> Yard:
    """Return the yard if the member belongs to it, else the same 404 as an unknown
    route. `does not exist` and `exists but not yours` are byte-identical (S-202)."""
    return _require(visible_yards(member), yard_id)


def require_visible_pod(member: Member, pod_id: int) -> Pod:
    """Return the pod if the member belongs to it, else a byte-identical 404."""
    return _require(visible_pods(member), pod_id)


def require_visible_member(member: Member, target_id: int) -> Member:
    """Return the target member if they share a yard with this member, else a
    byte-identical 404. Self-visibility holds whenever the member belongs to at
    least one pod that is in a yard; a member in no pod resolves nobody, including
    themselves, which is deny-by-default working as intended."""
    return _require(visible_members(member), target_id)
