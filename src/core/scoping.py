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
"""

from __future__ import annotations

from django.db import models
from django.http import Http404

from .models import Member, Pod, Yard


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


def require_visible_yard(member: Member, yard_id: int) -> Yard:
    """Return the yard if the member belongs to it, else the same 404 as an unknown
    route. `does not exist` and `exists but not yours` are byte-identical (S-202)."""
    try:
        return visible_yards(member).get(pk=yard_id)
    except Yard.DoesNotExist as exc:
        raise Http404 from exc


def require_visible_pod(member: Member, pod_id: int) -> Pod:
    """Return the pod if the member belongs to it, else a byte-identical 404."""
    try:
        return visible_pods(member).get(pk=pod_id)
    except Pod.DoesNotExist as exc:
        raise Http404 from exc


def require_visible_member(member: Member, target_id: int) -> Member:
    """Return the target member if they share a yard with this member, else a
    byte-identical 404. A member always shares a yard with themselves."""
    try:
        return visible_members(member).get(pk=target_id)
    except Member.DoesNotExist as exc:
        raise Http404 from exc
