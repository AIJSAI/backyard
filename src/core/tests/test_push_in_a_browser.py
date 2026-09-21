"""Turning notifications on, in a real browser (S-107, e2e).

WHAT IS REAL, and it is worth being exact, because "an e2e passed" is the kind of claim
that hides a stub:

REAL — the page, the script on it and every branch it takes; the service worker really
registering and `navigator.serviceWorker.ready` really resolving; the permission ANSWER
(`Notification.requestPermission()` resolves from the browser context's own grant, and
resolves "denied" in the second test with nothing granted); the `fetch` to
`/settings/notifications/subscribe/` carrying Django's CSRF token read out of the form on
the page; the server's endpoint and key validation; the row written; the reload; and the
device row the member then reads, rendered server-side.

STUBBED — two things, both measured headless-Chromium artefacts rather than product
shortcuts, and both in one init script:

1. `pushManager.subscribe` / `getSubscription`. Headless Chromium has no push service to
   register with, so the real call rejects. The stub returns a subscription of the real
   shape — an `fcm.googleapis.com` endpoint and a genuine uncompressed P-256 point from
   WebCrypto — so the server's `validate_endpoint` and `validate_p256dh` are doing real
   work on real bytes rather than waving a fixture through.
2. The initial value of `Notification.permission`, and ONLY in the tests that turn
   notifications on. Measured 2026-09-20 on this Chromium: with
   `context.grant_permissions(["notifications"])` the getter still reads `"denied"` while
   `Notification.requestPermission()` resolves `"granted"`. A first-time member's browser
   reads `"default"`, so the script restores that and lets the REAL `requestPermission()`
   decide, recording whatever it answers.

   The REFUSAL test stubs nothing at all. Headless Chromium natively reports
   `Notification.permission === "denied"`, which is precisely the state a member who
   blocked Backyard is in, so the page's own code is what reads it and decides. (The other
   road was not available: measured, `requestPermission()` in headless resolves `"default"`
   whether the permission is ungranted or explicitly denied over CDP, so a refusal cannot
   be produced from the tap.)

NOT COVERED BY ANY OF THIS, and only a real phone can answer it: whether iOS grants the
permission from this button's gesture inside an installed Home Screen app, whether Apple's
push service accepts this instance's VAPID assertion, whether a notification arrives, and
what it looks like on a lock screen.

Hygiene follows test_the_photo_button_in_a_browser.py: unique slugs and usernames per
call, a bounded networkidle drain, and the context closed before the browser.
"""

from __future__ import annotations

import os
import secrets
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from playwright.sync_api import Page, Playwright, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from core.management.commands.generate_vapid_keys import generate_pair
from core.models import Member, Pod, PodMembership, PushSubscription, Yard

User = get_user_model()
_PW = "aX9!mnpq2ffz"
_BACKEND = "django.contrib.auth.backends.ModelBackend"

# See test_onboarding_mobile.py: Playwright's sync API runs on a greenlet loop and Django
# refuses sync ORM calls from it unless told the single-threaded seeding here is safe.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

# The two stubs, in ONE init script so they run before any page script on every navigation
# — including the reload the page performs after a successful subscribe. Both pieces of
# state are kept in localStorage precisely so they survive that reload, which is how the
# browser itself behaves: a registration and a granted permission outlive a page load.
#
# AN IIFE, not an arrow function. `page.evaluate` CALLS a function-shaped string;
# `add_init_script` does not — it evaluates the source, so `() => {...}` there creates a
# function nobody calls and the script silently does nothing. Measured: the stub appeared
# to be installed and every assertion after it read the unpatched browser.
_BROWSER_QUIRKS = """
(() => {
  const permKey = '__backyard_e2e_permission';
  const subKey = '__backyard_e2e_subscription';
  const read = (key) => { try { return localStorage.getItem(key); } catch (e) { return null; } };
  const write = (key, value) => { try { localStorage.setItem(key, value); } catch (e) {} };

  // (2) Headless reads "denied" even when the context granted it. A first-time member's
  // browser reads "default"; the real requestPermission() still decides the answer.
  let permission = read(permKey) || 'default';
  Object.defineProperty(Notification, 'permission', {
    get: () => permission,
    configurable: true
  });
  const realRequest = Notification.requestPermission.bind(Notification);
  Notification.requestPermission = async () => {
    const answer = await realRequest();
    permission = answer;
    write(permKey, answer);
    return answer;
  };

  // (1) No push service is reachable from a headless browser, so subscribe() rejects.
  const b64url = (bytes) => btoa(String.fromCharCode.apply(null, bytes))
    .replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=+$/, '');
  const make = async () => {
    const pair = await crypto.subtle.generateKey(
      { name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
    const raw = new Uint8Array(await crypto.subtle.exportKey('raw', pair.publicKey));
    return {
      endpoint: 'https://fcm.googleapis.com/fcm/send/'
        + b64url(crypto.getRandomValues(new Uint8Array(16))),
      keys: {
        p256dh: b64url(raw),
        auth: b64url(crypto.getRandomValues(new Uint8Array(16)))
      }
    };
  };
  const wrap = (json) => ({
    endpoint: json.endpoint,
    toJSON: () => json,
    unsubscribe: async () => { write(subKey, ''); return true; }
  });

  navigator.serviceWorker.ready.then((registration) => {
    registration.pushManager.subscribe = async () => {
      const json = await make();
      write(subKey, JSON.stringify(json));
      return wrap(json);
    };
    registration.pushManager.getSubscription = async () => {
      const stored = read(subKey);
      return stored ? wrap(JSON.parse(stored)) : null;
    };
  });
})();
"""


def _seed(settings: Any) -> str:
    """A member in a household, on an instance with web push configured.

    Identifiers are unique per call: a `transaction=True` teardown can lose its flush to a
    request the live server is still answering, and a fixed slug turns that into a
    duplicate-key failure in the NEXT test, which is then the one that reads red.
    """
    public, private = generate_pair()
    settings.VAPID_PUBLIC_KEY = public
    settings.VAPID_PRIVATE_KEY = private
    settings.VAPID_SUBJECT = "mailto:admin@example.test"
    settings.PUSH_ENABLED = True

    tag = secrets.token_hex(4)
    yard = Yard.objects.create(name="Maternal", slug=f"maternal-{tag}")
    pod = Pod.objects.create(name="The cousins", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = User.objects.create_user(username=f"poster-{tag}", password=_PW)
    member = Member.objects.create(display_name="Ann Poster", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)  # a real DB session the live server shares
    return client.cookies["sessionid"].value


def _page(playwright: Playwright, base_url: str, cookie: str, *, allow: bool) -> tuple[Any, Page]:
    """A signed-in Chromium page whose answer to the permission prompt is already decided.

    Granted or withheld through the BROWSER CONTEXT, which is where a person's answer
    really lives: the page's own `Notification.requestPermission()` then resolves with that
    answer rather than waiting on a dialog nothing can click.
    """
    browser = playwright.chromium.launch()
    context = browser.new_context(**dict(playwright.devices["Pixel 5"]))
    context.add_cookies([{"name": "sessionid", "value": cookie, "url": base_url}])
    if allow:
        context.grant_permissions(["notifications"], origin=base_url)
        context.add_init_script(_BROWSER_QUIRKS)
    # ...and nothing at all when the answer is no: headless Chromium already reports
    # `Notification.permission === "denied"`, which is the state under test.
    return browser, context.new_page()


def _let_the_server_finish(page: Page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightTimeoutError:
        pass  # hygiene before the flush, never an assertion


def test_the_settings_button_subscribes_this_device_and_the_page_lists_it(
    live_server: Any, playwright: Playwright, settings: Any
) -> None:
    cookie = _seed(settings)
    browser, page = _page(playwright, live_server.url, cookie, allow=True)
    try:
        page.goto(f"{live_server.url}/settings/notifications/")
        expect(page.get_by_role("heading", name="On This Device")).to_be_visible()
        turn_on = page.get_by_role("button", name="Turn On Notifications")
        expect(turn_on).to_be_visible()
        # At rest there is no device list at all, so the assertions after the tap are not
        # reading something that was on the page before it.
        expect(page.get_by_role("heading", name="Your Devices")).to_have_count(0)
        assert PushSubscription.objects.count() == 0

        turn_on.tap()

        # The page reloads itself after a successful subscribe, so the row the member reads
        # is a row that exists on the server rather than one drawn in JavaScript.
        page.wait_for_function("() => !!document.querySelector('ul.devices')", timeout=15_000)
        expect(page.get_by_role("heading", name="Your Devices")).to_be_visible()
        row = page.locator("ul.devices > li").first
        expect(row).to_contain_text("Android")  # the coarse label, from the Pixel 5 agent
        expect(row).to_contain_text("Added")
        expect(row.get_by_role("button", name="Remove")).to_be_visible()

        # Turn On is gone, and the section now offers the off switch and both toggles.
        expect(
            page.get_by_role("button", name="Turn Off Notifications On This Device")
        ).to_be_visible()
        expect(page.get_by_role("button", name="Turn On Notifications")).to_be_hidden()
        expect(page.get_by_label("New Posts")).to_be_checked()
        expect(page.get_by_label("Replies")).to_be_checked()

        # The server really wrote a row, from bytes it really validated.
        device = PushSubscription.objects.get()
        assert device.endpoint.startswith("https://fcm.googleapis.com/fcm/send/")
        assert device.label == "Android"
        # ...and the capability is nowhere in the page a screenshot would capture.
        assert device.endpoint not in page.content()
        _let_the_server_finish(page)
    finally:
        page.context.close()
        browser.close()


def test_turning_them_off_again_removes_the_row(
    live_server: Any, playwright: Playwright, settings: Any
) -> None:
    """The other half of the same control, and the one the sign-out page reuses: the
    server row goes, and the browser's own registration goes with it."""
    cookie = _seed(settings)
    browser, page = _page(playwright, live_server.url, cookie, allow=True)
    try:
        page.goto(f"{live_server.url}/settings/notifications/")
        page.get_by_role("button", name="Turn On Notifications").tap()
        page.wait_for_function("() => !!document.querySelector('ul.devices')", timeout=15_000)
        assert PushSubscription.objects.count() == 1

        page.get_by_role("button", name="Turn Off Notifications On This Device").tap()
        page.wait_for_function("() => !document.querySelector('ul.devices')", timeout=15_000)
        expect(page.get_by_role("button", name="Turn On Notifications")).to_be_visible()
        assert PushSubscription.objects.count() == 0
        _let_the_server_finish(page)
    finally:
        page.context.close()
        browser.close()


def test_a_browser_that_refuses_permission_says_so_plainly(
    live_server: Any, playwright: Playwright, settings: Any
) -> None:
    """Denied is not an error state to hide, and it is not a dead button either. A member
    who blocked Backyard is told where the answer lives, because the product cannot change
    it from here — and is NOT offered a control that can only fail.

    NOTHING IS STUBBED IN THIS TEST. Headless Chromium reports the denied permission by
    itself, and the page's own script is what reads it and decides.
    """
    cookie = _seed(settings)
    browser, page = _page(playwright, live_server.url, cookie, allow=False)
    try:
        page.goto(f"{live_server.url}/settings/notifications/")
        expect(page.get_by_text("Notifications are blocked for Backyard")).to_be_visible(
            timeout=15_000
        )
        expect(page.get_by_role("button", name="Turn On Notifications")).to_be_hidden()
        assert PushSubscription.objects.count() == 0
        assert page.get_by_role("heading", name="Your Devices").count() == 0
        _let_the_server_finish(page)
    finally:
        page.context.close()
        browser.close()
