"""The Get The App page, in the three browsers a relative actually opens it in (S-103).

Everything on that page is decided client-side — which platform's steps come first, whether
this is an in-app browser, whether Chrome will offer an install — so a request-client test
can only prove the markup shipped. This is the half that proves the DECISION: real engines,
real user agents, mobile emulation, the script running under the enforced CSP.

WebKit is the engine iOS Safari uses and Chromium the one Android Chrome uses, the same
substitution `test_onboarding_mobile.py` makes and for the same reason: there are no phones
in CI. What that cannot prove is named in the report that ships with this work — an actual
iPhone is the only thing that proves Add to Home Screen does what the three steps say.

Excluded from the default unit run (`-m 'not e2e'`); runs in the browser job (`make e2e`).
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from playwright.sync_api import Playwright, expect

from core.models import Member, Pod, PodMembership, Yard

User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"

# Playwright's sync API drives the browser from a greenlet event loop, which Django reads as
# an async context and refuses ORM calls from. Set before any fixture runs a query, exactly
# as test_onboarding_mobile.py does.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def _a_member_with_a_session() -> str:
    """One member, signed in server-side. The session cookie is injected into each browser
    context, so these drive the INSTALL page rather than re-testing the sign-in form."""
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="The cousins", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = User.objects.create_user(username="installcousin")
    member = Member.objects.create(display_name="Cousin Reed", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)  # a real DB session the live server shares
    return str(client.cookies["sessionid"].value)


def _open(browser: Any, device: dict[str, Any], base_url: str, cookie: str) -> Any:
    context = browser.new_context(**device)
    context.add_cookies([{"name": "sessionid", "value": cookie, "url": base_url}])
    page = context.new_page()
    page.goto(f"{base_url}/app/")
    return page


def _order(page: Any) -> list[str]:
    """The platform sections as the reader meets them, top to bottom."""
    found = page.eval_on_selector_all(
        "[data-install-platform]", "nodes => nodes.map(n => n.dataset.installPlatform)"
    )
    return [str(name) for name in found]


def test_each_phone_is_shown_its_own_way_in(live_server: Any, playwright: Playwright) -> None:
    cookie = _a_member_with_a_session()
    base_url = live_server.url

    # --- Android Chrome: its steps first, and a real Install button -------------------
    chromium = playwright.chromium.launch()
    try:
        device = dict(playwright.devices["Pixel 5"])
        page = _open(chromium, device, base_url, cookie)
        assert _order(page) == ["android", "ios"], "an Android phone is shown Apple's steps first"
        # The other platform stays REACHABLE: a relative on a phone may be reading this to
        # tell a parent what to tap. It is below, not gone.
        # `exact`, because the Android steps below carry Chrome's own spelling of the
        # same label ("Add to Home screen"): each platform is quoted as it writes it.
        expect(page.get_by_text("Add to Home Screen", exact=True)).to_be_visible()

        # The install control is hidden until the browser says it can install, because a
        # button whose prompt() would throw is worse than the menu steps it replaces.
        offer = page.locator("[data-install-now]")
        expect(offer).to_be_hidden()
        expect(page.locator('[data-install-platform="android"]')).to_be_visible()

        # Chrome fires `beforeinstallprompt` only against a real installability check, which
        # a headless run over http does not pass — so the EVENT is synthesised and the
        # product's own wiring (preventDefault, keep it, prompt() on tap) is what is proven.
        page.evaluate(
            """() => {
                const event = new Event('beforeinstallprompt', { cancelable: true });
                event.prompt = () => { window.__promptedInstall = true; };
                window.dispatchEvent(event);
            }"""
        )
        expect(offer).to_be_visible()
        expect(page.locator('[data-install-platform="android"]')).to_be_hidden()
        assert page.evaluate("() => window.__promptedInstall === undefined"), (
            "the event was consumed on arrival; it must be kept for the member's own tap"
        )

        page.get_by_role("button", name="Install App", exact=True).click()
        assert page.evaluate("() => window.__promptedInstall === true"), (
            "tapping Install App did not call prompt() on the kept event"
        )
        # ...and the menu steps come back, so a dismissed sheet is not a dead end.
        expect(offer).to_be_hidden()
        expect(page.locator('[data-install-platform="android"]')).to_be_visible()

        # --- an in-app browser: told to leave it first --------------------------------
        viewer = dict(device)
        viewer["user_agent"] = (
            device["user_agent"] + " Instagram 300.0.0.0.0 Android (34/14; 420dpi)"
        )
        inside = _open(chromium, viewer, base_url, cookie)
        warning = inside.locator("[data-install-webview]")
        expect(warning).to_be_visible()
        expect(inside.get_by_role("heading", name="Open In Browser")).to_be_visible()
        # FIRST: every step below it is wasted until they are out of the viewer.
        platforms = inside.locator("[data-install-platforms]")
        assert (warning.bounding_box() or {})["y"] < (platforms.bounding_box() or {})["y"], (
            "the Open In Browser guidance is not above the steps it has to precede"
        )
    finally:
        chromium.close()

    # --- iPhone Safari: Apple's steps first ------------------------------------------
    webkit = playwright.webkit.launch()
    try:
        page = _open(webkit, dict(playwright.devices["iPhone 13"]), base_url, cookie)
        assert _order(page) == ["ios", "android"], "an iPhone is not shown its own steps first"
        expect(page.get_by_role("heading", name="iPhone And iPad")).to_be_visible()
        expect(page.get_by_text("Add to Home Screen", exact=True)).to_be_visible()
        # WebKit fires no beforeinstallprompt at all, which is why the three steps exist.
        expect(page.locator("[data-install-now]")).to_be_hidden()
    finally:
        webkit.close()
