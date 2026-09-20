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
from django.utils import timezone

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
    # Where Share IS depends on the device: the bottom on an iPhone's Safari, the TOP on an
    # iPad and in Chrome, Edge and Firefox on iOS. The heading says iPad, so no edge is named.
    assert "in the browser toolbar" in steps
    assert "bottom of the screen" not in steps


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


def test_it_says_what_to_do_about_signing_in_and_names_the_username() -> None:
    """An installed app on an iPhone has its own storage, so the Safari session does not come
    with it; on Android it usually does. "May", so the sentence is true on every phone.

    The second paragraph has to WORK for the member an admin hands a Sign-In Link to: by
    construction somebody with no e-mail on file, who may never have known their username.
    The link sets a password (recovery.redeem) and then shows the sign-in page with the
    username filled in, in the BROWSER. The installed app opens with that box empty, so an
    instruction that names only the password dead-ends exactly this member (review of #225).
    """
    pod, admin = _family()
    client, member = _member(pod)
    body = _flat(client.get(reverse("get_the_app")).content.decode())
    assert "The app may ask you to sign in again, once." in body
    assert "On an iPhone it keeps its own sign-in, separate from Safari." in body
    assert "A Sign-In Link usually opens in your browser, not in the app." in body
    assert "note the username on the next screen" in body
    assert "sign in with that username and password" in body
    # Never a claim about one platform's browser stated to every reader.
    assert "opens in Safari" not in body

    # The mechanism the paragraph rests on, exercised rather than asserted from prose: the
    # link leaves the member holding a password, and the next screen is told the username.
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
    """The page is public and the install page is not, so the section is signed-in only."""
    pod, _admin = _family()
    client, _row = _member(pod)
    signed_in = client.get(reverse("how_it_works")).content.decode()
    assert f'href="{reverse("get_the_app")}"' in signed_in
    assert "Add Backyard to your home screen and it opens like an app." in _flat(signed_in)
    # The WHOLE section is signed-in only. base.html links the manifest for a signed-in
    # reader only, so a stranger following the steps would make an icon with no name and no
    # app window: a page that tells somebody to install what they cannot is worse than none.
    public = Client().get(reverse("how_it_works")).content.decode()
    assert "On Your Phone" not in public
    assert "Add Backyard to your home screen" not in public
    assert reverse("get_the_app") not in public


def test_the_welcome_ends_on_it_and_can_be_left() -> None:
    """Screen four. It writes no content, so "Go To Your Backyard" is its skip. Screen three
    offers it by name and keeps its own way to the feed (test_welcome.py walks that)."""
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


def _past_the_email_offer(member: Member) -> None:
    """The feed shows ONE prompt at a time and the e-mail offer goes first, so the install
    line is only on the page of a member who has answered that one."""
    member.email_prompt_dismissed_at = timezone.now()
    member.save(update_fields=["email_prompt_dismissed_at"])


def test_the_feed_shows_one_prompt_at_a_time_and_email_goes_first() -> None:
    """Two sentences and two "Not Now"s between the composer and the first photograph is
    the wall of chrome the 2026-09-19 walk took down. Getting back into an account
    outranks an icon on a home screen, so the install line waits its turn."""
    pod, _admin = _family()
    client, member = _member(pod)
    body = client.get(reverse("feed")).content.decode()
    assert 'class="email-prompt"' in body
    assert "data-app-prompt" not in body
    _past_the_email_offer(member)
    body = client.get(reverse("feed")).content.decode()
    assert 'class="email-prompt"' not in body
    assert "data-app-prompt" in body


def test_declining_the_email_offer_does_not_summon_the_next_prompt() -> None:
    """Measured in review: the install line rendered at the same pixel the e-mail offer had
    just left, with its own "Not Now" in the same place. One prompt at a time also means
    not back to back: the page that follows a dismissal draws neither, the next visit may."""
    pod, _admin = _family()
    client, _row = _member(pod)
    assert 'class="email-prompt"' in client.get(reverse("feed")).content.decode()
    landed = client.post(reverse("dismiss_email_prompt"), follow=True).content.decode()
    assert 'class="email-prompt"' not in landed
    assert "data-app-prompt" not in landed, "a second prompt took the first one's seat"
    assert "data-app-prompt" in client.get(reverse("feed")).content.decode()


def test_the_feed_line_ships_hidden_and_only_a_script_reveals_it() -> None:
    """No flash. Every reason to show it — a phone, not installed, not already declined —
    is a browser fact, so the server sends it hidden and the script decides."""
    pod, _admin = _family()
    client, row = _member(pod)
    _past_the_email_offer(row)
    body = client.get(reverse("feed")).content.decode()
    assert '<div class="app-prompt" data-app-prompt hidden>' in body
    assert "display-mode: standalone" in body
    assert "pointer: coarse" in body, "the line is phones only"
    assert re.search(r"try \{\s*if \(window\.localStorage\.getItem", body), (
        "the read of the dismissal is not inside a try: Safari private mode THROWS there"
    )


def test_the_feed_line_sits_under_the_composer_beside_the_email_offer() -> None:
    """Item 5 of the phone-width walk cut a screen-tall card down to one line under the
    composer. A second card above it would put the product straight back."""
    pod, _admin = _family()
    client, row = _member(pod)
    _past_the_email_offer(row)
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
    client, row = _member(pod)
    _past_the_email_offer(row)
    script = client.get(reverse("feed")).content.decode()
    # PER ACCESS. A throw on the read would take the click wiring below it along, and a
    # single "try {" anywhere in the script satisfied the first cut of this test.
    assert re.search(r"try \{\s*if \(window\.localStorage\.getItem", script)
    assert re.search(r"try \{\s*window\.localStorage\.setItem", script)
    assert script.count("catch (error)") >= 2
    # ...and an install done elsewhere stops the offer without a reload.
    assert "addEventListener('appinstalled'" in script


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

    pod, _admin = _family()
    yard = pod.yards.first()
    assert yard is not None
    member = Member.objects.create(display_name="Nana")
    PodMembership.objects.create(member=member, pod=pod)
    now = timezone.now()
    issue = DigestIssue.objects.create(
        member=member, yard=yard, window_start=now - datetime.timedelta(days=7), window_end=now
    )
    link = reverse("digest_web", args=[digest_links.mint(issue)])
    # The token visitor, and ALSO a member who happens to be signed in when they tap the
    # link in their mail: what this item adds (the page link, the feed line, the install
    # button) belongs to member pages and appears on neither. (A signed-in member does get
    # the manifest link there, as on every page: base.html gates that on the session, and
    # they already carry the worker from the feed. ADR-002 is about the visitor with no
    # session, who is asserted worker-free by test_pwa.py.)
    signed_in, _row = _member(pod, username="reader-of-mail")
    for client in (Client(), signed_in):
        body = client.get(link).content.decode()
        assert "Email Update" in body  # non-vacuity: this is the mail's web copy
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
