"""The ad-hoc pod surface and quiet exits (S-204, S-205).

Every action resolves the pod through the guard first (require_visible_pod), so a
member can only act on a pod they belong to; owner-only actions are re-checked in
the pods service. Mute and leave are silent by construction: there is no
notification path, and mute is a per-member display flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from django.contrib import messages
from django.contrib.auth import BACKEND_SESSION_KEY, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from . import pods, scoping
from .feed_views import _acting_member
from .models import Member, Pod

_MODEL_BACKEND = "django.contrib.auth.backends.ModelBackend"


@dataclass
class PodRow:
    pod: Pod
    is_owner: bool
    is_muted: bool
    is_adhoc: bool


def _pod_list_response(request: HttpRequest, member: Member, refusal: str = "") -> HttpResponse:
    """Render the pod list, optionally with one sentence explaining a refused act.

    Extracted so a refused leave lands back on the page the member was already looking
    at, with the reason on it, rather than on an error page. `pods.PodLeaveRefused` is
    answerable — somebody has to put them in a household — and a 403 says nothing.
    """
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
            "refusal": refusal,
            "yards": scoping.visible_yards(member),
            "candidates": scoping.visible_members(member).exclude(id=member.id),
        },
    )


@login_required
def pod_list(request: HttpRequest) -> HttpResponse:
    """The member's pods: household and ad-hoc, with mute/leave and, for pods they
    own, the house rule and add-member controls."""
    return _pod_list_response(request, _acting_member(request))


@login_required
def pod_create(request: HttpRequest) -> HttpResponse:
    """Create an ad-hoc pod in a yard the member belongs to (S-204). POST only."""
    member = _acting_member(request)
    if request.method != "POST":
        raise Http404
    name = request.POST.get("name", "").strip()
    yard = scoping.require_visible_yard(member, _int(request.POST.get("yard_id", "")))
    if name:
        created = pods.create_adhoc_pod(
            owner=member, yard=yard, name=name, house_rule=request.POST.get("house_rule", "")
        )
        # R2-2. The same calm flash the composer uses. A new group lands part-way down a
        # page that already listed the member's households, so on a phone the only
        # evidence it worked was a row they had to go and find — and a member who did not
        # find it pressed Create again. The NAME is in the sentence for that reason: it is
        # what tells them the row they are looking at is the one they just made.
        messages.success(request, f"Group created: {created.name}.")
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
    try:
        pods.leave_pod(member=member, pod=pod)
    except pods.PodLeaveRefused as exc:
        return _pod_list_response(request, member, refusal=str(exc))
    # A leave that drops a side of the family runs the shrink registry, and its FIRST step
    # deletes every session belonging to this member — including this one, the one that
    # pressed the button. Without the re-login below, tapping "Leave" on a group logs you
    # out of your own family with no explanation, on the next page load, and the redirect
    # lands on the sign-in screen.
    #
    # Re-issuing THIS session is not a hole: `login()` cycles the session key, so the row
    # the registry deleted stays deleted, every OTHER device they were signed in on stays
    # signed out, and the elder link, digest links and reply addresses stay dead. What
    # survives is the browser of the person who is standing right there, whose credentials
    # were never the thing being revoked — they still belong here, with a narrower reach.
    #
    # The backend is read off the session before `login()` rewrites it, so a member who
    # signed in through allauth is re-issued through allauth rather than being silently
    # moved onto the model backend.
    # Read before the session dance below, not after: nothing here deletes the Pod row,
    # but the name is what the flash is about and taking it at the moment of the act is
    # what keeps the sentence true.
    left = pod.name
    backend = request.session.get(BACKEND_SESSION_KEY) or _MODEL_BACKEND
    # `cycle_key()` FIRST, and `login()` alone is not enough — measured. Django's `login`
    # only rotates the key when the request arrived with NO auth session; when the same
    # user is already signed in it leaves the key alone. The row behind that key has just
    # been deleted, so `SessionMiddleware` then tries to UPDATE a row that is gone and
    # raises SessionInterrupted: a 500 on the way out of a successful leave.
    #
    # `cycle_key` also keeps the session's DATA while replacing its identifier, which is
    # the behaviour this wants: a compose draft the member had in flight survives pressing
    # Leave, while the session row an attacker might hold does not.
    request.session.cycle_key()
    # `@login_required` above guarantees a real user here; the cast is for the type
    # checker, which only knows `request.user` as User | AnonymousUser.
    login(request, cast(User, request.user), backend=backend)
    # R2-2, and said AFTER the re-login so nothing in that sequence can drop it: a leave
    # is the quietest destructive act in the product — the row simply is not there any
    # more — and leaving a group you are in two of looks identical to a tap that did
    # nothing. `cycle_key` keeps the session's data, so a message set here survives.
    messages.success(request, f"You left {left}.")
    return redirect("pod_list")


def _int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise Http404 from None
