"""Token-surface response headers (TM-5), for every response shape.

The /d/ views set their own hygiene headers on the pages they render, but a
token URL also produces guard 404s, 405s, and APPEND_SLASH redirects, and those
must carry the same no-store/no-referrer/noindex set (security review of #36
LOW-2): a cached or referrer-leaked failure response still names a
token-bearing URL. Stamping by path prefix keeps 404 byte-identity intact —
the body stays the guard's bare 404; only path-derived headers differ.
"""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

_TOKEN_PREFIXES = ("/d/",)


class TokenSurfaceHeadersMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if request.path.startswith(_TOKEN_PREFIXES):
            response["X-Robots-Tag"] = "noindex, nofollow"
            response["Referrer-Policy"] = "no-referrer"
            response["Cache-Control"] = "no-store"
            response["X-Content-Type-Options"] = "nosniff"
        return response
