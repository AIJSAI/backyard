"""One throttle for every unauthenticated bearer surface (S2, issue 173).

The surfaces a stranger can reach with nothing but a URL: the invite join page, the
no-login link a grandparent opens, the web view of an emailed family update and its
confirm/unsubscribe pages, the "get back in" link an admin hands over, and the
break-glass admin reset. Every one of them carries a 256-bit token, so this is not about
guessing — it is about AVAILABILITY and cost: each hits the database several times and
renders a ~26 KB page even to refuse (see `TokenSurfaceHeadersMiddleware`'s own note on
that), and until now one client could ask for them as fast as it liked, on a box with
three gunicorn workers and the family's photographs on the same disk.

WHY A MIDDLEWARE, AND NOT A LINE IN EACH VIEW. This was built as a per-view call first,
and it did not work. `ATOMIC_REQUESTS = True` wraps every view in a transaction, the rate
limit lives in a DatabaseCache (TS-DJ-13: shared across workers, survives restarts), and
every one of these views answers an unknown or spent token by RAISING `Http404` — which
propagates out of that transaction and rolls the counter write back with it. Measured:
400 consecutive requests to `/break-glass/<bad>/<bad>/` were all answered, and the
counter never got past zero. The throttle would have been live on exactly the requests
that succeed and dead on exactly the requests an attacker makes. Middleware runs OUTSIDE
`make_view_atomic`, so its writes commit in autocommit and the 404 path counts like any
other — and, like `TokenSurfaceHeadersMiddleware` above it, it also covers the 405s and
APPEND_SLASH redirects a view-level call never sees.

WHY NOT `allauth.core.ratelimit.consume`, which the two throttled surfaces in this repo
already use: its public wrapper does not expose `limit_get`, and the implementation
beneath it exempts GET outright. That is right for the form endpoints it was written for
(a login page's GET is free, its POST is not) and exactly wrong here, because on these
surfaces the GET *is* the act — opening `/t/<token>/` mints a session, and opening
`/d/<token>/` renders a week of the family's life. So this reaches one level down to
`allauth.core.internal.ratelimit` to pass `limit_get=True`, and keeps everything else
allauth's: the same shared cache, the same key derivation, the same `ACCOUNT_RATE_LIMITS`
config block, and the same `respond_429`, which renders the product's own calm page
(`src/templates/429.html`) rather than a bare status line.

THE NUMBERS, and why they are generous (settings.ACCOUNT_RATE_LIMITS):

* `family_link` — 240 opens per 10 minutes per IP. The binding case is a whole family
  behind ONE home address: a household of eight opening the same invite, each retrying a
  few times through password-validator complaints, is perhaps 40; a grandparent who
  refreshes her page because she is not sure it worked is perhaps 20. 240 leaves a factor
  of five over the worst realistic case, and is still only four requests a second
  sustained, which is a bound on cost rather than on people.
* `family_link_action` — 60 acts per 10 minutes per IP, for the explicit POST behind one
  of those links (confirm, unsubscribe, set a new password, break-glass). Acts are rarer
  than opens by an order of magnitude and every one of them writes.

PER IP ONLY, and that is deliberate rather than an omission. The credential limits in
settings all carry a `/key` component so an attacker rotating IPs still hits an
account-scoped lockout. There is no account here until the token resolves, and keying on
the TOKEN would invert the control: it would do nothing against guessing (each guess is a
different key) while capping how many of a family can open the one link they were all
sent. So: per IP, sized for a household, and the token's own 256 bits answer guessing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from allauth.account import app_settings as account_settings
from allauth.core import ratelimit
from allauth.core.internal import ratelimit as internal_ratelimit
from django.http import HttpRequest, HttpResponse

# Opening a link somebody sent you.
LINK = "family_link"
# The explicit POST behind one: confirming, unsubscribing, setting a password.
LINK_ACTION = "family_link_action"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Every path prefix under which an unauthenticated request carries a bearer credential.
# Kept as prefixes, like `TokenSurfaceHeadersMiddleware`'s own list, so it covers the
# failure shapes a view never sees (a 405, an APPEND_SLASH 301) as well as the pages.
# `test_bearer_surfaces_are_rate_limited` walks the live URL resolver and fails on any
# credential-capturing route that is neither listed here nor excused below, so a new
# bearer surface cannot ship unthrottled.
THROTTLED_PREFIXES = (
    "/t/",  # the no-login link: a GET that mints a session
    "/d/",  # the web view of an emailed family update
    "/join/",  # the invite
    "/get-back-in/",  # the admin-issued recovery link (BY-01)
    "/break-glass/",  # the console-minted admin reset (S-805, issue 173)
    "/digest/confirm/",
    "/digest/unsubscribe/",
)

# Credential-bearing routes deliberately left out, each with the reason. A list of
# exceptions with reasons is the difference between a decision and an oversight.
UNTHROTTLED_WITH_REASON = {
    "/media/": (
        "one emailed family update fans out into a request per photograph, so a "
        "per-request limit here would charge a grandparent twenty units for one page and "
        "refuse her the second one. The media view's audience re-check is the control "
        "that matters on this path; if this is ever throttled it has to be per PAGE."
    ),
    "/accounts/": (
        "allauth's own credential routes (password reset, email confirmation) carry "
        "allauth's own limits from the same ACCOUNT_RATE_LIMITS block. A second limit on "
        "top would be two answers to one question."
    ),
}


def refuse_if_over_limit(request: HttpRequest) -> HttpResponse | None:
    """The 429 page if this client has been over the limit, else None.

    Exposed separately from the middleware so a view can take the limit explicitly if it
    ever needs to — and so the numbers can be exercised directly in a test without
    driving a whole request.
    """
    action = LINK if (request.method or "GET").upper() in _SAFE_METHODS else LINK_ACTION
    usage = internal_ratelimit.consume(
        request=request,
        config=account_settings.RATE_LIMITS,
        action=action,
        limit_get=True,
    )
    if usage is None:
        return cast(HttpResponse, ratelimit.respond_429(request))  # allauth is untyped
    return None


class FamilyLinkThrottleMiddleware:
    """Bound every request under a bearer-link prefix, before the view runs.

    Listed LAST in MIDDLEWARE, which is the position that matters: the 429 page extends
    `core/base.html`, so rendering it needs the session, `request.user` and the CSP nonce
    that the middleware above this one set up. Listed first, the refusal would 500.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith(THROTTLED_PREFIXES):
            refused = refuse_if_over_limit(request)
            if refused is not None:
                return refused
        return self.get_response(request)
