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

import io
import secrets

import qrcode  # type: ignore[import-untyped]  # qrcode ships no stubs
import qrcode.image.svg  # type: ignore[import-untyped]
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.safestring import mark_safe

from . import elder_tokens, permissions, scoping
from .feed_views import _acting_member


def _qr_svg(url: str) -> str:
    """An inline SVG QR for the handover URL. SVG has no raster dependency and
    embeds directly in the page, so the printable artifact needs no script, no
    image host, and no round-trip."""
    image = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue().decode()


@login_required
def provision_elder(request: HttpRequest, member_id: int) -> HttpResponse:
    """Show the elder path for one member and mint on demand (S-104)."""
    actor = _acting_member(request)
    if not permissions.is_admin(actor):
        raise PermissionDenied
    # require_visible_member 404s a member the actor cannot even see; the manage
    # check then refuses one they can see but may not administer.
    target = scoping.require_visible_member(actor, member_id)
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
    if request.method == "POST" and _consume_intent(request, target.id, request.POST.get("intent")):
        raw = elder_tokens.regenerate(target) if has_token else elder_tokens.mint(target)
        link = f"{settings.BASE_URL}/t/{raw}/"
        context.update(
            {
                "minted_link": link,
                # noqa justified: the SVG is qrcode's own path geometry, and the
                # only input is our CSPRNG token plus the configured BASE_URL —
                # the URL becomes QR modules, never reflected as SVG text.
                "qr_svg": mark_safe(_qr_svg(link)),  # noqa: S308
                "regenerated": has_token,
                "has_token": True,
            }
        )
    # The nonce for the NEXT action, set after any consume so it never clobbers
    # the one just submitted.
    context["intent"] = _fresh_intent(request, target.id)

    response = render(request, "core/provision_elder.html", context)
    # This page can carry the raw master token in its body, so it gets the full
    # TM-5 header set even though /members/ is not a token-prefix route (#43
    # review HIGH-1). The token is never in the URL, but no-store defends the
    # bfcache/history restore of a walked-away-from admin screen.
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _fresh_intent(request: HttpRequest, target_id: int) -> str:
    intent = secrets.token_urlsafe(16)
    request.session[f"elder_intent:{target_id}"] = intent
    return intent


def _consume_intent(request: HttpRequest, target_id: int, submitted: str | None) -> bool:
    key = f"elder_intent:{target_id}"
    expected = request.session.get(key)
    if not submitted or submitted != expected:
        return False
    del request.session[key]  # single use: a refreshed POST replays a spent nonce
    return True
