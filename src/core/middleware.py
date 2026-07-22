"""Token-surface response headers (TM-5), for every response shape.

The /d/ views set their own hygiene headers on the pages they render, but a
token URL also produces guard 404s, 405s, and APPEND_SLASH redirects, and those
must carry the same no-store/noindex set (security review of #36 LOW-2): a
cached or referrer-leaked failure response still names a token-bearing URL.
Stamping by path prefix keeps 404 byte-identity intact — the body stays the
guard's bare 404; only path-derived headers differ.

The Referrer-Policy differs by surface class. /t/ and /d/ carry the token IN the
URL, so they get no-referrer: the token must never ride a navigation's Referer —
including the /t/ -> /e/ redirect, which under a laxer policy would put the token
in the /e/ request's Referer (and the access log). /e/ is the elder session
surface: the token was already exchanged for a cookie, so /e/ URLs carry NO
token, but /e/ DOES host same-origin POST forms (one-tap react, bigger-text).
Under no-referrer the browser sends Origin: null on those POSTs and Django's CSRF
check rejects them, so the elder could never react from a real browser.
same-origin gives /e/ the identical cross-origin guarantee (zero third-party
Referer or Origin) while sending the same-origin Origin the CSRF check needs.
"""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

# Token is IN the URL: suppress the Referer entirely.
_TOKEN_URL_PREFIXES = ("/d/", "/t/")
# Elder session surface: no token in the URL, but hosts same-origin POST forms.
_ELDER_SURFACE_PREFIX = "/e/"


class TokenSurfaceHeadersMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        path = request.path
        on_token_url = path.startswith(_TOKEN_URL_PREFIXES)
        on_elder_surface = path.startswith(_ELDER_SURFACE_PREFIX)
        if on_token_url or on_elder_surface:
            response["X-Robots-Tag"] = "noindex, nofollow"
            response["Cache-Control"] = "no-store"
            response["X-Content-Type-Options"] = "nosniff"
            # no-referrer where the token is in the URL; same-origin on the elder session
            # surface so its POST forms are not CSRF-rejected on an Origin: null.
            response["Referrer-Policy"] = "no-referrer" if on_token_url else "same-origin"
        return response
