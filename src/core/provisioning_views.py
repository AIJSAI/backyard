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

    pods = list(scoping.visible_pods(target))
    yards = list(scoping.visible_yards(target))
    context: dict[str, object] = {
        "actor": actor,
        "target": target,
        "pods": pods,
        "yards": yards,
        "has_token": hasattr(target, "elder_token"),
    }

    if request.method == "POST":
        raw = elder_tokens.regenerate(target) if context["has_token"] else elder_tokens.mint(target)
        link = f"{settings.BASE_URL}/t/{raw}/"
        context.update(
            {
                "minted_link": link,
                # noqa justified: the SVG is qrcode's own path geometry, and the
                # only input is our CSPRNG token plus the configured BASE_URL —
                # the URL becomes QR modules, never reflected as SVG text.
                "qr_svg": mark_safe(_qr_svg(link)),  # noqa: S308
                "regenerated": context["has_token"],
                "has_token": True,
            }
        )

    return render(request, "core/provision_elder.html", context)
