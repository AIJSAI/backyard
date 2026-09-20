"""Get The App (S-103): the page, and the three places that point at it.

The manifest, the icons and the minimal worker shipped in wave 5 and passed
`test_pwa.py` ever since. What nothing tested, because nothing existed, is whether a
relative could ever FIND any of it: the product never said that Safari's Share sheet is
where the app comes from, never offered an Install button on Android, and never warned
somebody reading inside Instagram's viewer that no home screen is reachable from there.

Four properties, and each one has already been got wrong somewhere in this repository:

  * the page is signed in, and a stranger who asks for it is told nothing (the shape of
    test_a_stranger_is_told_no_names.py, applied to a new surface);
  * it is REACHABLE — from Settings, from How It Works, and from the feed — because a
    page linked from nowhere does not exist (test_member_settings_are_reachable.py);
  * the token surfaces carry none of it: /t/, /e/ and /d/ plant no worker and link no
    manifest (ADR-002), so they must not carry an install prompt either;
  * the branch a person sees is decided in the BROWSER, so the markup ships every branch
    and this file asserts they are all there. Which one is shown is the e2e's job
    (test_install_surface_mobile.py), on a real engine with a real user agent.
"""

from __future__ import annotations

import json
import re

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core import digest_links, elder_tokens
from core.models import DigestIssue, Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
# The name the stranger test uses, for the same reason: a relative's first name is the
# thing a public surface must not volunteer.
_ADMIN_NAME = "Jim Whitfield"
_ADMIN_FIRST = "Jim"


def _family() -> tuple[Pod, Member]:
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    admin = Member.objects.create(
        display_name=_ADMIN_NAME,
        user=User.objects.create_user(username="theadmin"),
        role=Member.INSTANCE_ADMIN,
    )
    PodMembership.objects.create(member=admin, pod=pod)
    return pod, admin


def _member(pod: Pod, username: str = "cousin") -> tuple[Client, Member]:
    user = User.objects.create_user(username=username)
    member = Member.objects.create(display_name="Cousin Reed", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return client, member


def _flat(html: str) -> str:
    return " ".join(html.split())


# --- who may read it ------------------------------------------------------------------


def test_a_stranger_is_sent_to_sign_in_and_told_nothing() -> None:
    """Not a privacy preference: base.html links the manifest and the apple-touch-icon
    for an AUTHENTICATED reader only, so a signed-out visitor following these steps would
    add an icon with no name and no standalone display, and Chrome would never fire
    `beforeinstallprompt` on a page carrying no manifest. The Install button would be
    dead. A page that cannot work for its reader should not open for them."""
    _family()
    response = Client().get(reverse("get_the_app"))
    assert response.status_code == 302
    assert reverse("account_login") in response.headers["Location"]
    # ...and the sign-in page it lands on still names nobody (walk item 12).
    landing = Client().get(response.headers["Location"]).content.decode()
    assert landing  # non-vacuity: something rendered
    assert _ADMIN_FIRST not in landing


def test_a_signed_in_member_gets_the_page() -> None:
    pod, _admin = _family()
    client, _member_row = _member(pod)
    response = client.get(reverse("get_the_app"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "<h1>Get The App</h1>" in body
    # The already-installed branch ships hidden, and the lead that would otherwise sit
    # above it saying "Add Backyard to your home screen" carries the hook that takes it
    # away — two lines about one thing that contradict each other is the empty-state
    # defect the voice guide names.
    assert '<div class="notice" data-install-done hidden>' in body
    assert "data-install-lead" in body


# --- what is on it --------------------------------------------------------------------


def test_the_iphone_steps_are_the_three_words_ios_shows() -> None:
    """Share, Add to Home Screen, Add — iOS's own labels, in order. A relative is looking
    for these exact words on their own screen, so a paraphrase is a defect."""
    pod, _admin = _family()
    client, _row = _member(pod)
    body = _flat(client.get(reverse("get_the_app")).content.decode())
    steps = body[body.index("iPhone And iPad") :]
    steps = steps[steps.index("<ol") : steps.index("</ol>")]
    positions = [
        steps.index(f"<strong>{label}</strong>") for label in ("Share", "Add to Home Screen", "Add")
    ]
    assert positions == sorted(positions), f"the steps are out of order: {steps}"
    # Three steps, not two and not four.
    assert steps.count("<li>") == 3, steps


def test_android_gets_a_real_install_button_and_the_menu_steps_behind_it() -> None:
    """The button is revealed by `beforeinstallprompt` and hidden until then, so the
    menu steps are what a browser that never fires the event (Firefox, some Samsung
    builds) leaves on screen."""
    pod, _admin = _family()
    client, _row = _member(pod)
    body = client.get(reverse("get_the_app")).content.decode()
    assert "beforeinstallprompt" in body
    assert "appinstalled" in body
    assert re.search(r"<div class=\"install-now\" data-install-now hidden>", body), (
        "the install offer must ship hidden: a button that cannot prompt is a dead control"
    )
    assert ">Install App</button>" in body
    assert '<section data-install-platform="android">' in body


def test_an_in_app_browser_is_told_to_leave_it_first() -> None:
    """Instagram, Facebook and LinkedIn open links in their own viewer, which can add
    nothing to a home screen. Every step on this page is wasted until they are out."""
    pod, _admin = _family()
    client, _row = _member(pod)
    body = client.get(reverse("get_the_app")).content.decode()
    assert "Open In Browser" in body
    for agent in ("Instagram", "FBAN", "FBAV", "LinkedInApp"):
        assert agent in body, f"{agent} is not detected, so its viewer gets no warning"


def test_both_platforms_ship_so_the_page_works_with_no_javascript() -> None:
    """Scripting off is a real reader — and it is also every reader for the moment before
    the script runs. Both lists are in the markup; the script only reorders them."""
    pod, _admin = _family()
    client, _row = _member(pod)
    body = client.get(reverse("get_the_app")).content.decode()
    assert 'data-install-platform="ios"' in body and 'data-install-platform="android"' in body
    assert 'data-install-platform="ios" hidden' not in body
    assert 'data-install-platform="android" hidden' not in body


def test_it_says_the_installed_app_has_its_own_sign_in() -> None:
    """The one thing that surprises people, and the reason an install reads as broken: an
    iOS home-screen app has its own storage, so the Safari session does not come with it.

    The second sentence has to be TRUE for the member who has no password of their own.
    They are the ones an admin hands a Sign-In Link to, and what that link does
    (core/recovery.py: `redeem` calls `user.set_password`) is give them one. So "choose a
    password, then sign in to the app with it" describes what actually happens.
    """
    pod, admin = _family()
    client, member = _member(pod)
    body = _flat(client.get(reverse("get_the_app")).content.decode())
    assert "the installed app has its own sign-in, separate from Safari" in body
    assert "Sign in once inside the app" in body
    assert "A Sign-In Link opens in Safari, not in the app." in body

    # The mechanism the sentence rests on, exercised rather than asserted from prose.
    from core import recovery

    raw = recovery.issue(member, issued_by=admin)
    recovery.redeem(raw, "aX9!mnpq2ffz")
    member.refresh_from_db()
    assert member.user is not None
    assert member.user.check_password("aX9!mnpq2ffz"), (
        "a Sign-In Link no longer leaves the member holding a password, so the page's "
        "instruction for signing in inside the app is no longer true for them"
    )


def test_it_names_nobody_and_links_nothing_private() -> None:
    """The page itself carries no member's name and no link into anybody's content. The
    footer's help line still names the admin, because that is what a signed-in reader is
    owed (test_a_stranger_is_told_no_names.py asserts the other direction)."""
    pod, _admin = _family()
    client, _row = _member(pod)
    body = client.get(reverse("get_the_app")).content.decode()
    page = body[body.index("<h1>Get The App</h1>") : body.index("<footer")]
    assert _ADMIN_FIRST not in page and "Cousin" not in page
    # NOTHING. It is a leaf reached from four places, so a "Back To ..." would name the
    # wrong one for three of its readers; the sticky header already carries the way out.
    assert not re.findall(r'href="([^"]+)"', page)


# --- reachability ---------------------------------------------------------------------


def test_settings_offers_it() -> None:
    pod, _admin = _family()
    client, _row = _member(pod)
    body = client.get(reverse("profile_edit")).content.decode()
    assert f'href="{reverse("get_the_app")}"' in body
    assert "data-app-row" in body, "nothing can hide the row once the app is installed"


def test_how_it_works_offers_it_to_a_member_and_not_to_a_stranger() -> None:
    """The page is public and the install page is not, so the link is signed-in only:
    offering a locked-out reader a link that bounces them to sign-in is the dead end the
    landing page already refuses to hand out."""
    pod, _admin = _family()
    client, _row = _member(pod)
    signed_in = client.get(reverse("how_it_works")).content.decode()
    assert f'href="{reverse("get_the_app")}"' in signed_in
    public = Client().get(reverse("how_it_works")).content.decode()
    assert "Add Backyard to your home screen" in public  # the fact is still stated
    assert reverse("get_the_app") not in public


def test_the_welcome_ends_on_it_and_can_be_left() -> None:
    """Screen four. It writes nothing, so "Go To Your Backyard" is its skip — the same
    shape screen three already uses rather than two controls with one destination."""
    pod, _admin = _family()
    client, member = _member(pod)

    three = client.get(reverse("welcome_hello")).content.decode()
    assert f'href="{reverse("welcome_app")}"' in three, "screen three no longer leads to it"

    four = client.get(reverse("welcome_app"))
    assert four.status_code == 200
    body = four.content.decode()
    assert "<h1>Get The App</h1>" in body
    assert 'data-install-platform="ios"' in body
    assert f'href="{reverse("feed")}"' in body, "there is no way off the last screen"

    # Leaving changes nothing and the feed still works.
    assert client.get(reverse("feed")).status_code == 200
    member.refresh_from_db()
    assert member.orientation_dismissed_at is not None


def test_the_welcome_step_needs_a_member_like_every_other_screen() -> None:
    _family()
    response = Client().get(reverse("welcome_app"))
    assert response.status_code == 302
    assert reverse("account_login") in response.headers["Location"]


# --- the quiet line on the feed --------------------------------------------------------


def test_the_feed_line_ships_hidden_and_only_a_script_reveals_it() -> None:
    """No flash. Every reason to show it — a phone, not installed, not already declined —
    is a browser fact, so the server sends it hidden and the script decides."""
    pod, _admin = _family()
    client, _row = _member(pod)
    body = client.get(reverse("feed")).content.decode()
    assert '<div class="app-prompt" data-app-prompt hidden>' in body
    assert "display-mode: standalone" in body
    assert "pointer: coarse" in body, "the line is phones only"
    assert "localStorage" in body and "catch" in body


def test_the_feed_line_sits_under_the_composer_beside_the_email_offer() -> None:
    """Item 5 of the phone-width walk cut a screen-tall card down to one line under the
    composer. A second card above it would put the product straight back."""
    pod, _admin = _family()
    client, _row = _member(pod)
    body = client.get(reverse("feed")).content.decode()
    assert body.index('class="composer') < body.index('class="app-prompt"')
    assert body.index('class="app-prompt"') < body.index('<ul class="feed">')


def test_the_archive_page_carries_no_install_line() -> None:
    """Paging back is a history page: no composer, no email offer, and no nudge. The
    whole block is inside `if not is_archive_page`, which is what keeps it that way."""
    pod, _admin = _family()
    client, member = _member(pod)
    post = Post.objects.create(author=member, pod=pod, body="something to page past")
    cursor = f"{post.created_at.isoformat()}_{post.id}"
    archive = client.get(reverse("feed"), {"before": cursor}).content.decode()
    assert "Older Posts" in archive  # non-vacuity: this really is the archive page
    assert "data-app-prompt" not in archive
    assert reverse("get_the_app") not in archive


def test_the_dismissal_is_per_device_and_survives_no_storage() -> None:
    """A departure from the email prompt beside it, which is dismissed on a member column.
    A second column is a migration this work item does not make, so the decline is kept in
    localStorage — and every access is wrapped, because Safari's private mode THROWS on
    localStorage rather than returning null, and an exception would take the rest of the
    script with it."""
    pod, _admin = _family()
    client, _row = _member(pod)
    script = client.get(reverse("feed")).content.decode()
    block = script[script.index("data-app-prompt-dismiss") :]
    assert "try {" in block and "catch (error)" in block


# --- the surfaces that must never carry it ---------------------------------------------


def test_the_no_login_link_pages_carry_no_install_surface() -> None:
    """ADR-002: /t/ and /e/ plant no worker and link no manifest, because an elder on a
    bare link is the intermittent visitor Safari evicts one from. An install prompt there
    would be an invitation to a home-screen icon that opens a page she cannot use."""
    pod, _admin = _family()
    nana = Member.objects.create(display_name="Nana")
    PodMembership.objects.create(member=nana, pod=pod)
    Post.objects.create(author=nana, pod=pod, body="a post")

    client = Client()
    client.get(reverse("elder_enter", args=[elder_tokens.mint(nana)]))
    body = client.get(reverse("elder_feed")).content.decode()
    assert body  # non-vacuity
    assert reverse("get_the_app") not in body
    assert "data-app-prompt" not in body and "data-install" not in body


def test_the_email_web_view_carries_no_install_surface() -> None:
    """/d/ shares base.html with member pages but mints no session, so its reader is an
    intermittent email-link visitor, not a member. Same rule."""
    import datetime

    from django.utils import timezone

    pod, _admin = _family()
    yard = pod.yards.first()
    assert yard is not None
    member = Member.objects.create(display_name="Nana")
    PodMembership.objects.create(member=member, pod=pod)
    now = timezone.now()
    issue = DigestIssue.objects.create(
        member=member, yard=yard, window_start=now - datetime.timedelta(days=7), window_end=now
    )
    body = Client().get(reverse("digest_web", args=[digest_links.mint(issue)])).content.decode()
    assert body  # non-vacuity
    assert reverse("get_the_app") not in body
    assert "data-app-prompt" not in body and "data-install" not in body


# --- the manifest the steps install ------------------------------------------------------


def test_the_manifest_carries_the_id_it_has_always_had_implicitly() -> None:
    """Chrome derives `id` from start_url when a manifest omits it, so every Backyard
    installed before this line existed is identified as "/feed/". Writing that same value
    down pins it: any other value reads as a DIFFERENT app, so an existing install would
    stop updating and a second icon would appear beside it."""
    data = json.loads(Client().get(reverse("manifest")).content)
    assert data["id"] == data["start_url"] == "/feed/"
