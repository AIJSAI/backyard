"""Elder token provisioning (S-104): generate, show, hand over, regenerate.

The family tech-helper generates an elder's link here. The flow shows the exact
pod and yard the token will grant BEFORE generation (T-TOKEN-G1), names the
surface as the elder path in plain words, and refuses a supervised member
(TM-10). Generating or regenerating ends with the re-hand-over artifacts in
hand in the same view: the link ready to send and a printable QR (rendered
inline as SVG, no script and no network). Regenerating invalidates the prior
token through the total regenerate (elder_tokens.regenerate, TM-1).

Authorization is the roster's: only an admin who may manage the target member
reaches this, so a yard admin provisions only within their own yards
(core.permissions). The raw token appears exactly once, on the page that mints
it, and is never stored or logged.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.safestring import mark_safe

from . import elder_tokens, permissions, scoping
from .feed_views import _acting_member
from .handover import apply_token_body_headers, consume_intent, fresh_intent, qr_svg
from .models import Member, Pod, PodMembership, Yard


def _int_or_404(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise Http404 from exc


@login_required
def provision_elder(request: HttpRequest, member_id: int) -> HttpResponse:
    """Show the elder path for one member and mint on demand (S-104)."""
    actor = _acting_member(request)
    if not permissions.is_admin(actor):
        raise PermissionDenied
    # The administrable set 404s a member the actor cannot administer (any member for the
    # instance admin, yard-scoped for a yard admin); the manage check then refuses one they
    # can see but may not administer (e.g. a yard admin on a bridge or admin member).
    target = get_object_or_404(permissions.administrable_members(actor), pk=member_id)
    if not permissions.can_manage_member(actor, target):
        raise PermissionDenied
    if target.is_supervised:
        # The elder path is never a supervised child's surface (TM-10). Named
        # explicitly so the UI cannot offer it rather than failing on submit.
        raise Http404

    # Deliberately the TARGET's full scope, not the actor's (#43 review LOW-3):
    # the token grants the target's whole visibility, and only an instance admin
    # can reach a bridge target (a yard admin is refused by can_manage_member's
    # subset check), so viewer-scoping here would UNDERSTATE the grant's blast
    # radius to the person about to hand it over, gutting T-TOKEN-G1.
    pods = list(scoping.visible_pods(target))
    yards = list(scoping.visible_yards(target))
    has_token = hasattr(target, "elder_token")
    context: dict[str, object] = {
        "actor": actor,
        "target": target,
        "pods": pods,
        "yards": yards,
        "has_token": has_token,
    }

    # A one-time intent nonce (#43 review MEDIUM-2): the mint form carries it,
    # the POST consumes it, and a browser refresh (a replayed POST with a spent
    # nonce) re-renders WITHOUT minting instead of silently regenerating the
    # link the admin just handed over. Consume BEFORE minting the next nonce,
    # or the fresh one would overwrite the submitted one's match. Kept in the
    # session, never the DB row, so the raw token still appears exactly once.
    if request.method == "POST" and consume_intent(
        request, f"elder_intent:{target.id}", request.POST.get("intent")
    ):
        raw = elder_tokens.regenerate(target) if has_token else elder_tokens.mint(target)
        link = f"{settings.BASE_URL}/t/{raw}/"
        context.update(
            {
                "minted_link": link,
                # noqa justified: the SVG is qrcode's own path geometry, and the
                # only input is our CSPRNG token plus the configured BASE_URL —
                # the URL becomes QR modules, never reflected as SVG text.
                "qr_svg": mark_safe(qr_svg(link)),  # noqa: S308
                "regenerated": has_token,
                "has_token": True,
            }
        )
    # The nonce for the NEXT action, set after any consume so it never clobbers
    # the one just submitted.
    context["intent"] = fresh_intent(request, f"elder_intent:{target.id}")

    response = render(request, "core/provision_elder.html", context)
    # Carries the raw master token in its body (never its URL) and hosts the regenerate
    # form, so it gets the shared hand-over hygiene set: no-store against a bfcache restore
    # of a walked-away-from admin screen, and same-origin (not no-referrer) so the form's
    # POST is not CSRF-rejected on an Origin: null (#43 HIGH-1; apply_token_body_headers).
    return apply_token_body_headers(response)


@login_required
def new_elder(request: HttpRequest) -> HttpResponse:
    """Create a net-new elder — a grandparent who never logs in — and mint their token
    in one flow (S-213). The delegate names the elder and picks a side of the family; we
    create their household pod in that yard, create the token-only member (no User,
    non-supervised), mint the elder token, and show the hand-over artifacts once. This is
    the move a delegate needs to onboard a grandparent onto the no-login path without a
    shell; provision_elder only re-mints for an already-existing member.

    Delegate-usable, scoped exactly like invite_household: the instance admin may add an
    elder to ANY side (including one they are not a member of, for the seed-ally rollout),
    a yard admin only within their own yards (require_visible_yard 404s otherwise). The
    authoritative in-transaction gate is can_issue_invite over the just-created pod — the
    same authority as issuing a household invite, since standing up a household and its
    first credential is one act whether that credential is an invite link or an elder
    token. The elder's whole visibility is that household's yard, a subset of the acting
    admin's authority by that same check, so no yard admin can stand up an elder who sees
    a side they do not control.
    """
    actor = _acting_member(request)
    if not permissions.is_admin(actor):
        raise PermissionDenied
    # The instance admin owns the whole instance and may add an elder to any side; a yard
    # admin is confined to their own yards (T-AUTH-G2), matching can_issue_invite exactly.
    pickable_yards = (
        Yard.objects.all() if permissions.is_instance_admin(actor) else scoping.visible_yards(actor)
    )
    context: dict[str, object] = {"actor": actor, "yards": list(pickable_yards)}
    errors: list[str] = []
    # Single-use intent nonce (same guard as invite_household): a browser refresh replays
    # a spent nonce and does NOT create a second household + elder + token.
    if request.method == "POST" and consume_intent(
        request, "new_elder_intent", request.POST.get("intent")
    ):
        yard_id = _int_or_404(request.POST.get("yard_id", ""))
        # An instance admin may resolve any yard; a yard admin only one they are in
        # (require_visible_yard 404s otherwise). can_issue_invite below is authoritative.
        yard = (
            get_object_or_404(Yard, pk=yard_id)
            if permissions.is_instance_admin(actor)
            else scoping.require_visible_yard(actor, yard_id)
        )
        elder_name = request.POST.get("elder_name", "").strip()
        kinship = request.POST.get("kinship_name", "").strip()
        household = request.POST.get("household_name", "").strip()
        if not elder_name or len(elder_name) > 100:
            errors.append("Give the grandparent a name.")
        if not household or len(household) > 100:
            errors.append("Name their household.")
        if len(kinship) > 50:
            errors.append("That nickname is too long (max 50 characters).")
        if not errors:
            with transaction.atomic():
                pod = Pod.objects.create(name=household, kind=Pod.HOUSEHOLD)
                pod.yards.set([yard])
                # Defense in depth: the pod sits in the picked (in-scope) yard, so
                # can_issue_invite passes for an in-scope yard admin; anything else is
                # refused and the whole atomic block (pod, member, token) rolls back.
                if not permissions.can_issue_invite(actor, pod):
                    raise PermissionDenied
                elder = Member.objects.create(
                    display_name=elder_name, kinship_name=kinship, user=None
                )
                PodMembership.objects.create(member=elder, pod=pod)
                # mint refuses a supervised member (elder is not) and an insecure base
                # URL; inside the transaction so a refusal orphans nothing.
                raw = elder_tokens.mint(elder)
            link = f"{settings.BASE_URL}/t/{raw}/"
            context.update(
                {
                    "minted_link": link,
                    # noqa justified: the SVG is qrcode's own path geometry over our
                    # CSPRNG token in BASE_URL, never reflected user text.
                    "qr_svg": mark_safe(qr_svg(link)),  # noqa: S308
                    "elder_name": elder_name,
                    "yard_name": yard.name,
                }
            )
    context["errors"] = errors
    context["intent"] = fresh_intent(request, "new_elder_intent")
    response = render(request, "core/new_elder.html", context)
    # Carries the raw elder token in its body once and hosts the create form: the shared
    # hand-over hygiene set (no-store + same-origin, so the form POST is not CSRF-rejected).
    return apply_token_body_headers(response)
