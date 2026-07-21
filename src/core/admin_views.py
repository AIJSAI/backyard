"""Instance-admin member management (S-701 enforced, S-703 supervised, S-702 UI).

The surface where an admin sees the family's members and administers them. Every
action routes through the write-authorization model (core/permissions.py) and the
read-scoping guard (core/scoping.py), so a yard admin sees and acts on only their
own yards' members, and a supervised child is administered only by its parent or
the instance admin.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from . import permissions, scoping, supervised
from .models import DigestDelivery, DigestSubscription, InboundQuarantine, Member
from .removal import remove_member


def _acting_member(request: HttpRequest) -> Member:
    """The Member behind the logged-in user, or 404. A user with no Member (should
    not happen for real accounts) has no management surface. The explicit pk guard
    matters: filtering on a None pk would otherwise match a user-less supervised
    member, so an anonymous request must never reach the query (login_required
    already blocks it; this is defense in depth and narrows the type)."""
    if not request.user.is_authenticated or request.user.pk is None:
        raise Http404
    member = Member.objects.filter(user_id=request.user.pk).first()
    if member is None:
        raise Http404
    return member


def _int_or_404(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise Http404 from exc


@login_required
def members(request: HttpRequest) -> HttpResponse:
    """Roster of members the actor can see, supervised ones flagged. Admins only."""
    actor = _acting_member(request)
    if not permissions.is_admin(actor):
        raise PermissionDenied
    visible = scoping.visible_members(actor).order_by("display_name")
    manageable_ids = {m.id for m in visible if permissions.can_manage_member(actor, m)}
    return render(
        request,
        "core/members.html",
        {"actor": actor, "members": visible, "manageable_ids": manageable_ids},
    )


@dataclass
class DigestRow:
    """One member's digest state plus their newest delivery records, as typed
    values for the template (the FeedItem pattern)."""

    subscription: DigestSubscription
    deliveries: list[DigestDelivery]


@login_required
def digests(request: HttpRequest) -> HttpResponse:
    """Per-member digest delivery status and failures (S-501). Admins only, and
    scoped exactly like the roster: a yard admin sees only their own yards'
    members, so a cross-yard subscription is simply absent (S-202). Statuses are
    transport-level truth only until the ADR-002 delivery matrix is measured;
    bounces only ever surface here, nothing auto-suppresses (T-EMAIL-6)."""
    actor = _acting_member(request)
    if not permissions.is_admin(actor):
        raise PermissionDenied
    visible_ids = set(scoping.visible_members(actor).values_list("id", flat=True))
    # Deliveries are yard-scoped too, not just member-scoped (security review of
    # #35 MEDIUM-1): a bridge member has issues in both yards, and a yard-A admin
    # must never see the yard-B ones' existence, timing, or failure detail.
    actor_yard_ids = scoping.member_yard_ids(actor)
    subscriptions = (
        DigestSubscription.objects.filter(member_id__in=visible_ids)
        .select_related("member")
        .order_by("member__display_name")
    )
    rows = [
        DigestRow(
            subscription=subscription,
            deliveries=list(
                DigestDelivery.objects.filter(
                    issue__member_id=subscription.member_id,
                    issue__yard_id__in=actor_yard_ids,
                ).order_by("-created_at")[:5]
            ),
        )
        for subscription in subscriptions
    ]
    return render(request, "core/members_digests.html", {"actor": actor, "rows": rows})


@login_required
def quarantine(request: HttpRequest) -> HttpResponse:
    """Inbound mail held for review (S-502). Instance admin ONLY: quarantine
    rows hold email content that predates attribution, so no yard scoping can
    apply and nobody below the instance admin sees it (T-OP-G2). POST with a
    row id deletes it (handled = gone; rows never accumulate)."""
    actor = _acting_member(request)
    if not permissions.is_instance_admin(actor):
        raise PermissionDenied
    if request.method == "POST":
        InboundQuarantine.objects.filter(pk=_int_or_404(request.POST.get("row_id", ""))).delete()
        return redirect("member_quarantine")
    rows = InboundQuarantine.objects.select_related("member")[:100]
    return render(request, "core/members_quarantine.html", {"actor": actor, "rows": rows})


@login_required
def create_supervised(request: HttpRequest) -> HttpResponse:
    """Create a supervised child under a parent (S-703). The actor must be allowed
    to create a supervised account for that parent, and must be able to see the pod."""
    actor = _acting_member(request)
    if request.method != "POST":
        raise Http404
    parent = scoping.require_visible_member(actor, _int_or_404(request.POST.get("parent_id", "")))
    if not permissions.can_create_supervised(actor, parent):
        raise PermissionDenied
    pod = scoping.require_visible_pod(actor, _int_or_404(request.POST.get("pod_id", "")))
    display_name = request.POST.get("display_name", "").strip()
    if display_name and len(display_name) <= 100:
        supervised.create_supervised_member(parent=parent, display_name=display_name, pod=pod)
    return redirect("members")


@login_required
def remove(request: HttpRequest, member_id: int) -> HttpResponse:
    """Remove a member (S-702 UI). Permission-gated, then wired to the atomic
    revocation-and-teardown flow."""
    actor = _acting_member(request)
    if request.method != "POST":
        raise Http404
    # require_visible_member 404s cross-scope, so a target the actor cannot even see
    # is indistinguishable from one that does not exist.
    target = scoping.require_visible_member(actor, member_id)
    permissions.require_can_manage_member(actor, target)  # raises PermissionDenied
    remove_member(target)
    return redirect("members")
