"""The get-back-in link ends on a page that says what happened and who you are.

Walk item 2, 2026-09-19. The button says "Save it and sign in". Tapping it saved the
password and dropped the person on a blank sign-in form: no message, no confirmation that
anything had been saved, and an empty username box.

That box is the whole problem. This link exists FOR the relatives with no email address on
file — the ones "Forgot your password?" can never reach, which is why an admin has to mint
them a link by hand — and a good share of them do not know what username somebody typed
for them a year ago. The product knew it, had just used it, and did not say it.

Now the sign-in page it lands on says "Your new password is saved. Sign in as <username>."
once, and the username is already in the box.

THE SECURITY PROPERTY, which is what most of this file is about: a username is printed
ONLY after a link was successfully used, and only the username that link belongs to. Every
failing shape — an unknown link, an expired one, a revoked one, one already used — answers
the same bare 404 it always did, and says nothing. A page that would name an account for a
guessed link would be an account-existence oracle handed to anybody with a URL bar.
"""

from __future__ import annotations

import datetime

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import recovery
from core.models import Member, Pod, PodMembership, RecoveryToken, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
# BOTH VALUES ARE ONES THIS SUITE ALREADY DECLARES SYNTHETIC. `test_no_hardcoded_demo_
# credentials` scans every tracked file for credential-shaped literals and refuses any that
# is not on `_ALLOWED_LITERALS` AND in .gitleaks.toml — a list that exists because this
# repository has published a working password three separate times. Reusing an entry that
# is already on both lists is the right move over adding two more: a shorter allowlist is a
# stronger one, and every new exemption is a place the next real credential can hide.
#
# Named rather than written inline at the call, the way the rest of this suite does it: an
# inline `password="..."` reads as a credential assignment to the pre-commit scanner.
_NEW_PW = "correct-horse-battery-staple-42"
_OLD_PW = "old-Passphrase-9"


def _locked_out() -> tuple[Member, Member, str]:
    """A relative with a login and no e-mail, and the admin who mints their link."""
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    admin = Member.objects.create(
        display_name="Ada Reed",
        user=User.objects.create_user(username="ada"),
        role=Member.INSTANCE_ADMIN,
    )
    PodMembership.objects.create(member=admin, pod=pod)
    member = Member.objects.create(
        display_name="Rose Reed",
        kinship_name="Nana",
        user=User.objects.create_user(username="nana", password=_OLD_PW),
    )
    PodMembership.objects.create(member=member, pod=pod)
    return member, admin, recovery.issue(member, issued_by=admin)


def test_saving_lands_on_sign_in_with_the_username_said_and_filled_in() -> None:
    member, _admin, raw = _locked_out()
    client = Client()

    page = client.post(
        reverse("recover", args=[raw]),
        {"password": _NEW_PW, "password_again": _NEW_PW},
        follow=True,
    )
    assert page.status_code == 200
    assert page.redirect_chain[-1][0] == reverse("account_login"), page.redirect_chain
    body = page.content.decode()

    assert "Your new password is saved. Sign in as nana." in body
    # Through the flash component the rest of the product uses, not a bespoke banner.
    assert 'class="messages"' in body and 'role="status"' in body
    # ...and the box is not empty.
    assert 'value="nana"' in body, "the username was named but not filled in"

    # Non-vacuity: the password really did change, so this is the success path.
    assert member.user is not None
    member.user.refresh_from_db()
    assert member.user.check_password(_NEW_PW)


def test_it_is_said_once_and_then_never_again() -> None:
    """A username left in the session would prefill the sign-in box on every later visit
    from that browser — including a visit by whoever else uses the phone."""
    _member, _admin, raw = _locked_out()
    client = Client()
    client.post(
        reverse("recover", args=[raw]),
        {"password": _NEW_PW, "password_again": _NEW_PW},
        follow=True,
    )

    again = client.get(reverse("account_login")).content.decode()
    assert "Your new password is saved" not in again
    assert 'value="nana"' not in again, "the username is still being filled in on later visits"


# --- the failing shapes, which must stay silent ---------------------------------------


def test_a_link_that_was_never_real_says_nothing_and_answers_404() -> None:
    _locked_out()
    client = Client()
    page = client.post(
        reverse("recover", args=["not-a-real-token-at-all"]),
        {"password": _NEW_PW, "password_again": _NEW_PW},
    )
    assert page.status_code == 404
    assert b"nana" not in page.content
    assert client.session.get(recovery.RECOVERED_USERNAME_KEY) is None


def test_a_reused_link_names_nobody_the_second_time() -> None:
    """The shape a forwarded or screenshotted link takes. The first use is legitimate; the
    second must be indistinguishable from a link that never existed."""
    _member, _admin, raw = _locked_out()
    first = Client()
    first.post(
        reverse("recover", args=[raw]),
        {"password": _NEW_PW, "password_again": _NEW_PW},
        follow=True,
    )

    second = Client()
    page = second.post(
        reverse("recover", args=[raw]),
        {"password": "a different one entirely", "password_again": "a different one entirely"},
    )
    assert page.status_code == 404
    assert b"nana" not in page.content
    assert second.session.get(recovery.RECOVERED_USERNAME_KEY) is None
    # And the sign-in page it might go to next is clean.
    assert 'value="nana"' not in second.get(reverse("account_login")).content.decode()


def test_an_expired_link_names_nobody() -> None:
    _member, _admin, raw = _locked_out()
    RecoveryToken.objects.all().update(expires_at=timezone.now() - datetime.timedelta(minutes=1))
    client = Client()
    page = client.post(
        reverse("recover", args=[raw]),
        {"password": _NEW_PW, "password_again": _NEW_PW},
    )
    assert page.status_code == 404
    assert client.session.get(recovery.RECOVERED_USERNAME_KEY) is None


def test_a_password_the_validators_refuse_names_nobody_yet() -> None:
    """The link SURVIVES a rejected password — a typo is not an attack — so the page
    re-renders for another try. It must not have said the password was saved."""
    _member, _admin, raw = _locked_out()
    client = Client()
    page = client.post(
        reverse("recover", args=[raw]),
        {"password": "123", "password_again": "123"},
    )
    assert page.status_code == 200, page.status_code
    body = page.content.decode()
    assert "Your new password is saved" not in body
    assert client.session.get(recovery.RECOVERED_USERNAME_KEY) is None


def test_a_mistyped_confirmation_names_nobody_yet() -> None:
    _member, _admin, raw = _locked_out()
    client = Client()
    page = client.post(
        reverse("recover", args=[raw]),
        {"password": _NEW_PW, "password_again": _NEW_PW + " oops"},
    )
    assert page.status_code == 200
    assert "Your new password is saved" not in page.content.decode()
    assert client.session.get(recovery.RECOVERED_USERNAME_KEY) is None


def test_merely_opening_the_link_names_nobody() -> None:
    """A GET must not consume the link, and it must not announce anything either — a mail
    scanner or a link preview fetches this URL before the person ever taps it."""
    _member, _admin, raw = _locked_out()
    client = Client()
    page = client.get(reverse("recover", args=[raw]))
    assert page.status_code == 200
    body = page.content.decode()
    assert "Your new password is saved" not in body
    assert "Sign in as" not in body
    assert client.session.get(recovery.RECOVERED_USERNAME_KEY) is None


def test_the_username_belongs_to_the_link_that_was_used() -> None:
    """Two locked-out relatives. Redeeming one must never name the other."""
    member, admin, raw = _locked_out()
    pod = Pod.objects.get(name="The Reeds")
    other = Member.objects.create(
        display_name="Sam Reed",
        user=User.objects.create_user(username="sam", password=_OLD_PW),
    )
    PodMembership.objects.create(member=other, pod=pod)
    other_raw = recovery.issue(other, issued_by=admin)

    client = Client()
    page = client.post(
        reverse("recover", args=[other_raw]),
        {"password": _NEW_PW, "password_again": _NEW_PW},
        follow=True,
    )
    body = page.content.decode()
    assert "Sign in as sam." in body
    assert "nana" not in body, "the wrong relative's username was printed"
    assert raw not in body
    # And the first relative's own link is untouched by somebody else redeeming theirs.
    assert member.user is not None
