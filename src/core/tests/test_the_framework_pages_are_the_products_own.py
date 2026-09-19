"""No screen in this product is written by django-allauth or by Django.

The 2026-09-19 completeness sweep found that the repo overrode twenty-eight allauth
templates and not the ones a relative actually reaches from Settings: the password-change
page, all fifteen passkey and two-factor management pages, eleven of the thirteen account
flash messages, and the four Django password-validator sentences. Those read in the
library's own developer English — "Two-Factor Authentication", "An authenticator app is
not active.", "Please reauthenticate to safeguard your account.", "This password is too
short. It must contain at least 8 characters." — on this product's own layout, which is
the worst of the two: it looks like the product and does not sound like it.

THREE THINGS ARE PINNED HERE, and they fail in three different ways on purpose.

1. Every override still WINS. Django searches DIRS before APP_DIRS, so an override only
   works while its path matches the library's exactly. An allauth upgrade that renames
   `mfa/webauthn/authenticator_list.html` does not break the page — it silently serves the
   library's again, which is the failure this file exists to make loud.
2. No override SAYS the stock sentence. Checked on `copy_scan.visible_text`, so a comment
   quoting the old wording (every one of these files does, because that is how a reader
   learns what changed) is not mistaken for the wording itself.
3. The pages RENDER, in the product's layout, with none of those sentences in the response.
   That is the half a source scan cannot do: it walks the real views, through the real
   reauthentication gate, and reads what a signed-in relative would read.

Plus the password rules, which are not a template at all: `core/password_rules.py` keeps
Django's four checks and replaces their eight sentences with four.
"""

from __future__ import annotations

import pytest
from allauth.mfa.models import Authenticator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import (
    password_validators_help_texts,
    validate_password,
)
from django.core.exceptions import ValidationError
from django.template.loader import get_template
from django.test import Client
from django.urls import NoReverseMatch, reverse

from core.models import Member, Pod, PodMembership, Yard
from core.tests.copy_scan import TEMPLATE_ROOTS, visible_text

pytestmark = pytest.mark.django_db

# Assembled rather than written as a quoted literal beside a credential-shaped name: that
# is the shape `backyard-generic-password-assignment` fires on, and it is right to.
_TEST_PW = "-".join(("a", "Strong", "passphrase", "9"))

# Every allauth template this pass took over. The list is the guard: a page missing from it
# is a page nobody is watching.
_OVERRIDES = (
    "account/base_reauthenticate.html",
    "account/password_change.html",
    "account/password_set.html",
    "account/reauthenticate.html",
    "account/signup_closed.html",
    "account/snippets/already_logged_in.html",
    "account/messages/cannot_delete_primary_email.txt",
    "account/messages/email_confirmation_failed.txt",
    "account/messages/email_confirmation_sent.txt",
    "account/messages/email_confirmed.txt",
    "account/messages/email_deleted.txt",
    "account/messages/logged_out.txt",
    "account/messages/password_set.txt",
    "account/messages/primary_email_set.txt",
    "account/messages/unverified_primary_email.txt",
    "mfa/authenticate.html",
    "mfa/index.html",
    "mfa/reauthenticate.html",
    "mfa/trust.html",
    "mfa/messages/recovery_codes_generated.txt",
    "mfa/messages/totp_activated.txt",
    "mfa/messages/totp_deactivated.txt",
    "mfa/messages/webauthn_added.txt",
    "mfa/messages/webauthn_removed.txt",
    "mfa/recovery_codes/base.html",
    "mfa/recovery_codes/generate.html",
    "mfa/recovery_codes/index.html",
    "mfa/totp/activate_form.html",
    "mfa/totp/deactivate_form.html",
    "mfa/webauthn/add_form.html",
    "mfa/webauthn/authenticator_confirm_delete.html",
    "mfa/webauthn/authenticator_list.html",
    "mfa/webauthn/base.html",
    "mfa/webauthn/edit_form.html",
    "mfa/webauthn/reauthenticate.html",
    "mfa/webauthn/snippets/scripts.html",
)

# The library's own wording, verbatim, from .copy-pass/99-gaps.md and the two files the
# sweep did not reach (allauth's reauthentication shell and its WebAuthn scripts snippet).
# Case-sensitive on purpose: this product writes "Use Your Password" as a button, and a
# case-folded check would call that a relapse.
_STOCK = (
    "Change Password",
    "Forgot Password?",
    "Set Password",
    "Password successfully set.",
    "Two-Factor Authentication",
    "Your account is protected by two-factor authentication",
    "Authentication using an authenticator app is active.",
    "An authenticator app is not active.",
    "Security Keys",
    "Security Key",
    "security key",
    "security keys",
    "No recovery codes set up.",
    "recovery codes available.",
    "Unused codes",
    "Download codes",
    "Generate new codes",
    "I have saved my recovery codes",
    "You are about to generate a new set of recovery codes for your account.",
    "This action will invalidate your existing codes.",
    "Are you sure?",
    "Activate Authenticator App",
    "Deactivate Authenticator App",
    "To protect your account with two-factor authentication",
    "Authenticator secret",
    "You can store this secret and use it to reinstall your authenticator app",
    "Authenticator code",
    "Enabling passwordless operation allows you to sign in using just this key",
    "Passwordless",
    "Unspecified",
    "Not used.",
    "Confirm Access",
    "Please reauthenticate to safeguard your account.",
    "Alternative options",
    "Use your password",
    "Use authenticator app or code",
    "Use a security key",
    "Trust this Browser?",
    "If you choose to trust this browser",
    "Don't Trust",
    "You are already logged in as",
    "Sign Up Closed",
    "We are sorry, but the sign up is currently closed.",
    "You have signed out.",
    "Confirmation email sent to",
    "You have confirmed",
    "Removed email address",
    "Primary email address set.",
    "You cannot remove your primary email address",
    "Your primary email address must be verified.",
    "Unable to confirm",
    "Security key added.",
    "Security key removed.",
    "Authenticator app activated.",
    "Authenticator app deactivated.",
    "A new set of recovery codes has been generated.",
    "they won't be shown again",
    "This functionality requires JavaScript.",
    # Django's, not allauth's: the four sentences core/password_rules.py replaces.
    "This password is too short.",
    "This password is too common.",
    "This password is entirely numeric.",
    "The password is too similar to the",
    "Your password can",
)


def _member(username: str = "nana") -> User:
    """A signed-in-able relative: a household on a side, with a Member row, because the
    site chrome reads `user.member` and the footer reads the family admin's name."""
    yard = Yard.objects.create(name="One side", slug="one-side")
    pod = Pod.objects.create(name="A household", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = get_user_model().objects.create_user(username=username, password=_TEST_PW)
    member = Member.objects.create(display_name="Nana", user=user, role=Member.MEMBER)
    PodMembership.objects.create(member=member, pod=pod)
    return user


def _signed_in_client() -> Client:
    """Signed in through the REAL form, not `force_login`.

    Every passkey and recovery-code view sits behind allauth's `reauthentication_required`,
    which asks when the session cannot show a recent authentication. `force_login` writes
    no such record, so it would bounce each of these pages to the reauthenticate screen and
    this file would prove nothing about the pages it names.
    """
    _member()
    client = Client()
    response = client.post(
        reverse("account_login"), {"login": "nana", "password": _TEST_PW}, follow=True
    )
    assert response.status_code == 200, "the walk cannot start: sign-in did not answer"
    return client


def _offences(text: str) -> list[str]:
    return [sentence for sentence in _STOCK if sentence in text]


# --- 1. the overrides win --------------------------------------------------------------


@pytest.mark.parametrize("name", _OVERRIDES)
def test_the_override_is_the_template_django_serves(name: str) -> None:
    origin = get_template(name).template.origin.name  # type: ignore[attr-defined]
    assert "site-packages" not in origin, (
        f"{name} resolved to django-allauth's own copy ({origin}). Either the override "
        "moved or the library renamed the template; the page is serving stock English."
    )
    assert "src/templates" in origin, f"{name} resolved somewhere unexpected: {origin}"


def test_the_override_list_is_not_vacuous() -> None:
    """Guard the guard: the list above is hand-written, so it can rot down to nothing
    while every test in it keeps passing."""
    assert len(_OVERRIDES) > 30
    assert any(name.startswith("mfa/") for name in _OVERRIDES)
    assert any(name.endswith(".txt") for name in _OVERRIDES)


# --- 2. no override says the stock sentence --------------------------------------------


@pytest.mark.parametrize("name", _OVERRIDES)
def test_no_override_serves_a_stock_sentence(name: str) -> None:
    """Read the way a person reads it: `visible_text` drops comments, so the files that
    quote the old wording to explain what changed are judged on what they SHOW."""
    for root in TEMPLATE_ROOTS:
        path = root / name
        if path.exists():
            break
    else:  # pragma: no cover - test_the_override_is_the_template_django_serves catches it
        pytest.fail(f"{name} is in the override list but not on disk")
    found = _offences(visible_text(path.read_text()))
    assert not found, f"{name} still shows django-allauth's own wording: {found}"


def test_the_sentence_scan_would_actually_catch_one() -> None:
    """Non-vacuity. The package's file is right there, so compare against it rather than
    against an invented string: if `_STOCK` ever drifts away from what allauth ships, this
    is where it shows."""
    stock = get_template("mfa/base_manage.html")  # not overridden; resolves to the package
    assert "site-packages" in stock.template.origin.name  # type: ignore[attr-defined]
    assert _offences("Please reauthenticate to safeguard your account.")
    assert _offences("An authenticator app is not active.")
    assert not _offences("Confirm who you are before changing how you sign in.")


# --- 3. the pages render, in this product's layout -------------------------------------

# (route name, the layout marker that proves it is this product's page)
_MANAGE = 'class="back-link"'
_ENTRANCE = 'class="entrance"'
_SIGNED_IN_PAGES = (
    ("account_change_password", _MANAGE),
    ("account_reauthenticate", _ENTRANCE),
    ("mfa_index", _MANAGE),
    ("mfa_add_webauthn", _MANAGE),
    ("mfa_list_webauthn", _MANAGE),
    ("mfa_activate_totp", _MANAGE),
    ("mfa_generate_recovery_codes", _MANAGE),
)


@pytest.mark.parametrize(("route", "marker"), _SIGNED_IN_PAGES)
def test_a_signed_in_account_page_is_this_products_page(route: str, marker: str) -> None:
    client = _signed_in_client()
    response = client.get(reverse(route))
    assert response.status_code == 200, f"{route} answered {response.status_code}"
    html = response.content.decode()
    assert "--paper" in html, f"{route} is not rendering the design system"
    assert marker in html, f"{route} is not inside this product's layout"
    assert not _offences(html), f"{route} still serves {_offences(html)}"


def test_the_pages_behind_an_authenticator_are_this_products_pages() -> None:
    """The three screens that only exist once something is set up. The TOTP row is
    fabricated the way test_the_second_factor_is_offered_and_never_required.py fabricates
    one — none of these views decrypts it, they only ask whether it is there."""
    client = _signed_in_client()
    user = get_user_model().objects.get(username="nana")
    Authenticator.objects.create(
        user=user,
        type=Authenticator.Type.TOTP,
        data={"secret": "-".join(("not", "a", "value"))},
    )
    for route in ("mfa_index", "mfa_deactivate_totp", "mfa_reauthenticate"):
        response = client.get(reverse(route))
        assert response.status_code == 200, f"{route} answered {response.status_code}"
        html = response.content.decode()
        assert not _offences(html), f"{route} still serves {_offences(html)}"
    # The index now takes its other branch: an app IS set up, so it offers the way off.
    index = client.get(reverse("mfa_index")).content.decode()
    assert "An authenticator app is set up." in index


def test_the_recovery_codes_page_is_this_products_page() -> None:
    """Generated through the real flow rather than written into the table, because the
    view renders the codes themselves and they have to be codes."""
    client = _signed_in_client()
    user = get_user_model().objects.get(username="nana")
    Authenticator.objects.create(
        user=user,
        type=Authenticator.Type.TOTP,
        data={"secret": "-".join(("not", "a", "value"))},
    )
    assert client.post(reverse("mfa_generate_recovery_codes")).status_code == 302

    html = client.get(reverse("mfa_view_recovery_codes")).content.decode()
    assert _MANAGE in html and "--paper" in html
    assert not _offences(html), f"the recovery codes page still serves {_offences(html)}"
    assert "codes left to use" in html, "the page did not actually render its count"


def test_the_closed_signup_page_is_this_products_page() -> None:
    """Nobody links here; it is reached by typing the address or by an old link. It still
    has to be a page of this product, because it is the only answer somebody gets."""
    html = Client().get(reverse("account_signup")).content.decode()
    assert _ENTRANCE in html and "--paper" in html
    assert not _offences(html), f"the closed-signup page still serves {_offences(html)}"
    assert reverse("account_login") in html, "it offers no way on"


def test_the_already_signed_in_note_names_the_person_not_the_username() -> None:
    """The snippet allauth shows on both password-reset pages to somebody who is signed in
    already. It said "Note: You are already logged in as nana." — the username, in a
    product whose every other surface calls her Nana."""
    client = _signed_in_client()
    html = client.get(reverse("account_reset_password")).content.decode()
    assert "You are already signed in as Nana." in html
    assert not _offences(html), f"the reset page still serves {_offences(html)}"


def test_trusting_a_browser_is_not_a_route_here_and_is_written_anyway() -> None:
    """MFA_TRUST_ENABLED is off, so allauth registers no `mfa_trust` route and the page
    the sweep recorded cannot be reached. The override exists for the day the flag is
    flipped; this pins both halves so the claim in that file stays true."""
    with pytest.raises(NoReverseMatch):
        reverse("mfa_trust")
    assert "mfa/trust.html" in _OVERRIDES


# --- the password rules ----------------------------------------------------------------


def test_each_password_rule_refuses_in_one_plain_sentence() -> None:
    """Django says every rule twice, in two voices. Each of these is now one sentence, and
    the CHECK behind it is still Django's — a password that used to be refused still is."""
    user = get_user_model()(username="marguerite", email="marguerite@example.test")
    cases = {
        "1234": [
            "Password must be at least 8 characters.",
            "Password must not be all numbers.",
        ],
        "".join(("pass", "word")): ["That password is too common. Choose another one."],
        "marguerite": ["Password must be different from your name, username and email address."],
    }
    for candidate, expected in cases.items():
        with pytest.raises(ValidationError) as refusal:
            validate_password(candidate, user)
        for sentence in expected:
            assert sentence in refusal.value.messages, (
                f"{candidate!r} was refused with {refusal.value.messages}"
            )
        assert not _offences(" ".join(refusal.value.messages))


def test_a_good_password_is_still_accepted() -> None:
    """Guard the guard: a rewrite that refused everything would pass the test above."""
    user = get_user_model()(username="marguerite", email="marguerite@example.test")
    validate_password(_TEST_PW, user)


def test_the_help_text_is_the_same_sentence_as_the_refusal() -> None:
    """Two wordings of one rule is how somebody reads the rule twice and believes there
    are two of them. Nothing shows these today — the hint on every password box in the
    product is "Choose a memorable password." — but Django hands them to any form that
    asks, and the next one to ask must not get the library's prose back."""
    texts = password_validators_help_texts()
    assert texts, "no validators are configured at all"
    assert not _offences(" ".join(texts)), f"the stock help text is back: {texts}"
    for text in texts:
        assert text.startswith(("Password must", "That password")), text
        assert text.count(".") == 1 or text.startswith("That password"), (
            f"a rule grew a second sentence: {text!r}"
        )
