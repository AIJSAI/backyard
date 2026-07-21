"""The ad-hoc pod surface and quiet exits (S-204, S-205).

Every action resolves the pod through the guard first (require_visible_pod), so a
member can only act on a pod they belong to; owner-only actions are re-checked in
the pods service. Mute and leave are silent by construction: there is no
notification path, and mute is a per-member display flag.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from . import pods, scoping
from .feed_views import _acting_member
from .models import Pod


@dataclass
class PodRow:
    pod: Pod
    is_owner: bool
    is_muted: bool
    is_adhoc: bool


@login_required
def pod_list(request: HttpRequest) -> HttpResponse:
    """The member's pods: household and ad-hoc, with mute/leave and, for pods they
    own, the house rule and add-member controls."""
    member = _acting_member(request)
    muted = pods.muted_pod_ids(member)
    rows = [
        PodRow(
            pod=pod,
            is_owner=pod.owner_id == member.id,
            is_muted=pod.id in muted,
            is_adhoc=pod.kind == Pod.ADHOC,
        )
        for pod in scoping.visible_pods(member)
    ]
    return render(
        request,
        "core/pods.html",
        {
            "member": member,
            "rows": rows,
            "yards": scoping.visible_yards(member),
            "candidates": scoping.visible_members(member).exclude(id=member.id),
        },
    )


@login_required
def pod_create(request: HttpRequest) -> HttpResponse:
    """Create an ad-hoc pod in a yard the member belongs to (S-204). POST only."""
    member = _acting_member(request)
    if request.method != "POST":
        raise Http404
    name = request.POST.get("name", "").strip()
    yard = scoping.require_visible_yard(member, _int(request.POST.get("yard_id", "")))
    if name:
        pods.create_adhoc_pod(
            owner=member, yard=yard, name=name, house_rule=request.POST.get("house_rule", "")
        )
    return redirect("pod_list")


@login_required
def pod_add_member(request: HttpRequest, pod_id: int) -> HttpResponse:
    """Owner-only: add an existing member who shares the pod's yard (S-204)."""
    member = _acting_member(request)
    pod = scoping.require_visible_pod(member, pod_id)
    if request.method != "POST":
        raise Http404
    new_member = scoping.require_visible_member(member, _int(request.POST.get("member_id", "")))
    pods.add_member_to_pod(actor=member, pod=pod, new_member=new_member)
    return redirect("pod_list")


@login_required
def pod_house_rule(request: HttpRequest, pod_id: int) -> HttpResponse:
    """Owner-only: set the one-sentence house rule (S-204). POST only."""
    member = _acting_member(request)
    pod = scoping.require_visible_pod(member, pod_id)
    if request.method != "POST":
        raise Http404
    pods.set_house_rule(actor=member, pod=pod, house_rule=request.POST.get("house_rule", ""))
    return redirect("pod_list")


@login_required
def pod_mute(request: HttpRequest, pod_id: int) -> HttpResponse:
    """Toggle this member's mute of a pod (S-205). Silent to everyone else. POST only."""
    member = _acting_member(request)
    pod = scoping.require_visible_pod(member, pod_id)
    if request.method != "POST":
        raise Http404
    currently_muted = pod.id in pods.muted_pod_ids(member)
    pods.set_muted(member=member, pod=pod, muted=not currently_muted)
    return redirect("pod_list")


@login_required
def pod_leave(request: HttpRequest, pod_id: int) -> HttpResponse:
    """Leave a pod silently (S-205). POST only; no broadcast to remaining members."""
    member = _acting_member(request)
    pod = scoping.require_visible_pod(member, pod_id)
    if request.method != "POST":
        raise Http404
    pods.leave_pod(member=member, pod=pod)
    return redirect("pod_list")


def _int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise Http404 from None
