"""PWA install surface (S-103): the Get The App page, manifest, icons, a worker.

Backyard installs to a member's home screen so it feels like an app with no
app store. Per ADR-002 the service worker is deliberately minimal: it has a
fetch handler (Chrome's installability bar) but NO app-shell precache and
caches nothing, so it can never serve a stale or cross-account page and there
is no cache to leak a token through. The manifest's start_url is the login-
gated feed; the icons are generated deterministically, no binary in the tree.

All of that shipped and NOTHING IN THE PRODUCT EVER SAID SO. A member had to
know that Safari's Share sheet holds Add to Home Screen, and an Android member
never saw an install control at all, so the one feature that turns this into
"the app" on a relative's phone was reachable only by somebody who already knew
how. `get_the_app` is that missing half.

The elder token surface never references any of this (the Safari eviction rule,
ADR-002): elders on a bare token link are the definition of intermittent
visitors whose service worker Safari would evict, so the elder page is plain
server-rendered HTML with no manifest link and no worker registration.
"""

from __future__ import annotations

import io

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from PIL import Image, ImageDraw

# Design v3 "Signage". These were still the v2 navy (#234a78) and its cool near-white
# ground after the founder REJECTED v2 and the whole app moved to sign green — so
# installing the PWA gave a home-screen icon and a splash screen matching nothing in the
# product, which is the one surface a member looks at every day without opening the app.
# Kept in sync with base.html's --green and --paper by test_pwa.
_THEME = "#1e5c46"  # --green, sign green (7.63:1 on paper)
_BG = "#fbfcfb"  # --paper


@login_required
def get_the_app(request: HttpRequest) -> HttpResponse:
    """How to put Backyard on a home screen, said once, in the product (S-103).

    SIGNED IN ONLY, and that is a mechanism decision rather than a privacy one —
    though it is both. base.html links the manifest and the apple-touch-icon for an
    AUTHENTICATED reader only, so a signed-out visitor following these steps would
    add a home-screen icon with no name, no icon and no standalone display, and
    Chrome would never fire `beforeinstallprompt` on a page with no manifest, so the
    Install App button would sit there dead. A page that tells somebody to install
    an app they cannot install is worse than no page. The privacy half is the usual
    one: this is an invite-only family network, the start_url is the login-gated
    feed, and a stranger reading an install guide learns nothing they can use.

    The page itself is static: the platform branch, the in-app-browser warning and
    the already-installed state are all decided in the browser, because only the
    browser knows. Nothing here sniffs a user agent server-side.
    """
    return render(
        request,
        "core/get_the_app.html",
        # The already-installed branch of the steps offers the one thing left to do
        # (S-107). Absent on an instance whose operator has set no VAPID pair: an
        # offer that leads to "notifications are not set up" is worse than no offer.
        {"push_available": settings.PUSH_ENABLED},
    )


def manifest(request: HttpRequest) -> JsonResponse:
    """The web app manifest (S-103): name, standalone display, icons."""
    data = {
        "name": "Backyard",
        "short_name": "Backyard",
        # The app's IDENTITY, and it must never change: a manifest with no `id` gets
        # one implicitly from start_url, so every Backyard installed before this line
        # existed is identified as "/feed/". Writing that same value down pins it. Any
        # other value — "/" looks tidier — would read to Chrome as a DIFFERENT app, so
        # an existing install would stop updating and a second icon would appear beside
        # it on the home screen of every relative who already has one.
        "id": "/feed/",
        # Read in the phone's install sheet, and the only place in the product where a
        # sentence has to introduce Backyard to somebody who has not seen a screen of it.
        # "Your family, on your own schedule." was the one marketing-shaped line anywhere
        # in the product; this is the landing page's own sentence, so the install sheet
        # and the first screen say the same thing.
        "description": "A private, invite-only family network.",
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
    green rounded field. Deterministic, no binary in the tree. A maskable icon keeps
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
    # An arched door cut back to the green field: a rectangle body + a half-disc arch.
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
#
# S-107 adds `push` and `notificationclick` and NOTHING ELSE. The two handlers hold to
# the same rule: the payload arrives decrypted by the browser (RFC 8291), is shown, and
# is never stored — there is still no Cache API use anywhere in this file, and test_pwa
# asserts that from the served bytes rather than from this comment.
#
# `data.url` IS UNTRUSTED INPUT, and it is the one place this worker could be turned into
# something. It arrives inside an encrypted payload, so only this server can have written
# it — but a worker that calls `clients.openWindow(data.url)` on whatever it is handed is
# one server-side defect away from opening an attacker's origin from inside the installed
# app, where a relative has no address bar to read. So the worker refuses anything that is
# not a single-slash absolute PATH ("/posts/12/"), which rejects "https://elsewhere/",
# "javascript:..." and the protocol-relative "//elsewhere/" that a naive startsWith('/')
# check accepts, and then COMPARES THE RESOLVED ORIGIN.
#
# The character tests alone were not enough, and that is why the comparison is there. A
# leading slash followed by a BACKSLASH is resolved by the WHATWG URL parser as a second
# slash whenever the base has a special scheme, so it lands on another origin while
# passing both of the character tests above (measured by the review lens in node). The
# backslash arm is written as `charCodeAt(1) === 92` rather than as a literal, so no
# escape has to survive this Python string; the origin comparison after resolution is the
# check that holds whatever the next parser quirk turns out to be.
_SERVICE_WORKER = """\
// Backyard service worker (minimal by design, ADR-002): no precache, no cache.
self.addEventListener('install', (event) => { self.skipWaiting(); });
self.addEventListener('activate', (event) => { event.waitUntil(self.clients.claim()); });
self.addEventListener('fetch', (event) => {
  // Network passthrough only. Nothing is cached, so nothing sensitive can be
  // served stale or from a device that changed hands.
  event.respondWith(fetch(event.request));
});

// Only a same-origin absolute path, resolved against this origin. A protocol-relative
// value (a slash followed by a slash) is refused -- and so is a slash followed by a
// BACKSLASH, because the URL parser treats a backslash under a special scheme as a second
// slash and resolves it to another origin (charCodeAt 92, spelled that way so no escape
// has to survive the server-side string literal). The resolved origin is then compared,
// which is the check that holds whatever the next parser quirk turns out to be. Anything
// unusable falls back to the feed.
function backyardPath(value) {
  const feed = new URL('/feed/', self.location.origin).href;
  if (typeof value !== 'string' || value.charAt(0) !== '/'
      || value.charAt(1) === '/' || value.charCodeAt(1) === 92) {
    return feed;
  }
  const resolved = new URL(value, self.location.origin);
  return resolved.origin === self.location.origin ? resolved.href : feed;
}

self.addEventListener('push', (event) => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch (error) { payload = {}; }
  const title = payload.title || 'Backyard';
  event.waitUntil(self.registration.showNotification(title, {
    body: payload.body || '',
    // The tag collapses every notification about one post into one entry, so a busy
    // thread is one line on the lock screen and a redelivered job replaces its own
    // notification instead of adding a second.
    tag: payload.tag || 'backyard',
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    data: { url: backyardPath(payload.url) }
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = backyardPath(event.notification.data && event.notification.data.url);
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    .then((windows) => {
      for (const client of windows) {
        if (client.url === target && 'focus' in client) { return client.focus(); }
      }
      // Nothing open on that post: focus an open Backyard and send it there, or open one.
      for (const client of windows) {
        if ('navigate' in client && 'focus' in client) {
          return client.navigate(target).then((navigated) => (navigated || client).focus());
        }
      }
      return self.clients.openWindow(target);
    }));
});
"""


def service_worker(request: HttpRequest) -> HttpResponse:
    response = HttpResponse(_SERVICE_WORKER, content_type="application/javascript")
    # Browsers must always re-check the worker so an update ships promptly, and
    # the worker file itself is never held in the HTTP cache.
    response["Cache-Control"] = "no-cache"
    return response
