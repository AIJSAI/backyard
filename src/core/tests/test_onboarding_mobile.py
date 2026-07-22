"""S-101 cross-browser mobile onboarding e2e.

The acceptance is "from tapping an invite link to standing in my pod's feed ... on my
phone", verified on iOS Safari and Android Chrome. There are no physical devices in CI,
so this drives the real join -> feed flow in the two browser ENGINES those products use
(WebKit for iOS Safari, Chromium for Android Chrome) under mobile device emulation
(viewport, touch, mobile user-agent). It is a real browser rendering and submitting the
real form against a live server, not a request-client simulation.

Excluded from the default unit run (`-m 'not e2e'`); runs in its own CI job with browsers
installed via `pytest -m e2e`.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from playwright.sync_api import Playwright, expect

from core import posting
from core.invites import mint_invite
from core.models import Member, Pod, PodMembership, Yard

# Playwright's sync API drives the browser from a greenlet event loop; Django then refuses
# sync ORM calls from that "async" context. The ORM work here (test seeding, and the live
# server's own queries in its worker thread) is single-threaded and safe, so opt in
# explicitly for this e2e module. Set before any fixture runs a query.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def _seed_invite_and_a_welcome_post() -> tuple[str, str]:
    """A yard + pod whose pod-mate already posted, plus a one-use invite. Returns
    (raw_token, welcome_body) so the e2e can assert the newcomer lands in a feed with
    real family content, not an empty or setup screen."""
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="The cousins")
    pod.yards.set([yard])
    podmate = Member.objects.create(display_name="Aunt Rose")
    PodMembership.objects.create(member=podmate, pod=pod)
    welcome_body = "Welcome to the family feed"
    posting.create_post(author=podmate, pod=pod, audience_yards=[], body=welcome_body)
    _, raw = mint_invite(pod, None, max_uses=1)
    return raw, welcome_body


def _drive_join_to_feed(
    playwright: Playwright,
    *,
    engine: str,
    device: str,
    base_url: str,
    raw: str,
    welcome_body: str,
    username: str,
) -> None:
    device_args: dict[str, Any] = dict(playwright.devices[device])
    browser = getattr(playwright, engine).launch()
    try:
        context = browser.new_context(**device_args)
        page = context.new_page()
        page.goto(f"{base_url}/join/{raw}/")
        # The invite opens a simple join form, never a create-a-community screen.
        assert "community" not in page.content().lower()

        page.fill('input[name="display_name"]', "New Cousin")
        page.fill('input[name="username"]', username)
        page.fill('input[name="password"]', "aX9!mnpq2ffz")
        page.click('button[type="submit"]')

        # Completing signup lands DIRECTLY in the pod feed (S-101 acceptance).
        page.wait_for_url(f"{base_url}/feed/")
        # And they are standing IN the pod feed: the composer and the pod-mate's existing
        # post both render for the brand-new account.
        expect(page.get_by_placeholder("Share something with your family")).to_be_visible()
        expect(page.get_by_text(welcome_body)).to_be_visible()
    finally:
        browser.close()


def test_onboarding_on_ios_safari(live_server: Any, playwright: Playwright) -> None:
    raw, welcome_body = _seed_invite_and_a_welcome_post()
    _drive_join_to_feed(
        playwright,
        engine="webkit",  # the engine iOS Safari uses
        device="iPhone 13",
        base_url=live_server.url,
        raw=raw,
        welcome_body=welcome_body,
        username="iosnewcousin",
    )


def test_onboarding_on_android_chrome(live_server: Any, playwright: Playwright) -> None:
    raw, welcome_body = _seed_invite_and_a_welcome_post()
    _drive_join_to_feed(
        playwright,
        engine="chromium",  # the engine Android Chrome uses
        device="Pixel 5",
        base_url=live_server.url,
        raw=raw,
        welcome_body=welcome_body,
        username="androidnewcousin",
    )
