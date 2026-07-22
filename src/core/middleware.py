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

import secrets
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


class ContentSecurityPolicyMiddleware:
    """A baseline Content-Security-Policy (S-724): default-src 'self' with a per-request
    nonce for the handful of inline scripts (service-worker registration, the client-side
    photo resize, the hand-over copy/share enhancement), so member-authored content can
    never inject an executing script even if Django's autoescape were somehow bypassed —
    the second net over autoescape the threat model asked for (TS-DJ-9).

    script-src is nonce-based, NOT 'unsafe-inline' — that is the control that matters: an
    injected <script> without this response's nonce does not run. style-src keeps
    'unsafe-inline' because the templates carry inline style attributes and <style> blocks
    that a nonce does not cover, and the XSS lever is script execution, not CSS. Every
    subresource is same-origin (there is no CDN), so the rest is a tight 'self';
    frame-ancestors 'none' is the CSP twin of X-Frame-Options DENY.

    The nonce is set on the request BEFORE the view renders (templates read it as
    request.csp_nonce) and stamped into the header on the way out, so the two always match.
    setdefault leaves alone any response that already carries its own policy — a per-view
    override may only TIGHTEN the baseline, never weaken it (no view sets one today).
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        nonce = secrets.token_urlsafe(16)
        # Read by templates as request.csp_nonce (the request context processor exposes it).
        request.csp_nonce = nonce  # type: ignore[attr-defined]
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", _policy(nonce))
        return response


def _policy(nonce: str) -> str:
    return "; ".join(
        (
            "default-src 'self'",
            f"script-src 'self' 'nonce-{nonce}'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self'",
            "object-src 'none'",
            "frame-src 'none'",  # the app embeds no iframes; an injected same-origin frame is inert
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
            "connect-src 'self'",
            "worker-src 'self'",
            "manifest-src 'self'",
        )
    )
