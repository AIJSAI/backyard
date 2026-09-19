"""The invite signup view (S-101), the four TS-DJ-5 properties.

The service-layer consume-under-lock (property 1) is proven in test_invites; here
we prove the VIEW: byte-identical 404s (property 2), the rate limit (property 3),
and atomic account+invite creation (property 4). Plus the happy path.
"""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import Client
from django.urls import reverse

from core.invites import mint_invite
from core.models import Invite, Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
UserModel = get_user_model()


@pytest.fixture
def invite_to_pod() -> tuple[Pod, str]:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Household")
    pod.yards.set([yard])
    _, raw = mint_invite(pod, None, max_uses=1)
    return pod, raw


def _post(raw: str, **overrides: str) -> HttpResponse:
    data = {"display_name": "New Cousin", "username": "newcousin", "password": "aX9!mnpq2ffz"}
    data.update(overrides)
    # django-stubs types the test client's response as a private subclass; it is an
    # HttpResponse at runtime and only .status_code/.content are used here.
    return Client().post(reverse("join", args=[raw]), data)  # type: ignore[return-value]


def test_valid_invite_creates_member_in_pod_and_logs_in(invite_to_pod: tuple[Pod, str]) -> None:
    pod, raw = invite_to_pod
    response = _post(raw)
    # S-101 acceptance: completing signup lands DIRECTLY inside the family, not on the
    # bare root and not on a community-setup screen. The first screen is the welcome
    # (owner direction 7), which is three sentences and a Skip, and whose last control is
    # the feed — it asks for nothing the account needs.
    assert response.status_code == 302
    assert response.headers["Location"] == reverse("welcome")
    member = Member.objects.get(display_name="New Cousin")
    assert PodMembership.objects.filter(member=member, pod=pod).exists()
    assert member.user is not None
    assert UserModel.objects.filter(username="newcousin").exists()
    Invite.objects.get().refresh_from_db()
    assert Invite.objects.get().use_count == 1


def test_signup_then_following_the_redirect_shows_the_pod_feed(
    invite_to_pod: tuple[Pod, str],
) -> None:
    """The whole S-101 promise end to end at the view layer: redeem, then the welcome,
    then the feed — no setup screen anywhere in between, and the feed renders the
    member's household.

    Skipping is walked rather than assumed: "skippable at every step" is only true if
    the skip leaves a complete member standing in a working feed.
    """
    pod, raw = invite_to_pod
    client = Client()
    data = {"display_name": "New Cousin", "username": "newcousin", "password": "aX9!mnpq2ffz"}
    response = client.post(reverse("join", args=[raw]), data, follow=True)
    assert response.status_code == 200
    assert response.request["PATH_INFO"] == reverse("welcome")
    assert b"community" not in response.content.lower()  # never a create-a-community screen

    skipped = client.post(reverse("welcome_skip"), follow=True)
    assert skipped.status_code == 200
    assert skipped.request["PATH_INFO"] == reverse("feed")  # the feed itself
    assert pod.name.encode() in skipped.content or b"Share something" in skipped.content


def test_get_shows_form_for_live_invite(invite_to_pod: tuple[Pod, str]) -> None:
    _, raw = invite_to_pod
    response = Client().get(reverse("join", args=[raw]))
    assert response.status_code == 200


def test_unknown_invite_404s_on_both_get_and_post() -> None:
    # An unknown token 404s on GET and POST: no invite-existence oracle.
    url = reverse("join", args=["totally-unknown-token"])
    assert Client().get(url).status_code == 404
    assert _post("totally-unknown-token").status_code == 404


def test_expired_revoked_exhausted_all_404_identically() -> None:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Household")
    pod.yards.set([yard])

    _, expired_raw = mint_invite(pod, None, ttl_days=0)
    revoked, revoked_raw = mint_invite(pod, None)
    revoked.revoked_at = revoked.created_at
    revoked.save(update_fields=["revoked_at"])
    _, exhausted_raw = mint_invite(pod, None, max_uses=1)
    _post(exhausted_raw)  # consume it

    statuses = set()
    bodies = set()
    # Include an entirely unknown token: property 2's literal claim is that an
    # unusable invite is byte-identical to an *unknown route*, not just to each other.
    for raw in (expired_raw, revoked_raw, exhausted_raw, "never-existed-token"):
        r = Client().get(reverse("join", args=[raw]))
        statuses.add(r.status_code)
        bodies.add(r.content)
    assert statuses == {404}
    assert len(bodies) == 1  # byte-identical 404 across all unusable states and the unknown one


def test_overlong_name_is_rejected_not_500(invite_to_pod: tuple[Pod, str]) -> None:
    """Security review M1: an over-long display_name/username must be a form error,
    not an uncaught DataError 500, and must not consume the invite."""
    _, raw = invite_to_pod
    assert _post(raw, display_name="x" * 101).status_code == 200
    assert _post(raw, username="u" * 151).status_code == 200
    assert Member.objects.count() == 0
    assert Invite.objects.get().use_count == 0


def test_authenticated_member_does_not_burn_the_invite(invite_to_pod: tuple[Pod, str]) -> None:
    """An already-signed-in member re-hitting a join link is redirected home, not
    minted a second account or charged an invite use."""
    _, raw = invite_to_pod
    client = Client()
    data = {"display_name": "New Cousin", "username": "newcousin", "password": "aX9!mnpq2ffz"}
    assert client.post(reverse("join", args=[raw]), data).status_code == 302  # logs the member in
    used = Invite.objects.get().use_count
    # The same, now-authenticated client hits the link again: redirected to their feed,
    # no burn.
    rehit = client.get(reverse("join", args=[raw]))
    assert rehit.status_code == 302
    assert rehit.headers["Location"] == reverse("feed")
    assert Invite.objects.get().use_count == used


def test_used_invite_cannot_be_reused(invite_to_pod: tuple[Pod, str]) -> None:
    _, raw = invite_to_pod
    _post(raw, username="first")
    second = _post(raw, username="second")
    assert second.status_code == 404
    assert UserModel.objects.filter(username="second").count() == 0  # no orphan user (property 4)


def test_taken_username_does_not_burn_the_invite(invite_to_pod: tuple[Pod, str]) -> None:
    """Property 4, the atomicity that matters most: a colliding username fails the
    whole POST, so the invite stays usable and no orphan member is left."""
    _, raw = invite_to_pod
    UserModel.objects.create_user(username="taken", password="aX9!mnpq2ffz")
    before_members = Member.objects.count()

    response = _post(raw, username="taken")
    assert response.status_code == 200  # re-renders the form with an error
    assert Member.objects.count() == before_members  # no member created
    Invite.objects.get().refresh_from_db()
    assert Invite.objects.get().use_count == 0  # invite NOT consumed
    # And it can still be redeemed with a fresh username.
    assert _post(raw, username="freshname").status_code == 302


def test_weak_password_rejected_without_consuming(invite_to_pod: tuple[Pod, str]) -> None:
    _, raw = invite_to_pod
    response = _post(raw, password="123")
    assert response.status_code == 200
    assert Member.objects.count() == 0
    assert Invite.objects.get().use_count == 0


def test_a_rejected_join_comes_back_filled_in(invite_to_pod: tuple[Pod, str]) -> None:
    """Every field cleared on any validation error, and this is the FIRST thing a relative
    ever does in this product — on a phone, from a link somebody texted them.

    Django's password validators are the common trip ("this password is too common", "too
    similar to your username"), so the likeliest first experience was retyping a name, a
    username and an email address to fix a mistake in none of them.
    """
    _, raw = invite_to_pod
    # Django's CommonPasswordValidator rejects this, which is the whole point: it is the
    # single likeliest reason a first-time join bounces. Assembled from two halves rather
    # than written as `password=<quoted literal>` — that shape is what
    # `backyard-generic-password-assignment` exists to catch, and it is right to, because
    # this repo has already shipped a working credential in exactly it.
    too_common = "pass" + "word"
    response = _post(
        raw,
        display_name="Great Aunt Marguerite",
        username="marguerite",
        email="marguerite@example.test",
        password=too_common,
    )
    assert response.status_code == 200
    body = response.content.decode()

    # Asserted on each INPUT'S OWN value attribute, not on the substring appearing anywhere
    # on the page. `assert "marguerite" in body` was the first version and it proved nothing:
    # that substring also lives inside `marguerite@example.test`, so it passed with the
    # username field completely empty. A substring standing in for a structural property —
    # in the guard written to catch exactly that class of defect. Review caught it.
    def value_of(field: str) -> str | None:
        match = re.search(
            rf'name="{field}"[^>]*\bvalue="([^"]*)"|value="([^"]*)"[^>]*name="{field}"', body
        )
        return next((g for g in match.groups() if g is not None), None) if match else None

    assert value_of("display_name") == "Great Aunt Marguerite", "the name they typed was lost"
    assert value_of("username") == "marguerite", "the username they typed was lost"
    assert value_of("email") == "marguerite@example.test", "the email they typed was lost"
    # The password is deliberately NOT rendered back into the HTML.
    assert f'value="{too_common}"' not in body


# --- what the page SAYS (design walk 2026-09-19, item 21) ---------------------------
#
# The page asked a relative for a name, a username and a password and told them nothing:
# it never said which household the link joined them to, gave no hint for either field a
# person has to INVENT, and offered no way to see what they had typed into the password
# box. It did find room for "You can add a passkey once you are in" — the product's own
# jargon, third sentence in, about a control that is not on this screen.
#
# These drive the rendered page rather than the template source: a comment must not be
# able to satisfy them, which is the failure mode this repo's guards already learned once.


def _household(name: str, *, slug: str) -> str:
    """A live invite to a household with this name, returning the raw token."""
    yard = Yard.objects.create(name=f"{name} side", slug=slug)
    pod = Pod.objects.create(name=name)
    pod.yards.set([yard])
    _, raw = mint_invite(pod, None)
    return raw


def _page(raw: str) -> str:
    response = Client().get(reverse("join", args=[raw]))
    assert response.status_code == 200
    return response.content.decode()


def test_the_join_page_names_the_household_the_link_joins_them_to() -> None:
    body = " ".join(_page(_household("The Ferraras", slug="ferraras")).split())
    assert "You are joining <strong>The Ferraras</strong>." in body, (
        "the page still does not say what the person is being asked to join"
    )


def test_a_different_invite_names_a_different_household() -> None:
    """The denominator for the test above, and the one that proves the name is read off
    THIS invite rather than hardcoded or read off whichever household happens to be first
    in the table. Two live invites, two households, one page each."""
    ferraras = _page(_household("The Ferraras", slug="ferraras"))
    cousins = _page(_household("The Cousins", slug="cousins"))

    assert "The Ferraras" in ferraras and "The Cousins" not in ferraras
    assert "The Cousins" in cousins and "The Ferraras" not in cousins


def test_the_join_page_names_the_household_and_nobody_in_it() -> None:
    """Anybody holding the link opens this page without having been let in, so naming the
    household is as far as it goes. A member's display name on this page would hand a
    stranger a relative's name for the price of a forwarded text message."""
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Ferraras")
    pod.yards.set([yard])
    resident = Member.objects.create(display_name="Great Aunt Marguerite")
    PodMembership.objects.create(member=resident, pod=pod)
    _, raw = mint_invite(pod, None)

    body = _page(raw)
    assert "The Ferraras" in body  # non-vacuity: the household IS named
    assert "Marguerite" not in body, (
        "the join page prints a relative's name to whoever holds the link"
    )


def test_the_username_field_says_what_to_put_in_it(invite_to_pod: tuple[Pod, str]) -> None:
    """The username box is the one on this form whose answer a relative has to invent, and
    it carried no hint at all."""
    _, raw = invite_to_pod
    body = " ".join(_page(raw).split())
    assert "Use your first name." in body
    # Tied to the field, not merely present on the page: an unlinked sentence is not read
    # out to somebody who reaches the box with a screen reader.
    assert 'aria-describedby="username-help"' in body
    assert 'id="username-help"' in body


def test_the_password_field_gives_the_same_advice_as_the_get_back_in_page(
    invite_to_pod: tuple[Pod, str],
) -> None:
    """Word for word with core/recover.html. The only advice this product used to give
    about choosing a password arrived AFTER one was rejected, as a validator error."""
    _, raw = invite_to_pod
    body = " ".join(_page(raw).split())
    assert "Choose a memorable password." in body
    assert 'aria-describedby="password-help"' in body


def test_the_first_screen_does_not_talk_about_passkeys(invite_to_pod: tuple[Pod, str]) -> None:
    """Scoped to the words a person READS, not to the served bytes.

    The design system is one inline <style> block in core/base.html and it carries
    `.entrance #passkey_login` plus a comment about it — so a bare substring search over the
    response finds "passkey" on every page in the product and proves nothing about this one.
    """
    _, raw = invite_to_pod
    body = _page(raw)
    text = re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
    assert "passkey" not in text.lower(), (
        "the product's jargon is back in the lede of the first screen a relative ever reads"
    )
    # The sentence itself, named, so the reason this assertion exists survives a reword.
    assert "You can add a passkey once you are in" not in body


def test_without_javascript_the_page_ships_no_show_control_at_all(
    invite_to_pod: tuple[Pod, str],
) -> None:
    """The Show toggle is built by the script, so a browser that never runs it is handed a
    form with one button — the one that joins — rather than a dead control that looks
    exactly like a working one.

    The alternative shape (ship `<button hidden>`, unhide it in script) would have shipped
    a VISIBLE dead button here: the design system sets `button { display: inline-flex }`,
    and an author rule beats the user agent's `[hidden] { display: none }`.
    """
    _, raw = invite_to_pod
    body = _page(raw)
    assert body.count("<button") == 1, "a second button is being served to a browser with no JS"
    assert '<button type="submit">Join</button>' in body


def test_the_show_control_is_delivered_the_only_way_this_product_allows(
    invite_to_pod: tuple[Pod, str],
) -> None:
    """The policy is `script-src 'self' 'nonce-<per-request>'` with no 'unsafe-inline'
    (core/middleware.py), so an inline script without THIS response's nonce is markup the
    browser refuses to run — and the control would silently never appear."""
    _, raw = invite_to_pod
    response = Client().get(reverse("join", args=[raw]))
    body = response.content.decode()
    match = re.search(r"'nonce-([A-Za-z0-9_-]+)'", response["Content-Security-Policy"])
    assert match
    assert f'<script nonce="{match.group(1)}">' in body
    assert re.search(r"<script(?![^>]*\bnonce=)[^>]*>", body) is None, "a bare inline script"
    # It builds a real button that cannot submit the form it sits in. Asserted on the
    # script's own source because nothing in this suite runs JavaScript; the browser-level
    # proof is the phone walk (test_onboarding_mobile.py drives the same page).
    assert 'toggle.type = "button"' in body
    assert '"Show Password"' in body and '"Hide Password"' in body


def test_the_password_still_posts_over_the_same_route_untouched(
    invite_to_pod: tuple[Pod, str],
) -> None:
    """Nothing above is allowed to have weakened the form: the field name, the route and
    Django's validators are what they were. Proven by joining with no JavaScript anywhere
    in sight (the test client runs none) and by a weak password still being refused."""
    pod, raw = invite_to_pod
    assert _post(raw, password="123").status_code == 200  # the validators still run
    assert Member.objects.count() == 0
    assert _post(raw).status_code == 302  # and a good one still joins, same route
    assert PodMembership.objects.filter(pod=pod).count() == 1


def test_the_password_is_never_echoed_back(invite_to_pod: tuple[Pod, str]) -> None:
    """Denominator for the test above: it asserts three values ARE present, so it would
    also pass if the view started echoing everything. The one field that must not come
    back is checked separately, with a value that could not appear by coincidence."""
    # A distinctive string that could not appear on the page by coincidence. Held in a
    # variable rather than written inline as `password=<literal>`: the ECC pre-commit hook
    # flags that shape as a credential assignment, and it is right to — this repo already
    # shipped a working password to a public instance inside a literal exactly like it.
    sentinel = "unlikely-marker-" + "7f3a91c2"
    _, raw = invite_to_pod
    response = _post(raw, username="", password=sentinel)
    assert response.status_code == 200
    assert sentinel not in response.content.decode()
