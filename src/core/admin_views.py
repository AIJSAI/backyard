"""Instance-admin member management (S-701 enforced, S-703 supervised, S-702 UI).

The surface where an admin sees the family's members and administers them. Every
action routes through the write-authorization model (core/permissions.py) and the
read-scoping guard (core/scoping.py), so a yard admin sees and acts on only their
own yards' members, and a supervised child is administered only by its parent or
the instance admin.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import BadRequest, PermissionDenied
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from . import handover, invites, permissions, removal, scoping, supervised
from .models import (
    DigestDelivery,
    DigestSubscription,
    InboundQuarantine,
    Invite,
    Member,
    Pod,
    Yard,
    YardWeekMetrics,
)
from .removal import remove_member
from .views import _unique_yard_slug

# The roles the roster's appoint control may set (S-707). SUPERVISED is deliberately
# absent: a supervised child is a created state (create_supervised), not a role a member
# is promoted into, and unsupervising is a different, parent-scoped act. Authority is
# still decided per (actor, target, role) by permissions.can_assign_role; this list only
# bounds which roles the UI ever offers, so a role string outside it is never honored.
#
# POD_OWNER is deliberately absent too, and for a sharper reason: it grants NOTHING. No
# authorization predicate in `permissions.py` reads it, so a member promoted to it is
# permission-identical to a plain member — while the roster's own copy promised them a
# house rule and invites. It is the role a delegate is most likely to hand out, and the
# 2026-07-22 retro had already ruled "Activate pod_owner? No." The constant stays for rows
# that already carry it; the roster stops offering an appointment that does nothing.
_ASSIGNABLE_ROLES: tuple[str, ...] = (
    Member.MEMBER,
    Member.YARD_ADMIN,
    Member.INSTANCE_ADMIN,
)


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


@dataclass
class RosterRow:
    """One roster line: the member, whether the actor may administer them, and the
    roles the actor may set on them (S-707). assignable_roles is empty for a member the
    actor cannot manage, for a supervised child, and for the member's current role, so
    the appoint control only ever offers a real, authorized change."""

    member: Member
    manageable: bool
    assignable_roles: list[tuple[str, str]]
    # Separate from `manageable` on purpose: `can_edit_profile_of` is a narrower question
    # than `can_manage_member` and answers it differently — a yard admin may manage a
    # member's role without being allowed to rewrite their birthday and phone number.
    can_edit_profile: bool = False
    # Narrower again, and for a sharper reason. `can_provision_token` is deliberately
    # stricter than `can_manage_member`: minting an elder link hands the actor a working
    # no-login credential for the TARGET'S WHOLE SCOPE, which they can open themselves. So a
    # yard admin may provision only for someone whose pods are a subset of their own.
    #
    # The roster gated this control on `manageable`, so a yard admin saw "Elder link" on
    # every row in their yard and got a 403 on click — measured — while
    # `setting-up-your-side.md` tells them to click exactly that when a grandparent's link
    # goes to the wrong person.
    can_provision_elder: bool = False


@login_required
def members(request: HttpRequest) -> HttpResponse:
    """Roster of members the actor can see, supervised ones flagged, each with the
    role changes the actor may make (S-701, S-707). Admins only."""
    actor = _acting_member(request)
    if not permissions.is_admin(actor):
        raise PermissionDenied
    role_labels = dict(Member.ROLE_CHOICES)
    rows: list[RosterRow] = []
    for member in permissions.administrable_members(actor).order_by("display_name"):
        manageable = permissions.can_manage_member(actor, member)
        # Only offer roles the actor is authorized to grant this target, excluding the
        # current role (a no-op) and supervised members (re-roled only via their parent).
        assignable = (
            [
                (role, role_labels[role])
                for role in _ASSIGNABLE_ROLES
                if role != member.role and permissions.can_assign_role(actor, member, role)
            ]
            if manageable and not member.is_supervised
            else []
        )
        rows.append(
            RosterRow(
                member=member,
                manageable=manageable,
                assignable_roles=assignable,
                # S-901's third path — an admin fixing a name that was typed wrong at
                # invite time, or filling in an elder's details for her, since she has no
                # login by design (TM-10). The route existed and the only `{% url %}`
                # reference to it in the tree was its own form action, so nobody could open
                # it. `can_edit_profile_of` is deliberately NOT `can_manage_member`: it is
                # a narrower question and has its own answer.
                can_edit_profile=permissions.can_edit_profile_of(actor, member),
                can_provision_elder=(
                    not member.is_supervised and permissions.can_provision_token(actor, member)
                ),
            )
        )
    return render(
        request,
        "core/members.html",
        {
            "content_choices": removal.CONTENT_CHOICES,
            "actor": actor,
            "rows": rows,
            "can_create_yard": permissions.is_instance_admin(actor),
            # The households a supervised child can be placed in. `create_supervised` is
            # POST-only and 404s on GET, and NO template posted to it — so S-703 shipped as
            # an endpoint with no way to reach it, and a child account could not be created
            # from anywhere in the product.
            "assignable_pods": scoping.visible_pods(actor).order_by("name"),
            "is_instance_admin": permissions.is_instance_admin(actor),
            # S-907: what each role actually permits, beside the control that grants
            # it. Only the roles this roster can hand out — listing "supervised" here
            # would describe something the Set role control cannot produce.
            "role_meanings": [
                (label, Member.ROLE_DESCRIPTIONS[role])
                for role, label in Member.ROLE_CHOICES
                if role in _ASSIGNABLE_ROLES
            ],
        },
    )


@login_required
def assign_role(request: HttpRequest, member_id: int) -> HttpResponse:
    """Appoint a delegate or change a member's role (S-707). POST-only. The role must be
    in the offered whitelist AND authorized by can_assign_role for this (actor, target),
    so an instance admin can promote a member to yard_admin (a per-side delegate) or to a
    second instance_admin (succession/bus-factor), and a yard admin can only re-role an
    in-scope member to a non-admin role. Supervised members are never re-roled here."""
    actor = _acting_member(request)
    if request.method != "POST":
        raise Http404
    if not permissions.is_admin(actor):
        raise PermissionDenied
    # Resolve over the administrable set: any member for the instance admin (they can
    # promote a delegate on a side they are not in), yard-scoped for a yard admin with the
    # byte-identical 404 for a cross-yard target (S-202).
    target = get_object_or_404(permissions.administrable_members(actor), pk=member_id)
    new_role = request.POST.get("role", "")
    # Whitelist first: never trust the form's role string (wave-1 review). A value outside
    # the offered set is treated as an unknown request, not a server error.
    if new_role not in _ASSIGNABLE_ROLES or target.is_supervised:
        raise Http404
    if not permissions.can_assign_role(actor, target, new_role):
        raise PermissionDenied
    if new_role != target.role:
        Member.objects.filter(pk=target.pk).update(role=new_role)
    return redirect("members")


@dataclass
class DigestRow:
    """One member's digest state plus their newest delivery records, as typed
    values for the template (the FeedItem pattern)."""

    subscription: DigestSubscription
    # The address the TEMPLATE renders, already masked or not per the viewer's role. The
    # template must never reach through to subscription.address, or the masking becomes a
    # thing every future template has to remember -- the shape T-YARD-6 warns about.
    address: str
    deliveries: list[DigestDelivery]


def _mask_address(address: str) -> str:
    """`priya@example.com` -> `p•••@example.com`. Enough to identify the row and the
    provider for delivery debugging, not enough to write to someone."""
    local, _, domain = address.partition("@")
    if not domain:
        return "•••"
    return f"{local[:1]}•••@{domain}"


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
    # A yard admin sees the address MASKED. It is a personal email the member entered for
    # delivery, and this panel's job is "did it arrive, did it bounce" -- which a masked
    # address answers, since it still identifies the row and the provider. Showing it in
    # full handed a yard admin an address the member may have set HIDDEN on their profile,
    # the same class as T-YARD-6 (a second surface bypassing per-field visibility). The
    # instance admin sees it whole: they hold the database anyway, and T-OP-G1 discloses
    # that plainly rather than pretending otherwise.
    mask = not permissions.is_instance_admin(actor)
    rows = [
        DigestRow(
            subscription=subscription,
            address=_mask_address(subscription.address) if mask else subscription.address,
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
        InboundQuarantine.objects.filter(
            pk=handover.int_or_404(request.POST.get("row_id", ""))
        ).delete()
        return redirect("member_quarantine")
    rows = InboundQuarantine.objects.select_related("member")[:100]
    return render(request, "core/members_quarantine.html", {"actor": actor, "rows": rows})


@login_required
def metrics(request: HttpRequest) -> HttpResponse:
    """Weekly connection health (S-705). Instance admin only, per the story:
    aggregates span every yard, so no yard scoping can apply. What renders is
    counts — the only per-person datum anywhere is the yes/no presence, and it
    is not shown here."""
    actor = _acting_member(request)
    if not permissions.is_instance_admin(actor):
        raise PermissionDenied
    rows = YardWeekMetrics.objects.select_related("yard").order_by("-week_start", "yard__name")[:52]
    return render(request, "core/members_metrics.html", {"actor": actor, "rows": rows})


@login_required
def create_supervised(request: HttpRequest) -> HttpResponse:
    """Create a supervised child under a parent (S-703). The actor must be allowed
    to create a supervised account for that parent, and must be able to see the pod."""
    actor = _acting_member(request)
    if request.method != "POST":
        raise Http404
    parent = scoping.require_visible_member(
        actor, handover.int_or_404(request.POST.get("parent_id", ""))
    )
    if not permissions.can_create_supervised(actor, parent):
        raise PermissionDenied
    pod = scoping.require_visible_pod(actor, handover.int_or_404(request.POST.get("pod_id", "")))
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
    # Administrable set: any member for the instance admin, yard-scoped for a yard admin
    # (a cross-scope target is a byte-identical 404, same as one that does not exist).
    target = get_object_or_404(permissions.administrable_members(actor), pk=member_id)
    permissions.require_can_manage_member(actor, target)  # raises PermissionDenied
    # S-702: the admin chooses what happens to their content, explicitly. An unrecognised
    # or absent value is refused rather than defaulted — a default would silently keep
    # everything, which is the behaviour this criterion exists to replace.
    try:
        remove_member(target, content=request.POST.get("content", ""))
    except removal.UnknownContentChoice as exc:
        raise BadRequest("Choose what happens to this person's posts.") from exc
    return redirect("members")


@login_required
def invite_household(request: HttpRequest) -> HttpResponse:
    """Create a household pod and mint its invite in one flow (S-201): an admin
    names a household and picks a yard they administer, the pod is created in that
    yard, and a one-time invite link + printable QR is shown once for hand-over.
    The invitee never sees a community-setup screen; they only redeem at /join and
    land already inside the pod. Only admins issue invites, scoped by
    can_issue_invite (a yard admin only within their own yards, T-AUTH-G2)."""
    actor = _acting_member(request)
    if not permissions.is_admin(actor):
        raise PermissionDenied
    # The instance admin owns the whole instance, so they can stand up a household in ANY
    # yard, including a just-created empty family side they are not yet a member of (S-708
    # rollout: create the other side, then invite its first household). A yard admin is
    # confined to their own yards (T-AUTH-G2), matching can_issue_invite exactly.
    pickable_yards = (
        Yard.objects.all() if permissions.is_instance_admin(actor) else scoping.visible_yards(actor)
    )
    context: dict[str, object] = {"actor": actor, "yards": list(pickable_yards)}
    errors: list[str] = []
    # Single-use intent nonce: a browser refresh replays a spent nonce and does NOT
    # create a duplicate household + invite (the same guard the elder handover uses).
    if request.method == "POST" and handover.consume_intent(
        request, "invite_household_intent", request.POST.get("intent")
    ):
        # An instance admin may resolve any existing yard; a yard admin only one they are
        # in (require_visible_yard 404s otherwise). The in-transaction can_issue_invite
        # check below is the authoritative gate either way.
        # A LIST, because a household can belong to more than one side — that is the
        # bridging household, the case the whole isolation model is built around and the
        # flagship diagram in docs/README.md ("yours, probably"). Until now every call site
        # in the product did `pod.yards.set([one_yard])`, the form was a single `<select>`,
        # and the ONLY multi-yard assignment anywhere in the tree was a seed script — so
        # `self-host.md` step 2 told an operator to "attach it to the yard(s) it belongs
        # to" and no surface could do it. It required a Django shell, and Django admin is
        # not mounted.
        #
        # No new authorization logic: each yard goes through the same resolution as before,
        # and `can_issue_invite` below already handles the multi-yard case correctly
        # (`pod_yards <= member_yard_ids`), so a yard admin is automatically refused a
        # bridge that spans outside their own side.
        yard_ids = [handover.int_or_404(raw) for raw in request.POST.getlist("yard_ids")]
        yards = [
            get_object_or_404(Yard, pk=yard_id)
            if permissions.is_instance_admin(actor)
            else scoping.require_visible_yard(actor, yard_id)
            for yard_id in yard_ids
        ]
        name = request.POST.get("household_name", "").strip()
        if not name or len(name) > 100:
            errors.append("Give the household a name.")
        elif not yards:
            errors.append("Pick at least one side of the family.")
        else:
            with transaction.atomic():
                pod = Pod.objects.create(name=name, kind=Pod.HOUSEHOLD)
                pod.yards.set(yards)
                # Defense in depth: the pod sits in a yard the actor picked through
                # require_visible_yard, so can_issue_invite passes for an in-scope
                # yard admin; anything else is refused before a token is minted.
                if not permissions.can_issue_invite(actor, pod):
                    raise PermissionDenied
                invite, raw = invites.mint_invite(pod, created_by=actor)
            context.update(handover.link_artifacts(f"{settings.BASE_URL}/join/{raw}/"))
            context.update(
                {
                    "household_name": name,
                    # Plural now: a bridging household names both sides, and the confirm
                    # page has to say so or the operator cannot tell what they just made.
                    "yard_name": " and ".join(sorted(y.name for y in yards)),
                    "expires_at": invite.expires_at,
                    "max_uses": invite.max_uses,
                }
            )
    context["errors"] = errors
    context["intent"] = handover.fresh_intent(request, "invite_household_intent")
    response = render(request, "core/invite_household.html", context)
    # Carries the raw invite token in its body once and hosts the create form: the shared
    # hand-over hygiene set (no-store against a bfcache restore of a walked-away-from admin
    # screen, and same-origin so the form POST is not CSRF-rejected on an Origin: null).
    return handover.apply_token_body_headers(response)


@login_required
def invite_list(request: HttpRequest) -> HttpResponse:
    """Outstanding invites the actor may see, with per-invite uses-left, expiry, and
    who redeemed it and when (S-201 hardening). Scoped exactly like the authority to
    issue: an invite is shown only if the actor can_issue_invite for its pod, so a
    yard admin never sees another yard's invites (or a bridge pod's spanning outside
    their scope). Calm surface: no counts of activity, only the invite ledger."""
    actor = _acting_member(request)
    if not permissions.is_admin(actor):
        raise PermissionDenied
    if permissions.is_instance_admin(actor):
        candidates = Invite.objects.all()
    else:
        # Scope the candidate set EXACTLY in the query, before the [:200] slice, not
        # just with a superset prefilter cleaned up in Python afterward (security
        # review LOW). A yard admin may issue only into a pod whose yards are ALL
        # within their own, so an invite qualifies iff its pod touches the actor's
        # yards AND has no yard outside them (a bridge pod spanning outside is
        # excluded, matching can_issue_invite). Filtering after the slice would let a
        # burst of out-of-scope bridge invites fill the window and push in-scope ones
        # out of view; filtering before it keeps the window all-issuable.
        actor_yards = scoping.member_yard_ids(actor)
        outside_yards = Yard.objects.exclude(id__in=actor_yards)
        candidates = (
            Invite.objects.filter(pod__yards__id__in=actor_yards)
            .exclude(pod__yards__id__in=outside_yards)
            .distinct()
        )
    rows = [
        invite
        for invite in candidates.select_related("pod")
        .prefetch_related("redemptions__member")
        .order_by("-created_at")[:200]
        if permissions.can_issue_invite(actor, invite.pod)
    ]
    return render(
        request,
        "core/members_invites.html",
        {"actor": actor, "invites": rows, "now": timezone.now()},
    )


@login_required
def revoke_invite(request: HttpRequest, invite_id: int) -> HttpResponse:
    """Revoke an invite (S-201 hardening: invites are revocable). POST-only,
    authorized by can_issue_invite over the invite's pod (whoever may issue may
    revoke). A revoked invite 404s at /join immediately, the same InviteInvalid
    parity as an unknown token."""
    actor = _acting_member(request)
    if request.method != "POST":
        raise Http404
    if not permissions.is_admin(actor):
        raise PermissionDenied
    try:
        invite = Invite.objects.select_related("pod").get(pk=invite_id)
    except Invite.DoesNotExist:
        raise Http404 from None
    # 404 (not 403) an invite outside the actor's issuing scope: never reveal the
    # existence of another yard's invite.
    if not permissions.can_issue_invite(actor, invite.pod):
        raise Http404
    if invite.revoked_at is None:
        Invite.objects.filter(pk=invite.pk).update(revoked_at=timezone.now())
    return redirect("member_invites")


@login_required
def resend_invite(request: HttpRequest, invite_id: int) -> HttpResponse:
    """Mint a FRESH one-time link for a household whose earlier link expired, filled up,
    was revoked, or simply needs another copy to hand over (S-212). POST-only, authorized
    exactly like issuing and revoking (can_issue_invite over the invite's pod), with the
    same byte-identical 404 for an out-of-scope or unknown invite so another side's invite
    is never revealed (S-202 parity). The new link is ADDITIVE: the prior invite is left
    untouched (it may still be live in someone's hands), so re-handing-over never silently
    kills a link already sent. The fresh raw token is shown once, with the TM-5 headers."""
    actor = _acting_member(request)
    if request.method != "POST":
        raise Http404
    if not permissions.is_admin(actor):
        raise PermissionDenied
    try:
        invite = Invite.objects.select_related("pod").get(pk=invite_id)
    except Invite.DoesNotExist:
        raise Http404 from None
    # 404 (not 403) an invite outside the actor's issuing scope: never reveal that another
    # yard's invite exists, the same parity as revoke_invite.
    if not permissions.can_issue_invite(actor, invite.pod):
        raise Http404
    fresh, raw = invites.mint_invite(invite.pod, created_by=actor)
    response = render(
        request,
        "core/handover_link.html",
        {
            "actor": actor,
            **handover.link_artifacts(f"{settings.BASE_URL}/join/{raw}/"),
            "pod_name": invite.pod.name,
            "expires_at": fresh.expires_at,
            "max_uses": fresh.max_uses,
        },
    )
    # Carries the raw invite token once: the shared hand-over hygiene set (no-store +
    # same-origin), like invite_household.
    return handover.apply_token_body_headers(response)


@login_required
def family_sides(request: HttpRequest) -> HttpResponse:
    """Create and list the family sides (yards) — S-708. Instance admin ONLY: a new
    family side is an instance-wide act that widens the isolation topology, so it sits
    above the per-yard delegates (a yard admin administers within a side, never creates a
    new one). This unblocks the seed-ally rollout's second move: stand up the other side,
    then invite its first household (invite_household) and appoint its per-side delegate
    (assign_role). A refresh replays a spent intent nonce and creates no duplicate side."""
    actor = _acting_member(request)
    if not permissions.is_instance_admin(actor):
        raise PermissionDenied
    errors: list[str] = []
    if request.method == "POST" and handover.consume_intent(
        request, "create_yard_intent", request.POST.get("intent")
    ):
        name = request.POST.get("yard_name", "").strip()
        if not name or len(name) > 100:
            errors.append("Give the family side a name.")
        else:
            Yard.objects.create(name=name, slug=_unique_yard_slug(name))
            return redirect("family_sides")
    return render(
        request,
        "core/family_sides.html",
        {
            "actor": actor,
            "yards": Yard.objects.order_by("name"),
            "errors": errors,
            "intent": handover.fresh_intent(request, "create_yard_intent"),
        },
    )
