"""The install surface, in the three browsers a relative actually opens it in (S-103).

Two surfaces, one file: the Get The App page, and the card at the foot of every signed-in
page that offers it.

Everything on both is decided client-side — which platform's steps come first, whether this
is an in-app browser, whether Chrome will offer an install, whether this phone has been
offered the home screen before — so a request-client test can only prove the markup
shipped. This is the half that proves the DECISION: real engines, real user agents, mobile
emulation, real localStorage, the scripts running under the enforced CSP.

WebKit is the engine iOS Safari uses and Chromium the one Android Chrome uses, the same
substitution `test_onboarding_mobile.py` makes and for the same reason: there are no phones
in CI. What that cannot prove is named in the report that ships with this work — an actual
iPhone is the only thing that proves Add to Home Screen does what the three steps say.

Excluded from the default unit run (`-m 'not e2e'`); runs in the browser job (`make e2e`).
"""

from __future__ import annotations

import os
import secrets
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone
from playwright.sync_api import Playwright, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from core import elder_tokens
from core.models import Member, Pod, PodMembership, Post, Yard

User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"

# Playwright's sync API drives the browser from a greenlet event loop, which Django reads as
# an async context and refuses ORM calls from. Set before any fixture runs a query, exactly
# as test_onboarding_mobile.py does.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def _a_member_with_a_session(posts: int = 0) -> str:
    """One member, signed in server-side. The session cookie is injected into each browser
    context, so these drive the INSTALL page rather than re-testing the sign-in form.

    `posts` writes that many of the member's own posts, which is what a test needs when it
    has to put a control UNDER the card: an empty feed is one screen tall and nothing on it
    ever reaches the bottom band.

    Identifiers are unique per call, the pattern test_the_photo_button_in_a_browser.py
    adopted: a `transaction=True` teardown can lose its flush to a request the live server is
    still answering, and a fixed slug ("maternal" is also test_onboarding_mobile.py's) turns
    that into a duplicate-key failure in whichever test runs NEXT."""
    tag = secrets.token_hex(4)
    yard = Yard.objects.create(name="Maternal", slug=f"maternal-{tag}")
    pod = Pod.objects.create(name=f"The cousins {tag}", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = User.objects.create_user(username=f"installcousin-{tag}")
    member = Member.objects.create(
        display_name="Cousin Reed",
        user=user,
        # The e-mail offer on the feed is ANSWERED, so it can never be the reason a
        # home-screen card is or is not on the page: the product shows one prompt at a time
        # and that one goes first (core/feed_views.py). Its own rule is covered by the
        # request-client tests in test_get_the_app.py.
        email_prompt_dismissed_at=timezone.now(),
    )
    PodMembership.objects.create(member=member, pod=pod)
    for index in range(posts):
        Post.objects.create(author=member, pod=pod, body=f"Something that happened, {index}.")
    client = Client()
    client.force_login(user, backend=_BACKEND)  # a real DB session the live server shares
    return str(client.cookies["sessionid"].value)


def _an_elder_with_a_link() -> str:
    """A No-Login Link, minted for a relative who has no account at all."""
    tag = secrets.token_hex(4)
    yard = Yard.objects.create(name="Paternal", slug=f"paternal-{tag}")
    pod = Pod.objects.create(name=f"The elders {tag}", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    nana = Member.objects.create(display_name="Nana")
    PodMembership.objects.create(member=nana, pod=pod)
    return str(elder_tokens.mint(nana))


def _let_the_server_finish(page: Any) -> None:
    """The page goes on to fetch the manifest, an icon (a PIL render) and to register the
    worker after `goto` returns; ending the test with one of those in flight is how the
    per-test flush deadlocks against the session-scoped live server."""
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightTimeoutError:
        pass  # hygiene before the flush, never an assertion


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


def test_android_is_offered_a_real_install_button(live_server: Any, playwright: Playwright) -> None:
    cookie = _a_member_with_a_session()
    base_url = live_server.url
    chromium = playwright.chromium.launch()
    try:
        device = dict(playwright.devices["Pixel 5"])
        page = _open(chromium, device, base_url, cookie)
        assert _order(page) == ["android", "ios"], (
            "an Android phone is not shown its own steps first"
        )
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
        _let_the_server_finish(page)
    finally:
        chromium.close()


def test_an_in_app_browser_is_sent_to_a_real_browser(
    live_server: Any, playwright: Playwright
) -> None:
    cookie = _a_member_with_a_session()
    base_url = live_server.url
    chromium = playwright.chromium.launch()
    try:
        device = dict(playwright.devices["Pixel 5"])
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
        above, below = warning.bounding_box(), platforms.bounding_box()
        assert above is not None and below is not None
        assert above["y"] < below["y"], (
            "the Open In Browser guidance is not above the steps it has to precede"
        )
        _let_the_server_finish(inside)
    finally:
        chromium.close()


def test_an_iphone_is_shown_apples_steps_first(live_server: Any, playwright: Playwright) -> None:
    cookie = _a_member_with_a_session()
    base_url = live_server.url
    webkit = playwright.webkit.launch()
    try:
        page = _open(webkit, dict(playwright.devices["iPhone 13"]), base_url, cookie)
        assert _order(page) == ["ios", "android"], "an iPhone is not shown its own steps first"
        expect(page.get_by_role("heading", name="iPhone And iPad")).to_be_visible()
        expect(page.get_by_text("Add to Home Screen", exact=True)).to_be_visible()
        # WebKit fires no beforeinstallprompt at all, which is why the three steps exist.
        expect(page.locator("[data-install-now]")).to_be_hidden()
        _let_the_server_finish(page)
    finally:
        webkit.close()


# --- the card at the foot of every signed-in page ----------------------------------------
#
# THE MOVE THIS SECTION PROVES. The offer used to be one muted line under the composer, on
# the feed and nowhere else. It is a card fixed to the bottom edge now, on every signed-in
# page, shown ONCE ever per device. Every condition it turns on is a browser fact, so a
# request-client test can only see that the markup shipped hidden; these drive it.


def _phone(browser: Any, playwright: Playwright, base_url: str, cookie: str, **kwargs: Any) -> Any:
    """A signed-in phone context. `kwargs` overrides the device (or adds `viewport`)."""
    device = dict(playwright.devices["Pixel 5"])
    device.update(kwargs)
    context = browser.new_context(**device)
    context.add_cookies([{"name": "sessionid", "value": cookie, "url": base_url}])
    return context


def _the_feed(context: Any, base_url: str) -> Any:
    page = context.new_page()
    page.goto(f"{base_url}/feed/")
    return page


def test_the_card_is_offered_once_and_never_again_on_that_phone(
    live_server: Any, playwright: Playwright
) -> None:
    """The whole rule, in one test: it comes up on a phone, the fact that it was SHOWN is
    remembered as it appears, and the next load is quiet. Remembering on appearance rather
    than on an answer is what makes ignoring it count — a nudge this small is worse asked
    twice than never asked at all."""
    cookie = _a_member_with_a_session()
    base_url = live_server.url
    chromium = playwright.chromium.launch()
    try:
        context = _phone(chromium, playwright, base_url, cookie)
        page = _the_feed(context, base_url)
        card = page.locator("[data-install-card]")
        expect(card).to_be_visible()
        expect(page.get_by_text("Add Backyard to your home screen.")).to_be_visible()
        assert (
            page.evaluate("() => window.localStorage.getItem('backyard.install-card.seen')") == "1"
        ), "the seen mark is not written as the card appears, so ignoring it would not count"
        _let_the_server_finish(page)

        # Nothing was pressed. The second load is quiet anyway.
        page.goto(f"{base_url}/feed/")
        expect(page.locator("[data-install-card]")).to_be_hidden()
        _let_the_server_finish(page)
    finally:
        chromium.close()


def test_a_store_that_cannot_keep_the_mark_gets_no_card(
    live_server: Any, playwright: Playwright
) -> None:
    """The once-ever rule fails CLOSED. A full store lets the read succeed and the write
    throw; a card revealed on that path would come back on every page load, which is the
    one thing this offer must never do. So the mark is written before the card is shown,
    and no mark means no card. The seam is `setItem` itself, made to throw the way a
    browser does at quota, with `getItem` left honest."""
    cookie = _a_member_with_a_session()
    base_url = live_server.url
    chromium = playwright.chromium.launch()
    try:
        context = _phone(chromium, playwright, base_url, cookie)
        context.add_init_script(
            """Object.defineProperty(Storage.prototype, 'setItem', {
                 value: function () { throw new DOMException('full', 'QuotaExceededError'); }
               });"""
        )
        page = _the_feed(context, base_url)
        assert page.evaluate(
            "() => { try { window.localStorage.setItem('x', '1'); return false; }"
            " catch (e) { return true; } }"
        ), "the seam this test drives is not in place, so it proves nothing"
        expect(page.get_by_role("heading", name="Your Backyard")).to_be_visible()  # non-vacuity
        expect(page.locator("[data-install-card]")).to_be_hidden()
        assert "install-card-open" not in page.evaluate("() => document.documentElement.className")
        _let_the_server_finish(page)
    finally:
        chromium.close()


def test_the_card_leads_to_the_install_page(live_server: Any, playwright: Playwright) -> None:
    """WebKit, because an iPhone is where the offer has to work: Safari fires no
    `beforeinstallprompt`, so this link to the three steps is the whole route to a home
    screen there."""
    cookie = _a_member_with_a_session()
    base_url = live_server.url
    webkit = playwright.webkit.launch()
    try:
        context = _phone(webkit, playwright, base_url, cookie, **playwright.devices["iPhone 13"])
        page = _the_feed(context, base_url)
        expect(page.locator("[data-install-card]")).to_be_visible()
        page.get_by_role("link", name="Get The App", exact=True).click()
        page.wait_for_url(f"{base_url}/app/")
        expect(page.get_by_role("heading", name="Get The App")).to_be_visible()
        _let_the_server_finish(page)
    finally:
        webkit.close()


def test_not_now_takes_the_card_away(live_server: Any, playwright: Playwright) -> None:
    """Pressed like a thumb, by its accessible NAME. The control shows an x; a screen
    reader announces "Not Now", the same decline this product writes everywhere else."""
    cookie = _a_member_with_a_session()
    base_url = live_server.url
    chromium = playwright.chromium.launch()
    try:
        context = _phone(chromium, playwright, base_url, cookie)
        page = _the_feed(context, base_url)
        card = page.locator("[data-install-card]")
        expect(card).to_be_visible()
        page.get_by_role("button", name="Not Now", exact=True).click()
        expect(card).to_be_hidden()
        _let_the_server_finish(page)
    finally:
        chromium.close()


def test_the_page_keeps_its_own_controls_out_from_under_the_card(
    live_server: Any, playwright: Playwright
) -> None:
    """The card is FIXED to the bottom edge, so the page has to reserve the room the way a
    tab bar's layout does — otherwise the last thing on every screen is under it. Scrolled
    to the very bottom, the footer's own link must still be the thing a thumb lands on."""
    cookie = _a_member_with_a_session()
    base_url = live_server.url
    chromium = playwright.chromium.launch()
    try:
        context = _phone(chromium, playwright, base_url, cookie)
        page = _the_feed(context, base_url)
        expect(page.locator("[data-install-card]")).to_be_visible()
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        link = page.get_by_role("link", name="Sign Out", exact=True)
        box = link.bounding_box()
        assert box is not None
        landed = page.evaluate(
            """([x, y]) => {
                const found = document.elementFromPoint(x, y);
                return found ? found.outerHTML.slice(0, 120) : '';
            }""",
            [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2],
        )
        assert "Sign Out" in landed, (
            f"the card is sitting on the last control on the page: {landed}"
        )
        _let_the_server_finish(page)
    finally:
        chromium.close()


def test_a_desktop_window_is_never_offered_a_home_screen(
    live_server: Any, playwright: Playwright
) -> None:
    """A home-screen icon means nothing on a laptop.

    TWO MECHANISMS, AND THIS ASSERTS BOTH. `to_be_hidden` alone proves only the
    STYLESHEET: `.install-card { display: none }` outside the phone query hides the card
    whatever the script does. So the script's own reading is asserted by its consequences —
    no seen mark and no class on the root element, neither of which the CSS can produce.
    Without them a regression that revealed the card on every desktop load, silently
    spending the phone's one showing on a laptop, would have passed here.

    The second window is 500px wide with a FINE pointer, which is the narrowed desktop
    window the coarse-pointer reading exists for: it is inside the phone breakpoint, so the
    width test alone would offer it a home screen.
    """
    cookie = _a_member_with_a_session()
    base_url = live_server.url
    chromium = playwright.chromium.launch()
    try:
        context = chromium.new_context(viewport={"width": 1280, "height": 900})
        context.add_cookies([{"name": "sessionid", "value": cookie, "url": base_url}])
        page = _the_feed(context, base_url)
        expect(page.get_by_role("heading", name="Your Backyard")).to_be_visible()  # non-vacuity
        expect(page.locator("[data-install-card]")).to_be_hidden()
        assert (
            page.evaluate("() => window.localStorage.getItem('backyard.install-card.seen')") is None
        ), "a desktop load spent the one showing this person's phone will ever get"
        assert (
            page.evaluate("() => document.documentElement.classList.contains('install-card-open')")
            is False
        ), "the script revealed the card on a desktop; only the stylesheet hid it"
        _let_the_server_finish(page)

        # A NARROWED DESKTOP WINDOW: inside the phone breakpoint, and still not a phone.
        narrow = chromium.new_context(viewport={"width": 500, "height": 900})
        narrow.add_cookies([{"name": "sessionid", "value": cookie, "url": base_url}])
        page = _the_feed(narrow, base_url)
        assert page.evaluate("() => window.matchMedia('(max-width: 37.4375rem)').matches"), (
            "500px is not inside the phone breakpoint, so this window proves nothing"
        )
        assert page.evaluate("() => window.matchMedia('(pointer: fine)').matches")
        expect(page.locator("[data-install-card]")).to_be_hidden()
        assert (
            page.evaluate("() => window.localStorage.getItem('backyard.install-card.seen')") is None
        )
        _let_the_server_finish(page)
    finally:
        chromium.close()


def test_an_installed_app_is_not_asked_to_install_itself(
    live_server: Any, playwright: Playwright
) -> None:
    """Somebody reading this INSIDE the home-screen app has already done the thing the card
    asks for.

    THE SEAM IS `navigator.standalone`, set by an init script before the page loads.
    Playwright cannot emulate the `display-mode: standalone` media feature, and the product
    reads both — the display mode for Chrome and Android, `navigator.standalone` for iOS,
    which never reported a display mode. So this drives the iOS half, on WebKit, which is
    the engine that half exists for.
    """
    cookie = _a_member_with_a_session()
    base_url = live_server.url
    webkit = playwright.webkit.launch()
    try:
        context = _phone(webkit, playwright, base_url, cookie, **playwright.devices["iPhone 13"])
        context.add_init_script(
            "Object.defineProperty(navigator, 'standalone', { get: () => true });"
        )
        page = _the_feed(context, base_url)
        assert page.evaluate("() => navigator.standalone === true"), (
            "the seam this test drives is not in place, so it proves nothing"
        )
        expect(page.get_by_role("heading", name="Your Backyard")).to_be_visible()  # non-vacuity
        expect(page.locator("[data-install-card]")).to_be_hidden()
        _let_the_server_finish(page)
    finally:
        webkit.close()


def test_the_no_login_link_page_carries_no_card(live_server: Any, playwright: Playwright) -> None:
    """ADR-002: /t/ and /e/ plant no worker and link no manifest, because an elder on a bare
    link is the intermittent visitor Safari evicts one from. An offer of a home-screen icon
    there is an offer of an icon that opens a page she cannot use."""
    token = _an_elder_with_a_link()
    base_url = live_server.url
    chromium = playwright.chromium.launch()
    try:
        context = chromium.new_context(**dict(playwright.devices["Pixel 5"]))
        page = context.new_page()
        page.goto(f"{base_url}/t/{token}/")
        # Non-vacuity, on the control that exists only here: the No-Login Link page is
        # standalone and carries none of base.html's chrome, headings included.
        expect(page.get_by_role("button", name="Bigger Text")).to_be_visible()
        assert page.locator("[data-install-card]").count() == 0
        _let_the_server_finish(page)
    finally:
        chromium.close()


def test_the_card_stands_down_where_the_page_already_says_it(
    live_server: Any, playwright: Playwright
) -> None:
    """Get The App carries the steps and opens on "Add Backyard to your home screen"; a
    card under it saying the same words, linking to the page being read, is the
    two-lines-about-one-thing defect the voice guide names.

    AND THE TURN IS NOT SPENT: the offer is still to come on the next page this member
    opens, which is why the seen mark must not be written here."""
    cookie = _a_member_with_a_session()
    base_url = live_server.url
    chromium = playwright.chromium.launch()
    try:
        context = _phone(chromium, playwright, base_url, cookie)
        page = context.new_page()
        page.goto(f"{base_url}/app/")
        expect(page.get_by_role("heading", name="Get The App")).to_be_visible()  # non-vacuity
        expect(page.locator("[data-install-card]")).to_be_hidden()
        assert (
            page.evaluate("() => window.localStorage.getItem('backyard.install-card.seen')") is None
        ), "standing down on the install page spent the one showing this phone ever gets"
        _let_the_server_finish(page)

        # ...and the feed, next, still gets it.
        page.goto(f"{base_url}/feed/")
        expect(page.locator("[data-install-card]")).to_be_visible()
        _let_the_server_finish(page)
    finally:
        chromium.close()


def test_the_welcome_leaves_the_card_unspent(live_server: Any, playwright: Playwright) -> None:
    """THE BROWSER HALF OF THE WELCOME RULE, which is the half that matters: the card is
    remembered the moment it APPEARS, so what has to be proven is that no welcome screen
    writes the mark. A brand-new relative walks all four and then reaches the feed, and the
    card is still there to be offered.

    Screen four is the product's own Get The App, three taps in, at the moment it works — a
    card spent on screen one would be the only showing that device ever gets."""
    cookie = _a_member_with_a_session()
    base_url = live_server.url
    chromium = playwright.chromium.launch()
    try:
        context = _phone(chromium, playwright, base_url, cookie)
        page = context.new_page()
        for path, heading in (
            ("/welcome/", "Welcome"),
            ("/welcome/family-email/", "Email Updates"),
            ("/welcome/hello/", "Say Hello"),
            ("/welcome/app/", "Get The App"),
        ):
            page.goto(f"{base_url}{path}")
            expect(page.get_by_role("heading", name=heading)).to_be_visible()  # non-vacuity
            expect(page.locator("[data-install-card]")).to_be_hidden()
            assert (
                page.evaluate("() => window.localStorage.getItem('backyard.install-card.seen')")
                is None
            ), f"{path} spent the one showing this device ever gets"
            _let_the_server_finish(page)

        page.goto(f"{base_url}/feed/")
        expect(page.locator("[data-install-card]")).to_be_visible()
        _let_the_server_finish(page)
    finally:
        chromium.close()


def test_the_post_menu_outranks_the_card(live_server: Any, playwright: Playwright) -> None:
    """A member opened Post Options on a post low on the screen and the card painted over
    Edit Post and Delete Post, so a thumb aimed at Delete Post opened Get The App. A menu
    somebody deliberately opened outranks a nudge nobody asked for."""
    cookie = _a_member_with_a_session(posts=10)
    base_url = live_server.url
    chromium = playwright.chromium.launch()
    try:
        context = _phone(chromium, playwright, base_url, cookie)
        page = _the_feed(context, base_url)
        card = page.locator("[data-install-card]")
        expect(card).to_be_visible()

        # PUT A MENU WHERE IT OVERLAPS, which is the whole setup. A menu opens DOWNWARDS
        # (`top: 100%`), so the one that lands in the card's band is a control sitting just
        # above the card — and scrolling to the very bottom does not produce one, because
        # the end-cap, the footer and the reserved room are all below the last post. So the
        # page is scrolled until a chosen post's control is 30px above the card's top edge.
        which = page.evaluate(
            """() => {
                const top = document.querySelector('[data-install-card]')
                    .getBoundingClientRect().top;
                const all = [...document.querySelectorAll('.post-menu > summary')];
                if (!all.length) { return -1; }
                const target = all[Math.floor(all.length / 2)];
                window.scrollBy(0, target.getBoundingClientRect().bottom - (top - 30));
                return all.indexOf(target);
            }"""
        )
        assert which >= 0, "the feed drew no post menus, so nothing here can overlap"
        # The <summary> itself, pressed like a thumb. Its accessible name is "Post Options",
        # but Chromium maps a disclosure summary to no stable role, so the role query is not
        # the way in here.
        page.locator(".post-menu > summary").nth(which).click()
        opened = page.locator(".post-menu").nth(which)
        items = opened.locator(".post-menu-items")
        expect(items).to_be_visible()
        delete = items.get_by_role("link", name="Delete Post")
        box = delete.bounding_box()
        assert box is not None
        centre = [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2]
        rect = card.bounding_box()
        assert rect is not None
        overlaps = (
            centre[0] >= rect["x"]
            and centre[0] <= rect["x"] + rect["width"]
            and centre[1] >= rect["y"]
            and centre[1] <= rect["y"] + rect["height"]
        )
        assert overlaps, (
            "Delete Post is not inside the card's rectangle, so this test proves nothing "
            "about which of them a thumb reaches"
        )
        landed = page.evaluate(
            """([x, y]) => {
                const found = document.elementFromPoint(x, y);
                return found ? found.outerHTML.slice(0, 120) : '';
            }""",
            centre,
        )
        assert "Delete Post" in landed, f"the card is painting over the post menu: {landed}"
        _let_the_server_finish(page)
    finally:
        chromium.close()


def test_the_scrollport_reserves_the_card_and_focus_lands_clear_of_it(
    live_server: Any, playwright: Playwright
) -> None:
    """WCAG 2.2 SC 2.4.11, asserted as the MECHANISM and then as the outcome.

    THE MECHANISM is `scroll-padding-bottom` on the scrollport, which is the ROOT element —
    what any fixed bottom bar owes the page, the same way the body's padding is what it
    owes the footer. It is declared while the card is open and gone when it is closed, and
    it is read here off the computed style because that is the only thing that distinguishes
    it from a rule that never applied: a class on <body> could not reach the root at all.

    THE OUTCOME is the thing a member feels: the control that takes focus is not underneath
    the card. The two reserves carry different halves of it and neither is spare. The body's
    padding carries the END of the document — the footer's own links, which is what
    test_the_page_keeps_its_own_controls_out_from_under_the_card walks. `scroll-padding`
    carries everything ABOVE that: with it removed and the body's padding left alone, a
    keyboard walk of this feed put 18 of 80 Tab presses on Chromium and 30 of 80 on WebKit
    onto controls the card was painted over — the composer's own Post button, Love, Reply,
    Post Options — and `scrollIntoView({block: 'end'})`, which is the move an anchor jump
    and find-in-page make, left the control entirely behind the card on both engines.

    A SCRIPTED `.focus()` IS NOT THAT CASE, which is why the block-end scroll is what is
    driven below: Chromium parks a scripted focus scroll near the TOP of the viewport and
    WebKit does not scroll for one at all, so a `focus()` assertion passes whether the rule
    is there or not. Both halves are asserted so that removing EITHER reserve is caught.
    """
    cookie = _a_member_with_a_session(posts=8)
    base_url = live_server.url
    chromium = playwright.chromium.launch()
    try:
        context = _phone(chromium, playwright, base_url, cookie)
        page = _the_feed(context, base_url)
        card = page.locator("[data-install-card]")
        expect(card).to_be_visible()

        reserve = page.evaluate(
            "() => getComputedStyle(document.documentElement).scrollPaddingBottom"
        )
        height = (card.bounding_box() or {}).get("height", 0)
        assert reserve.endswith("px"), f"the scrollport reserves nothing: {reserve!r}"
        assert float(reserve[:-2]) >= height, (
            f"the scrollport reserves {reserve} for a card {height}px tall, so a control "
            "scrolled to the bottom edge still lands behind it"
        )

        which = page.evaluate(
            """() => {
                const all = [...document.querySelectorAll('button.love')];
                const target = all.find(
                    node => node.getBoundingClientRect().top > window.innerHeight
                );
                if (!target) { return -1; }
                target.focus();
                return all.indexOf(target);
            }"""
        )
        assert which >= 0, "no control sits below the fold, so no Tab here can scroll downwards"
        focused = page.locator("button.love").nth(which)
        box = focused.bounding_box()
        rect = card.bounding_box()
        assert box is not None and rect is not None
        assert page.evaluate("() => document.activeElement.classList.contains('love')"), (
            "the control never took focus, so nothing scrolled"
        )
        assert box["y"] >= 0, "the focused control scrolled off the top instead"
        assert box["y"] + box["height"] <= rect["y"], (
            "the focused control is behind the card: its bottom is "
            f"{box['y'] + box['height']}, the card starts at {rect['y']}"
        )

        # THE CASE `scroll-padding` IS ACTUALLY FOR: a scroll to the bottom edge of the
        # scrollport, which is what an anchor jump, find-in-page and Chrome's auto-expanding
        # <details> all do. Without the rule this lands the control entirely behind the card
        # on both engines; a scripted focus() does not, on either.
        landed = page.evaluate(
            """() => {
                const card = document.querySelector('[data-install-card]');
                const loves = [...document.querySelectorAll('main button.love')];
                const el = loves[loves.length - 1];
                el.scrollIntoView({block: 'end'});
                const r = el.getBoundingClientRect(), c = card.getBoundingClientRect();
                return {bottom: Math.round(r.bottom), cardTop: Math.round(c.top)};
            }"""
        )
        assert landed["bottom"] <= landed["cardTop"], (
            "a scroll to the bottom edge of the scrollport put the control behind the card: "
            f"it ends at {landed['bottom']}, the card starts at {landed['cardTop']}"
        )

        # ...and the reserve goes with the card, so a page nobody is being offered anything
        # on scrolls exactly as it always did.
        page.get_by_role("button", name="Not Now", exact=True).click()
        expect(card).to_be_hidden()
        assert (
            page.evaluate("() => getComputedStyle(document.documentElement).scrollPaddingBottom")
            != reserve
        ), "the scrollport is still reserving room for a card that is gone"
        _let_the_server_finish(page)
    finally:
        chromium.close()
