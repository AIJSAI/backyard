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
from core.models import (
    Member,
    NotificationPreference,
    Pod,
    PodMembership,
    PushSubscription,
    Yard,
)

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
  const bytesToB64url = b64url;
  const b64urlToBytes = (value) => {
    const padded = (value + '='.repeat((4 - value.length % 4) % 4))
      .replace(/-/g, '+').replace(/_/g, '/');
    const raw = atob(padded);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) { bytes[i] = raw.charCodeAt(i); }
    return bytes;
  };
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
  // `options.applicationServerKey` is what a real PushSubscription exposes and what the
  // page compares against the key rendered into it, so the stub carries it too: the
  // subscription remembers the key it was MADE with, which is the whole point of the
  // check (a rotation changes the page's key and not the browser's registration).
  const wrap = (json) => ({
    endpoint: json.endpoint,
    toJSON: () => json,
    options: { applicationServerKey: b64urlToBytes(json.madeWith).buffer },
    unsubscribe: async () => {
      write(subKey, '');
      window.__backyardUnsubscribed = true;
      return true;
    }
  });

  navigator.serviceWorker.ready.then((registration) => {
    registration.pushManager.subscribe = async (options) => {
      const json = await make();
      json.madeWith = bytesToB64url(new Uint8Array(options.applicationServerKey));
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


def test_a_double_tap_makes_one_device_and_no_error(
    live_server: Any, playwright: Playwright, settings: Any
) -> None:
    """A slow phone gets tapped twice. The page's in-flight guard is what stops the two
    subscribes; the server's once-retried savepoint is the belt behind it. Either way the
    member ends with one device and no failure sentence."""
    cookie = _seed(settings)
    browser, page = _page(playwright, live_server.url, cookie, allow=True)
    try:
        page.goto(f"{live_server.url}/settings/notifications/")
        turn_on = page.get_by_role("button", name="Turn On Notifications")
        expect(turn_on).to_be_visible()
        # dispatchEvent rather than two taps: it fires both clicks in one task, which is
        # what a double tap does and what a second tap after a reload would not.
        page.evaluate(
            """() => {
              const b = document.querySelector('[data-push-on]');
              b.dispatchEvent(new MouseEvent('click', { bubbles: true }));
              b.dispatchEvent(new MouseEvent('click', { bubbles: true }));
            }"""
        )
        page.wait_for_function("() => !!document.querySelector('ul.devices')", timeout=15_000)
        expect(page.locator("ul.devices > li")).to_have_count(1)
        expect(page.get_by_text("That did not save.")).to_be_hidden()
        assert PushSubscription.objects.count() == 1
        _let_the_server_finish(page)
    finally:
        page.context.close()
        browser.close()


def test_a_row_the_server_forgot_is_re_announced_exactly_once(
    live_server: Any, playwright: Playwright, settings: Any
) -> None:
    """D5: the browser's registration outlives the server's row.

    A push service answering 404/410, a run of failed sends, or a removal all delete the
    row while the phone keeps its registration — so the page would read ON with Your
    Devices empty beside it. It re-announces, exactly once, and then settles.
    """
    cookie = _seed(settings)
    browser, page = _page(playwright, live_server.url, cookie, allow=True)
    try:
        page.goto(f"{live_server.url}/settings/notifications/")
        page.get_by_role("button", name="Turn On Notifications").tap()
        page.wait_for_function("() => !!document.querySelector('ul.devices')", timeout=15_000)
        assert PushSubscription.objects.count() == 1

        # What a push service's 410 does, from the server's side only.
        PushSubscription.objects.all().delete()
        page.goto(f"{live_server.url}/settings/notifications/")
        page.wait_for_function("() => !!document.querySelector('ul.devices')", timeout=15_000)
        expect(page.locator("ul.devices > li")).to_have_count(1)
        assert PushSubscription.objects.count() == 1

        # ...and it SETTLES. One more load with the row present must not re-announce or
        # reload again; a loop here would be a page a relative cannot read.
        page.goto(f"{live_server.url}/settings/notifications/")
        expect(
            page.get_by_role("button", name="Turn Off Notifications On This Device")
        ).to_be_visible()
        page.wait_for_timeout(1200)
        assert PushSubscription.objects.count() == 1
        expect(page.locator("ul.devices > li")).to_have_count(1)
        _let_the_server_finish(page)
    finally:
        page.context.close()
        browser.close()


# A registration the server will NOT take: the host is nobody's push service, so the real
# subscribe route refuses it with the real message. Used to exercise the reload-loop guard
# without stubbing the server's answer — `page.route` cannot see this fetch anyway, because
# the page is controlled by the service worker and Playwright does not intercept a request
# that passes through one.
_A_REGISTRATION_THE_SERVER_REFUSES = """
(() => {
  // Granted, and a registration in hand: the two halves the page reads as "on". Added
  // after _BROWSER_QUIRKS so this definition and this getSubscription are the live ones.
  Object.defineProperty(Notification, 'permission', {
    get: () => 'granted', configurable: true
  });
  const endpoint = 'https://not-a-push-service.example/x';
  const subscription = {
    endpoint,
    toJSON: () => ({ endpoint, keys: { p256dh: 'AAAA', auth: 'BBBB' } }),
    unsubscribe: async () => true
  };
  navigator.serviceWorker.ready.then((registration) => {
    registration.pushManager.getSubscription = async () => subscription;
  });
})();
"""


def test_a_registration_made_with_the_same_key_is_still_live(
    live_server: Any, playwright: Playwright, settings: Any
) -> None:
    """The guard must not fire on the ordinary case. Same key, so the re-announce this
    test's sibling covers still happens and the page still reads ON."""
    cookie = _seed(settings)
    browser, page = _page(playwright, live_server.url, cookie, allow=True)
    try:
        page.goto(f"{live_server.url}/settings/notifications/")
        page.get_by_role("button", name="Turn On Notifications").tap()
        page.wait_for_function("() => !!document.querySelector('ul.devices')", timeout=15_000)
        PushSubscription.objects.all().delete()

        page.goto(f"{live_server.url}/settings/notifications/")
        page.wait_for_function("() => !!document.querySelector('ul.devices')", timeout=15_000)
        expect(
            page.get_by_role("button", name="Turn Off Notifications On This Device")
        ).to_be_visible()
        assert PushSubscription.objects.count() == 1
        assert page.evaluate("() => !!window.__backyardUnsubscribed") is False
        _let_the_server_finish(page)
    finally:
        page.context.close()
        browser.close()


def test_a_registration_made_with_an_older_key_is_cleared_and_turn_on_comes_back(
    live_server: Any, playwright: Playwright, settings: Any
) -> None:
    """F-B: after a VAPID rotation the browser keeps a registration every push is now
    refused for, and the page read ON for ever.

    Rotation is entirely server-side, so nothing tells the browser. Before this the page
    hid Turn On, re-announced the dead registration on every visit, watched the row get
    deleted after five 403s, and re-created it on the next visit — so the cure the
    self-host runbook documents ("each relative turns notifications on again") could never
    be reached. The rotation here is the real one: a new pair from the same command the
    runbook tells an operator to run.
    """
    cookie = _seed(settings)
    browser, page = _page(playwright, live_server.url, cookie, allow=True)
    try:
        page.goto(f"{live_server.url}/settings/notifications/")
        page.get_by_role("button", name="Turn On Notifications").tap()
        page.wait_for_function("() => !!document.querySelector('ul.devices')", timeout=15_000)
        assert PushSubscription.objects.count() == 1

        # THE ROTATION. The operator generates a new pair and restarts; the server also
        # forgets the row, which is what five 403s would have done by then.
        rotated_public, rotated_private = generate_pair()
        settings.VAPID_PUBLIC_KEY = rotated_public
        settings.VAPID_PRIVATE_KEY = rotated_private
        PushSubscription.objects.all().delete()

        subscribes: list[str] = []
        page.on(
            "request",
            lambda request: (
                subscribes.append(request.url)
                if request.url.endswith("/settings/notifications/subscribe/")
                else None
            ),
        )
        page.goto(f"{live_server.url}/settings/notifications/")
        expect(page.get_by_role("button", name="Turn On Notifications")).to_be_visible(
            timeout=15_000
        )
        page.wait_for_timeout(1200)  # long enough for a re-announce to have gone out
        assert page.evaluate("() => !!window.__backyardUnsubscribed") is True, (
            "the stale registration was left in the browser"
        )
        assert subscribes == [], "the dead registration was re-announced to the server"
        assert PushSubscription.objects.count() == 0
        _let_the_server_finish(page)
    finally:
        page.context.close()
        browser.close()


def test_a_toggle_says_it_saved(live_server: Any, playwright: Playwright, settings: Any) -> None:
    """F-I: the two toggles save the instant they change, and only spoke on failure.

    With the e-mail section's Save Changes button in plain sight just below them, a
    relative who unticked Replies had no way to tell whether it took or whether the button
    underneath was waiting for them. Read off the 390px screenshots, not off the code.
    """
    cookie = _seed(settings)
    browser, page = _page(playwright, live_server.url, cookie, allow=True)
    try:
        page.goto(f"{live_server.url}/settings/notifications/")
        page.get_by_role("button", name="Turn On Notifications").tap()
        page.wait_for_function("() => !!document.querySelector('ul.devices')", timeout=15_000)

        replies = page.get_by_label("Replies")
        expect(replies).to_be_checked()
        expect(page.get_by_text("Saved.")).to_be_hidden()

        replies.uncheck()
        expect(page.get_by_text("Saved.")).to_be_visible(timeout=10_000)
        expect(page.get_by_text("That did not save.")).to_be_hidden()

        # ...and the server really holds what the page just claimed.
        preference = NotificationPreference.objects.get()
        assert preference.push_replies is False
        assert preference.push_new_posts is True
        _let_the_server_finish(page)
    finally:
        page.context.close()
        browser.close()


def test_a_refused_re_announce_shows_the_off_state_instead_of_reloading_forever(
    live_server: Any, playwright: Playwright, settings: Any
) -> None:
    """The reload-loop guard. A re-announce can be refused — the device cap, the feature
    switched off between the two loads, a value the validator will not take — and a page
    that reloads on refusal comes back, re-announces, is refused and reloads forever.

    The refusal here is REAL: the browser is made to hold a registration on a host that is
    not a push service, so `subscribe` answers its own 400 and nothing about the server is
    stubbed. (It could not be stubbed from the page anyway: this page is controlled by the
    service worker, and Playwright does not intercept a request that passes through one.)
    """
    cookie = _seed(settings)
    browser, page = _page(playwright, live_server.url, cookie, allow=True)
    page.context.add_init_script(_A_REGISTRATION_THE_SERVER_REFUSES)
    try:
        page.goto(f"{live_server.url}/settings/notifications/")
        expect(page.get_by_text("That did not save.")).to_be_visible(timeout=15_000)
        expect(page.get_by_role("button", name="Turn On Notifications")).to_be_visible()
        expect(page.get_by_role("heading", name="Your Devices")).to_have_count(0)
        page.wait_for_timeout(1500)  # long enough for a loop to have gone round twice
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


# --- the service worker's same-origin guard, exercised rather than grepped ---------------


def test_the_served_worker_refuses_every_hostile_url(
    live_server: Any, playwright: Playwright, settings: Any
) -> None:
    """Run the SERVED worker's `backyardPath` against real values in a real URL parser.

    `test_pwa.py` asserts the guard's clauses are present in the response; this asserts
    they WORK, which is the only way to catch the class of defect that put this test here.
    A leading slash followed by a backslash passes both character tests and resolves to
    another origin under the WHATWG parser, so a substring test on the old two-clause
    guard was green while the guard was bypassed.

    The worker source is served into a ROUTED page of this test's own, on the live
    server's origin so `self.location.origin` is the real one, and with no
    Content-Security-Policy so an inline script runs. The product's own pages carry a
    nonce-based policy with no `unsafe-eval`, so neither `eval` nor `new Function` can
    load the source there, and `page.add_script_tag` injects an un-nonced tag the policy
    refuses. Nothing about the product changes for this: the bytes under test are exactly
    what `/service-worker.js` served.

    Defining the worker in a window is safe: `self` is the window, `addEventListener`
    exists, and `self.registration` / `self.clients` are touched only inside handlers that
    nothing here fires.
    """
    _seed(settings)
    worker = Client().get("/service-worker.js").content.decode()
    browser = playwright.chromium.launch()
    context = browser.new_context()
    page = context.new_page()
    try:
        page.route(
            "**/a-probe-page-that-is-not-a-route",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body=f"<!doctype html><script>{worker}</script>",
            ),
        )
        page.goto(f"{live_server.url}/a-probe-page-that-is-not-a-route")
        feed = f"{live_server.url}/feed/"

        # The good case, so the table below is not vacuously "everything is the feed".
        assert page.evaluate("() => backyardPath('/posts/12/')") == f"{live_server.url}/posts/12/"

        hostile = {
            "protocol-relative": "//elsewhere.example/x",
            # THE ONE THIS TEST EXISTS FOR. The parser reads the backslash as a second
            # slash under a special scheme, so this lands on elsewhere.example while
            # passing "starts with one slash and not two".
            "slash-backslash": "/\\elsewhere.example/x",
            "slash-backslash-backslash": "/\\\\elsewhere.example/x",
            "absolute": "https://elsewhere.example/x",
            "scheme-relative-with-scheme": "javascript:alert(1)",
            "empty": "",
            "a-bare-backslash": "\\\\elsewhere.example/x",
        }
        for name, value in hostile.items():
            assert page.evaluate("(v) => backyardPath(v)", value) == feed, (
                f"backyardPath let {name} ({value!r}) through"
            )
        # The non-string arm. Its own loop and its own annotation: a payload that is not a
        # string at all is what a malformed or truncated push body looks like.
        not_strings: tuple[tuple[str, Any], ...] = (
            ("null", None),
            ("a number", 12),
            ("an object", {"url": "/x"}),
        )
        for name, other in not_strings:
            assert page.evaluate("(v) => backyardPath(v)", other) == feed, (
                f"backyardPath let {name} through"
            )
    finally:
        page.context.close()
        browser.close()
