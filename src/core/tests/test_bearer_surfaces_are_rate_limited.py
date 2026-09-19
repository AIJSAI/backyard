"""Every unauthenticated bearer surface carries a limit, and refuses calmly (S2, 173).

The surfaces a stranger reaches with nothing but a URL — the invite join page, the
no-login link, the web view of an emailed family update with its confirm and unsubscribe
pages, the "get back in" link, and break-glass — could be asked for as fast as anyone
liked. Each one hits the database several times, on a box with three gunicorn workers and
the family's photographs on the same disk.

Two properties, and the second is not a detail: whoever trips this is a grandparent
refreshing a page or a family opening one invite from six phones, so the answer must be
the product's own calm page and never a bare 429. The limits are sized so that neither of
those people ever sees it — see `core/throttling` for the numbers and the reasoning.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import digest_links, elder_tokens, invites, recovery, throttling
from core.breakglass import break_glass_tokens
from core.models import DigestIssue, Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture(autouse=True)
def _clean_rate_limit_cache() -> Any:
    """The limit rides the shared DatabaseCache, which outlives a test. Clear it around
    each one so a burst in one test cannot refuse a request in the next."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def world() -> dict[str, Any]:
    yard = Yard.objects.create(name="One side", slug="one-side")
    pod = Pod.objects.create(name="A household", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = User.objects.create_user(username="gran")
    member = Member.objects.create(display_name="Gran", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    return {"yard": yard, "pod": pod, "member": member, "user": user}


def _elder_link(member: Member) -> str:
    return reverse("elder_enter", args=[elder_tokens.mint(member)])


def _digest_link(member: Member, yard: Yard) -> str:
    now = timezone.now()
    issue = DigestIssue.objects.create(
        member=member,
        yard=yard,
        window_start=now - datetime.timedelta(days=7),
        window_end=now + datetime.timedelta(hours=1),
    )
    return reverse("digest_web", args=[digest_links.mint(issue)])


def _join_link(pod: Pod) -> str:
    _invite, raw = invites.mint_invite(pod, None)
    return reverse("join", args=[raw])


def _recovery_link(member: Member) -> str:
    return reverse("recover", args=[recovery.issue(member, issued_by=member)])


def _break_glass_link(user: Any) -> str:
    from django.utils.http import urlsafe_base64_encode

    return reverse(
        "break_glass",
        args=[urlsafe_base64_encode(str(user.pk).encode()), break_glass_tokens.make_token(user)],
    )


def _readable_text(html: str) -> str:
    """The words a person actually reads: markup, inline CSS and scripts removed."""
    without_code = re.sub(r"<(style|script)\b.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", without_code)


def _surfaces(world: dict[str, Any]) -> dict[str, str]:
    """Every unauthenticated bearer URL in the product, built live.

    Enumerated from the routes rather than sampled: the finding was that NONE of these
    had a limit, so a test covering the two that were easiest to build would have been
    the same shape as the gap.
    """
    member, pod, yard = world["member"], world["pod"], world["yard"]
    return {
        "the no-login link": _elder_link(member),
        "the web view of a family update": _digest_link(member, yard),
        "the invite link": _join_link(pod),
        "the get-back-in link": _recovery_link(member),
        "break-glass": _break_glass_link(world["user"]),
    }


@pytest.mark.parametrize(
    "name",
    [
        "the no-login link",
        "the web view of a family update",
        "the invite link",
        "the get-back-in link",
        "break-glass",
    ],
)
def test_each_bearer_surface_refuses_an_unbounded_burst(world: dict[str, Any], name: str) -> None:
    """Fails without the `throttling.refuse_if_over_limit` call in that view: the burst
    runs to completion and the surface answers every single request."""
    url = _surfaces(world)[name]
    client = Client()
    statuses = {client.get(url).status_code for _ in range(400)}
    assert 429 in statuses, f"{name} answered 400 opens in a row without ever refusing"


def test_the_refusal_is_the_products_own_page_not_a_bare_429(world: dict[str, Any]) -> None:
    """Whoever trips this is a relative, so the answer has to be a page written for one.

    Fails without `src/templates/429.html`: allauth's handler429 falls back to its
    built-in `<h1>429 Too Many Requests</h1>`, which is the one thing a grandparent must
    never be handed.
    """
    url = _surfaces(world)["the no-login link"]
    client = Client()
    response = client.get(url)
    for _ in range(400):
        response = client.get(url)
        if response.status_code == 429:
            break
    assert response.status_code == 429
    body = response.content.decode()
    assert "Too Many Requests" not in body, "this is allauth's bare fallback page"
    assert "Just a moment" in body, body[:400]
    assert "Nothing is wrong" in body
    # The product's vocabulary, in the words a person READS: whole words, from the
    # rendered text only. `base.html` carries the whole stylesheet inline, so scanning the
    # raw HTML flags its `.pods` CSS class and the guard fails on something nobody sees.
    words = set(re.findall(r"[a-z]+", _readable_text(body).lower()))
    for jargon in ("pod", "pods", "yard", "yards", "token", "instance", "digest", "throttle"):
        assert jargon not in words, f"the refusal page says {jargon!r} to a relative"


def test_a_grandparent_refreshing_her_page_is_never_refused(world: dict[str, Any]) -> None:
    """The limit is a bound on cost, not on people. Twenty refreshes is what somebody who
    is not sure the page worked actually does, and it must not be near the edge."""
    url = _surfaces(world)["the no-login link"]
    client = Client()
    assert {client.get(url).status_code for _ in range(20)} == {302}


def test_a_family_opening_one_invite_from_one_home_address_is_never_refused(
    world: dict[str, Any],
) -> None:
    """The binding case for the numbers: eight people behind ONE home IP, each loading
    the invite a few times through password-validator complaints. Every request below
    shares an address, which is the whole point."""
    url = _surfaces(world)["the invite link"]
    clients = [Client() for _ in range(8)]
    statuses = {client.get(url).status_code for client in clients for _ in range(5)}
    assert statuses == {200}, statuses


def test_the_act_behind_a_link_is_bounded_separately_from_opening_it(
    world: dict[str, Any],
) -> None:
    """A POST writes; an open does not. They get their own budgets, so a page somebody
    keeps reloading cannot spend the budget for the act, or the reverse."""
    assert throttling.LINK != throttling.LINK_ACTION
    from django.conf import settings

    limits = settings.ACCOUNT_RATE_LIMITS
    assert throttling.LINK in limits and throttling.LINK_ACTION in limits
    # Per IP only, and no `/key` half: there is no account until the token resolves, and
    # keying on the token would cap a family sharing one link while doing nothing about
    # guessing. Asserted so the reasoning in core/throttling cannot silently rot.
    for action in (throttling.LINK, throttling.LINK_ACTION):
        assert limits[action].endswith("/ip"), limits[action]
        assert "/key" not in limits[action], limits[action]


def test_the_limit_covers_get_which_allauths_own_wrapper_exempts() -> None:
    """The reason this module exists at all. `allauth.core.ratelimit.consume` does not
    expose `limit_get`, and the implementation under it returns "allowed" for every GET.
    On these surfaces the GET IS the act, so a throttle that exempts it is decorative."""
    from allauth.account import app_settings as account_settings
    from allauth.core import ratelimit as public_ratelimit
    from django.test import RequestFactory

    request = RequestFactory().get("/t/whatever/")
    for _ in range(10_000):
        if not public_ratelimit.consume(request, action=throttling.LINK):
            pytest.fail("allauth's public wrapper unexpectedly limited a GET")
    assert account_settings.RATE_LIMITS[throttling.LINK], "the action must be configured"
    # And ours does limit it.
    refusals = [throttling.refuse_if_over_limit(request) for _ in range(400)]
    assert any(r is not None for r in refusals)


def test_the_limit_lives_where_a_404_cannot_roll_it_back() -> None:
    """The finding that moved this out of the views, pinned so it cannot come back.

    `ATOMIC_REQUESTS` wraps every view in a transaction and the counter lives in a
    DatabaseCache, so a view that answers an unknown token by RAISING `Http404` takes its
    own counter write down with it. Measured before the move: 400 consecutive requests to
    a bad break-glass URL, all answered, counter still at zero — the throttle live on the
    requests that succeed and dead on the requests an attacker makes.

    Middleware runs outside `make_view_atomic`, so the 404 path counts. Asserted through
    a URL that ALWAYS 404s.
    """
    from django.conf import settings

    assert settings.DATABASES["default"]["ATOMIC_REQUESTS"] is True, (
        "if this is ever turned off, re-read why the throttle is in middleware"
    )
    assert "core.throttling.FamilyLinkThrottleMiddleware" in settings.MIDDLEWARE

    client = Client()
    url = "/break-glass/never-was/a-real-token/"
    statuses = {client.get(url).status_code for _ in range(400)}
    assert statuses == {404, 429}, statuses


def test_every_bearer_route_is_covered_or_excused_by_name() -> None:
    """Walk the live resolver and fail on any credential-capturing route that is neither
    throttled nor excused with a reason.

    Enumerated rather than sampled, and for the reason `test_isolation_registry` gives for
    its own resolver walk: the finding here was that NONE of these had a limit, so a test
    listing the ones somebody remembered would have exactly the shape of the gap.
    """
    from django.urls import get_resolver

    credential_like = re.compile(r"(?i)(token|key|uidb|secret|code)")

    def walk(resolver: Any, prefix: str = "") -> Any:
        for pattern in resolver.url_patterns:
            text = prefix + str(getattr(pattern, "pattern", ""))
            if hasattr(pattern, "url_patterns"):
                yield from walk(pattern, text)
            else:
                yield text

    def captures_a_credential(raw: str) -> bool:
        names = re.findall(r"\(\?P<([^>]+)>", raw)
        for converter in re.findall(r"<([^>]+)>", raw):
            if converter.startswith("int:"):
                continue  # a primary key is an object id, not a capability
            names.append(converter.split(":")[-1])
        return any(credential_like.search(name) for name in names)

    patterns = [f"/{raw}" for raw in walk(get_resolver())]
    assert len(patterns) > 50, f"the resolver walk found only {len(patterns)} patterns"
    bearer = [p for p in patterns if captures_a_credential(p)]
    assert len(bearer) >= 5, "the walk recognised almost no credential routes; it is vacuous"

    covered = throttling.THROTTLED_PREFIXES + tuple(throttling.UNTHROTTLED_WITH_REASON)
    uncovered = [p for p in bearer if not p.startswith(covered)]
    assert not uncovered, (
        "these routes carry a bearer credential and are neither throttled nor excused "
        f"with a reason in core/throttling: {uncovered}"
    )


def test_media_is_deliberately_not_throttled() -> None:
    """Excused BY NAME, with the reason, so its absence reads as a decision. One emailed
    family update fans out into a request per photograph, so a per-request limit there
    would charge a grandparent twenty units for one page."""
    assert "/media/" in throttling.UNTHROTTLED_WITH_REASON
    assert "per PAGE" in throttling.UNTHROTTLED_WITH_REASON["/media/"]
    assert not "/media/x/".startswith(throttling.THROTTLED_PREFIXES)
