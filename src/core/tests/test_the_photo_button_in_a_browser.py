"""The photo button, pressed the way a person presses it, in a real browser.

2026-09-20: the owner sat down to write the first real post, tapped the photo button
before typing a word, and the composer closed under the thumb. No photo sheet, no error.
Every test the composer had was green, and so was every walk, because every one of them
handed files straight to the <input>. Nobody had pressed the button on an empty composer.

The mechanism, for whoever meets it again: the button is a <label>, and pressing a label
takes focus off the textarea. The composer hid its extras whenever the box was empty and
unfocused, the button lived inside the extras, so it was gone between the press and the
release and the click landed on the form. The reply form had the same shape.

So these tests TAP, on the two engines a family's phones run (WebKit for iOS Safari,
Chromium for Android Chrome), and they start from an EMPTY composer: the feed test makes
the button its very first touch, the reply test taps the box first and leaves it empty,
which is the sequence the owner met. A test that types first, or that calls
`set_input_files` on the input, cannot see this defect.

Excluded from the default unit run (`-m 'not e2e'`); runs in the browser lane.
"""

from __future__ import annotations

import io
import os
import secrets
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from PIL import Image
from playwright.sync_api import Page, Playwright, expect

from core import posting
from core.models import Member, Pod, PodMembership, Yard

User = get_user_model()
_PW = "aX9!mnpq2ffz"
_BACKEND = "django.contrib.auth.backends.ModelBackend"

# See test_onboarding_mobile.py: Playwright's sync API runs on a greenlet loop and Django
# refuses sync ORM calls from it unless told the single-threaded seeding here is safe.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

_ENGINES = [
    pytest.param("webkit", "iPhone 13", id="ios-safari"),
    pytest.param("chromium", "Pixel 5", id="android-chrome"),
]


def _seed() -> tuple[str, int]:
    """A member in a household with one post to reply to. Returns (session cookie, post id).

    Identifiers are unique per call. A `transaction=True` teardown can lose its flush to a
    request the live server is still answering, and a fixed slug or username turns that into
    a duplicate-key failure in the NEXT test, which is then the one that reads red."""
    tag = secrets.token_hex(4)
    yard = Yard.objects.create(name="Maternal", slug=f"maternal-{tag}")
    pod = Pod.objects.create(name="The cousins", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = User.objects.create_user(username=f"poster-{tag}", password=_PW)
    member = Member.objects.create(display_name="Ann Poster", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    post = posting.create_post(author=member, pod=pod, audience_yards=[], body="Reply to this one")
    client = Client()
    client.force_login(user, backend=_BACKEND)  # a real DB session the live server shares
    return client.cookies["sessionid"].value, post.id


def _photo(tmp_path: Path, name: str) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), (52, 110, 84)).save(buffer, format="JPEG")
    path = tmp_path / name
    path.write_bytes(buffer.getvalue())
    return str(path)


def _signed_in_page(
    playwright: Playwright, engine: str, device: str, base_url: str, cookie: str
) -> tuple[Any, Page]:
    browser = getattr(playwright, engine).launch()
    context = browser.new_context(**dict(playwright.devices[device]))
    context.add_cookies([{"name": "sessionid", "value": cookie, "url": base_url}])
    return browser, context.new_page()


def _let_the_server_finish(page: Page) -> None:
    """Wait for the page's own requests (the photo it just posted) before the test ends.

    `to_have_count` is satisfied by the <img> TAG, not by its bytes, so a test could end
    with `/media/<token>/` still being answered. `live_server` is session-scoped and the
    database flush is per test: the flush then deadlocks against that request, fails, and
    leaves rows behind for whichever test runs next. Measured at about one run in six."""
    page.wait_for_load_state("networkidle")


@pytest.mark.parametrize(("engine", "device"), _ENGINES)
def test_the_photo_button_opens_the_sheet_on_an_empty_composer(
    live_server: Any, playwright: Playwright, tmp_path: Path, engine: str, device: str
) -> None:
    cookie, _ = _seed()
    browser, page = _signed_in_page(playwright, engine, device, live_server.url, cookie)
    try:
        page.goto(f"{live_server.url}/feed/")
        composer = page.locator("form.composer.collapsible")
        button = composer.get_by_text("Add Photos Or Videos", exact=True)
        # At rest: the box, the photo button and Post. Who can see it waits.
        expect(button).to_be_visible()
        expect(composer.get_by_role("button", name="Post", exact=True)).to_be_visible()
        expect(composer.get_by_text("Who Can See This")).to_be_hidden()

        # The headline case: the button is the FIRST thing touched. No focusin has run, so
        # nothing has opened the composer for good; only the button's place in the DOM can
        # make this work. (The reply test below takes the other road: the box first.)
        with page.expect_file_chooser(timeout=5000) as chooser:
            button.tap()
        chooser.value.set_files(_photo(tmp_path, "lake.jpg"))

        # The picture is shown back, and the composer stays open around it, focus or no.
        expect(composer.locator("ul.media-previews > li")).to_have_count(1)
        page.locator("h1").tap()
        expect(composer.get_by_text("Who Can See This")).to_be_visible()
        expect(composer.locator("ul.media-previews > li")).to_have_count(1)

        composer.get_by_label("Share Something").fill("At the lake")
        composer.get_by_role("button", name="Post", exact=True).tap()
        # No wait_for_url: posting from the feed lands on the feed, so a URL wait is already
        # satisfied before the POST has left. The locators below retry across it.
        first = page.locator("ul.feed > li").first
        expect(first.get_by_text("At the lake")).to_be_visible()
        expect(first.locator("img")).to_have_count(1)
        _let_the_server_finish(page)
    finally:
        page.context.close()
        browser.close()


@pytest.mark.parametrize(("engine", "device"), _ENGINES)
def test_the_photo_button_opens_the_sheet_on_an_empty_reply(
    live_server: Any, playwright: Playwright, tmp_path: Path, engine: str, device: str
) -> None:
    """The reply form had the same shape and the same defect. A reply that is only a
    photograph is a real reply, so nothing is typed at all."""
    cookie, post_id = _seed()
    browser, page = _signed_in_page(playwright, engine, device, live_server.url, cookie)
    try:
        page.goto(f"{live_server.url}/posts/{post_id}/")
        reply = page.locator("form#reply")
        # The owner's own sequence: the box tapped and left EMPTY, then the button. Focus
        # leaving an empty box is what used to close the form under the press.
        reply.get_by_label("Write A Reply").tap()
        with page.expect_file_chooser(timeout=5000) as chooser:
            reply.get_by_text("Add Photos Or Videos", exact=True).tap()
        chooser.value.set_files(_photo(tmp_path, "porch.jpg"))
        expect(reply.locator("ul.media-previews > li")).to_have_count(1)

        reply.get_by_role("button", name="Reply", exact=True).tap()
        # No wait_for_url: the reply redirects to the URL the page is already on, so a URL
        # wait is satisfied before the POST has left. The locator retries across it.
        expect(page.locator("ul.comments > li img")).to_have_count(1)
        _let_the_server_finish(page)
    finally:
        page.context.close()
        browser.close()
