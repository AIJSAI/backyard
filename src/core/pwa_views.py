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

_THEME = "#2f5d3a"  # a backyard green
_BG = "#f4f1ea"


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
    """A simple, deterministic house glyph on a rounded field. A maskable icon
    keeps its content inside the center safe zone so a launcher mask cannot clip
    it."""
    image = Image.new("RGB", (size, size), _BG)
    draw = ImageDraw.Draw(image)
    pad = int(size * (0.16 if maskable else 0.08))
    draw.rounded_rectangle([pad, pad, size - pad, size - pad], radius=int(size * 0.18), fill=_THEME)
    # A plain white house: a roof triangle over a body square, centered.
    cx = size / 2
    body_top = size * 0.5
    body_half = size * 0.16
    draw.rectangle([cx - body_half, body_top, cx + body_half, size * 0.72], fill=_BG)
    draw.polygon(
        [(cx - body_half * 1.4, body_top), (cx, size * 0.32), (cx + body_half * 1.4, body_top)],
        fill=_BG,
    )
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
