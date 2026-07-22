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
import re
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from playwright.sync_api import Browser, Playwright, expect

from core import posting
from core.invites import mint_invite
from core.models import Member, Pod, PodMembership, Yard

User = get_user_model()
_PW = "aX9!mnpq2ffz"
_BACKEND = "django.contrib.auth.backends.ModelBackend"

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


# --- mint + hand-over on a real mobile browser (S-212, S-213) ---------------------
#
# The redeem-side e2e above proves a newcomer reaches the feed. These prove the ADMIN
# side of the same acceptance on a real phone: the delegate's mint FORM actually works
# in the browser (its CSRF + intent nonce + submit), the hand-over artifacts render, and
# the minted link then opens. curl cannot prove the form path (no Origin/CSRF), which is
# exactly why the retro called for extending this from redeem to mint+hand-over.


def _seed_admin_yard_and_welcome() -> tuple[str, int, str]:
    """An instance admin (with a login), their yard, and a yard-audience welcome post a
    net-new elder in that side will see. Returns (admin session cookie, yard id, welcome
    body). The session is created server-side and injected into the browser context, so
    these e2es exercise the mint/hand-over path, not the already-covered login UI."""
    yard = Yard.objects.create(name="Riverside", slug="riverside")
    pod = Pod.objects.create(name="Admin household", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = User.objects.create_user(username="theadmin", password=_PW)
    admin = Member.objects.create(display_name="The Admin", user=user, role=Member.INSTANCE_ADMIN)
    PodMembership.objects.create(member=admin, pod=pod)
    welcome_body = "Welcome to the whole family"
    posting.create_post(author=admin, pod=pod, audience_yards=[yard], body=welcome_body)

    client = Client()
    client.force_login(user, backend=_BACKEND)  # a real DB session the live server shares
    return client.cookies["sessionid"].value, yard.id, welcome_body


def _admin_context(
    browser: Browser, device_args: dict[str, Any], base_url: str, cookie: str
) -> Any:
    context = browser.new_context(**device_args)
    context.add_cookies([{"name": "sessionid", "value": cookie, "url": base_url}])
    return context


def _drive_invite_mint_handover_and_redeem(
    playwright: Playwright, *, engine: str, device: str, base_url: str, cookie: str, yard_id: int
) -> None:
    device_args: dict[str, Any] = dict(playwright.devices[device])
    browser = getattr(playwright, engine).launch()
    try:
        # The delegate, on their phone, mints a household invite through the real form.
        page = _admin_context(browser, device_args, base_url, cookie).new_page()
        page.goto(f"{base_url}/members/invite-household/")
        page.fill('input[name="household_name"]', "The Reed family")
        page.select_option('select[name="yard_id"]', str(yard_id))
        page.click('button[type="submit"]')

        # The hand-over artifacts render: the one-time link, the copy affordance, the QR.
        link_field = page.locator("[data-handover-link]")
        expect(link_field).to_be_visible()
        html = page.content()
        assert "data-handover-copy" in html and "<svg" in html
        match = re.search(r"/join/([A-Za-z0-9_-]+)/", link_field.input_value())
        assert match, "no /join link in the minted page"
        raw = match.group(1)

        # A real newcomer, in a FRESH context on their own phone, redeems the link
        # (reconstructed against the live server, since BASE_URL != the live_server port)
        # and lands in the pod feed.
        newcomer = browser.new_context(**device_args).new_page()
        newcomer.goto(f"{base_url}/join/{raw}/")
        newcomer.fill('input[name="display_name"]', "Cousin Reed")
        newcomer.fill('input[name="username"]', f"{engine}reed")
        newcomer.fill('input[name="password"]', _PW)
        newcomer.click('button[type="submit"]')
        newcomer.wait_for_url(f"{base_url}/feed/")
        expect(newcomer.get_by_placeholder("Share something with your family")).to_be_visible()
    finally:
        browser.close()


def _drive_new_elder_mint_and_open(
    playwright: Playwright,
    *,
    engine: str,
    device: str,
    base_url: str,
    cookie: str,
    yard_id: int,
    welcome_body: str,
) -> None:
    device_args: dict[str, Any] = dict(playwright.devices[device])
    browser = getattr(playwright, engine).launch()
    try:
        # The delegate stands up a net-new grandparent through the real new-elder form.
        page = _admin_context(browser, device_args, base_url, cookie).new_page()
        page.goto(f"{base_url}/members/new-elder/")
        page.fill('input[name="elder_name"]', "Grandma Reed")
        page.fill('input[name="household_name"]', "Grandma's house")
        page.select_option('select[name="yard_id"]', str(yard_id))
        page.click('button[type="submit"]')

        link_field = page.locator("[data-handover-link]")
        expect(link_field).to_be_visible()
        match = re.search(r"/t/([A-Za-z0-9_-]+)/", link_field.input_value())
        assert match, "no /t/ elder link in the minted page"
        raw = match.group(1)

        # The elder, in a FRESH context (their shared tablet), opens the handed-over link:
        # it exchanges for a session and lands on the large-text feed with real family
        # content, no login. This is the product's core bet, proven on a real browser.
        elder = browser.new_context(**device_args).new_page()
        elder.goto(f"{base_url}/t/{raw}/")
        elder.wait_for_url(f"{base_url}/e/")
        expect(elder.get_by_text("Grandma Reed")).to_be_visible()  # "Hello, Grandma Reed"
        expect(elder.get_by_text(welcome_body)).to_be_visible()

        # And the elder can send love with one tap (S-602). This is the load-bearing proof
        # of the /e/ Referrer-Policy fix: the react form is a same-origin POST, and under
        # the old no-referrer the browser sent Origin: null and Django's CSRF rejected it,
        # so the elder could never react from a real browser. It must succeed now.
        elder.locator("button", has_text="Send love").click()
        expect(elder.get_by_text("You love this")).to_be_visible()
    finally:
        browser.close()


def test_admin_mint_and_handover_on_ios_safari(live_server: Any, playwright: Playwright) -> None:
    cookie, yard_id, _ = _seed_admin_yard_and_welcome()
    _drive_invite_mint_handover_and_redeem(
        playwright,
        engine="webkit",
        device="iPhone 13",
        base_url=live_server.url,
        cookie=cookie,
        yard_id=yard_id,
    )


def test_admin_mint_and_handover_on_android_chrome(
    live_server: Any, playwright: Playwright
) -> None:
    cookie, yard_id, _ = _seed_admin_yard_and_welcome()
    _drive_invite_mint_handover_and_redeem(
        playwright,
        engine="chromium",
        device="Pixel 5",
        base_url=live_server.url,
        cookie=cookie,
        yard_id=yard_id,
    )


def test_new_elder_mint_and_open_on_ios_safari(live_server: Any, playwright: Playwright) -> None:
    cookie, yard_id, welcome = _seed_admin_yard_and_welcome()
    _drive_new_elder_mint_and_open(
        playwright,
        engine="webkit",
        device="iPhone 13",
        base_url=live_server.url,
        cookie=cookie,
        yard_id=yard_id,
        welcome_body=welcome,
    )


def test_new_elder_mint_and_open_on_android_chrome(
    live_server: Any, playwright: Playwright
) -> None:
    cookie, yard_id, welcome = _seed_admin_yard_and_welcome()
    _drive_new_elder_mint_and_open(
        playwright,
        engine="chromium",
        device="Pixel 5",
        base_url=live_server.url,
        cookie=cookie,
        yard_id=yard_id,
        welcome_body=welcome,
    )


# --- the baseline CSP does not break the inline scripts (S-724) ---------------------
#
# A unit test proves the nonce is in the header and on the <script> tags; only a real
# browser proves the browser then EXECUTES those scripts under the enforced policy. If a
# nonce were missing or mismatched, the browser refuses the inline script and logs a CSP
# violation to the console — which this captures and fails on.


def _drive_csp_inline_script_check(
    playwright: Playwright, *, engine: str, device: str, base_url: str, cookie: str
) -> None:
    device_args: dict[str, Any] = dict(playwright.devices[device])
    browser = getattr(playwright, engine).launch()
    try:
        page = _admin_context(browser, device_args, base_url, cookie).new_page()
        violations: list[str] = []
        page.on(
            "console",
            lambda m: (
                violations.append(m.text)
                if ("Content Security Policy" in m.text or "Refused to" in m.text)
                else None
            ),
        )
        # The feed carries two nonce'd inline scripts (service-worker registration, the
        # client-side resize); if the CSP blocked either, the console records it.
        page.goto(f"{base_url}/feed/")
        expect(page.get_by_placeholder("Share something with your family")).to_be_visible()
        page.wait_for_timeout(400)  # give the inline scripts a beat to run (or be refused)
        assert not violations, (
            f"CSP refused an inline script under the enforced policy: {violations}"
        )
    finally:
        browser.close()


def test_csp_allows_inline_scripts_on_ios_safari(live_server: Any, playwright: Playwright) -> None:
    cookie, _, _ = _seed_admin_yard_and_welcome()
    _drive_csp_inline_script_check(
        playwright, engine="webkit", device="iPhone 13", base_url=live_server.url, cookie=cookie
    )


def test_csp_allows_inline_scripts_on_android_chrome(
    live_server: Any, playwright: Playwright
) -> None:
    cookie, _, _ = _seed_admin_yard_and_welcome()
    _drive_csp_inline_script_check(
        playwright, engine="chromium", device="Pixel 5", base_url=live_server.url, cookie=cookie
    )
