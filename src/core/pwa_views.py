"""PWA install surface (S-103): manifest, icons, a minimal service worker.

Backyard installs to a member's home screen so it feels like an app with no
app store. Per ADR-002 the service worker is deliberately minimal: it has a
fetch handler (Chrome's installability bar) but NO app-shell precache and
caches nothing, so it can never serve a stale or cross-account page and there
is no cache to leak a token through. The manifest's start_url is the login-
gated feed; the icons are generated deterministically, no binary in the tree.

The elder token surface never references any of this (the Safari eviction rule,
ADR-002): elders on a bare token link are the definition of intermittent
visitors whose service worker Safari would evict, so the elder page is plain
server-rendered HTML with no manifest link and no worker registration.
"""

from __future__ import annotations

import io

from django.http import HttpRequest, HttpResponse, JsonResponse
from PIL import Image, ImageDraw

_THEME = "#234a78"  # Backyard navy (design system v2)
_BG = "#f7f8f9"  # cool near-white ground


def manifest(request: HttpRequest) -> JsonResponse:
    """The web app manifest (S-103): name, standalone display, icons."""
    data = {
        "name": "Backyard",
        "short_name": "Backyard",
        "description": "Your family, on your own schedule.",
        "start_url": "/feed/",
        "scope": "/",
        "display": "standalone",
        "background_color": _BG,
        "theme_color": _THEME,
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {
                "src": "/icon-maskable-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
    }
    response = JsonResponse(data)
    response["Content-Type"] = "application/manifest+json"
    response["Cache-Control"] = "public, max-age=86400"
    return response


def _render_icon(size: int, *, maskable: bool) -> bytes:
    """The Homestead mark (design system v2): a light house with an arched door on a
    navy rounded field. Deterministic, no binary in the tree. A maskable icon keeps
    its content inside the center safe zone so a launcher mask cannot clip it. Traces
    the handoff app-icon path (§6) in a 24-unit box whose 2..22 field maps to the
    padded rounded rectangle."""
    image = Image.new("RGB", (size, size), _BG)
    draw = ImageDraw.Draw(image)
    pad = int(size * (0.16 if maskable else 0.08))
    inner = size - 2 * pad
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad], radius=int(inner * 0.275), fill=_THEME
    )

    def m(x: float, y: float) -> tuple[float, float]:
        # map the §6 24-box (the rounded field spans 2..22) into the padded field
        return (pad + (x - 2) / 20 * inner, pad + (y - 2) / 20 * inner)

    # A light house pentagon: apex, right eave, right base, left base, left eave.
    draw.polygon([m(12, 6), m(17.4, 10.8), m(17.4, 17.6), m(6.6, 17.6), m(6.6, 10.8)], fill=_BG)
    # An arched door cut back to the navy field: a rectangle body + a half-disc arch.
    dl, dtop = m(10.6, 14)
    dr, dbot = m(13.4, 17.6)
    draw.rectangle([dl, dtop, dr, dbot], fill=_THEME)
    cx, cy = m(12, 14)
    r = 1.4 / 20 * inner
    draw.pieslice([cx - r, cy - r, cx + r, cy + r], start=180, end=360, fill=_THEME)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _icon_response(size: int, *, maskable: bool) -> HttpResponse:
    response = HttpResponse(_render_icon(size, maskable=maskable), content_type="image/png")
    response["Cache-Control"] = "public, max-age=604800"
    return response


def icon_192(request: HttpRequest) -> HttpResponse:
    return _icon_response(192, maskable=False)


def icon_512(request: HttpRequest) -> HttpResponse:
    return _icon_response(512, maskable=False)


def icon_maskable_512(request: HttpRequest) -> HttpResponse:
    return _icon_response(512, maskable=True)


# A deliberately minimal service worker (ADR-002): a fetch handler for
# installability, network passthrough, and NO cache. It stores nothing, so it
# can never serve a stale page, a cross-account response, or a token surface
# from cache, and there is no cache for a lost device to mine.
_SERVICE_WORKER = """\
// Backyard service worker (minimal by design, ADR-002): no precache, no cache.
self.addEventListener('install', (event) => { self.skipWaiting(); });
self.addEventListener('activate', (event) => { event.waitUntil(self.clients.claim()); });
self.addEventListener('fetch', (event) => {
  // Network passthrough only. Nothing is cached, so nothing sensitive can be
  // served stale or from a device that changed hands.
  event.respondWith(fetch(event.request));
});
"""


def service_worker(request: HttpRequest) -> HttpResponse:
    response = HttpResponse(_SERVICE_WORKER, content_type="application/javascript")
    # Browsers must always re-check the worker so an update ships promptly, and
    # the worker file itself is never held in the HTTP cache.
    response["Cache-Control"] = "no-cache"
    return response
