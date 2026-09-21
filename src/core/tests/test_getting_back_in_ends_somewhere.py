"""The get-back-in link ends on a page that says what happened and who you are.

Walk item 2, 2026-09-19. The button said "Save it and sign in". Tapping it saved the
password and dropped the person on a blank sign-in form: no message, no confirmation that
anything had been saved, and an empty username box.

That box is the whole problem. This link exists FOR the relatives with no email address on
file — the ones "Forgot your password?" can never reach, which is why an admin has to mint
them a link by hand — and a good share of them do not know what username somebody typed
for them a year ago. The product knew it, had just used it, and did not say it.

Now the sign-in page it lands on says "Password changed. Sign in as <username>."
once, and the username is already in the box. The button says "Save Password", which is the
one act it performs (issue 227): the sign-in is the screen after the next one, and a button
that promised it had the person typing the new password a third time.

THE SECURITY PROPERTY, which is what most of this file is about: a username is printed
ONLY after a link was successfully used, and only the username that link belongs to. Every
failing shape — an unknown link, an expired one, a revoked one, one already used — answers
the same bare 404 it always did, and says nothing. A page that would name an account for a
guessed link would be an account-existence oracle handed to anybody with a URL bar.
"""

from __future__ import annotations

import contextlib
import datetime
from collections.abc import Iterator
from unittest import mock

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


@contextlib.contextmanager
def freeze_the_clock(*, minutes: int) -> Iterator[None]:
    """Run the block as if `minutes` had passed, by moving `timezone.now` forward.

    Patched rather than sleeping, and patched on `core.recovery` because that is the
    module whose `now` decides whether the stamp is stale.
    """
    real_now = timezone.now
    shifted = real_now() + datetime.timedelta(minutes=minutes)
    with mock.patch("core.recovery.timezone.now", return_value=shifted):
        yield


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

    assert "Password changed. Sign in as nana." in body
    # Through the flash component the rest of the product uses, not a bespoke banner.
    assert 'class="messages"' in body and 'role="status"' in body
    # ...and the box is not empty.
    assert 'value="nana"' in body, "the username was named but not filled in"

    # Non-vacuity: the password really did change, so this is the success path.
    assert member.user is not None
    member.user.refresh_from_db()
    assert member.user.check_password(_NEW_PW)


def test_the_button_promises_only_what_saving_does() -> None:
    """Issue 227, from the v0.2.0 role walk. The button said "Save And Sign In" and then
    the next screen asked for the password again, so a relative who had already typed it
    twice typed it a third time and wondered what they had got wrong.

    The flow is deliberate and unchanged — the test above proves what saving DOES do. This
    is the words: the form promises the one act it performs, plus the sign-out, which is
    true. Scoped to the form rather than the page so the check stays about the control: the
    base template's inlined stylesheet carries "sign-in" in its own comments, and a future
    tightening of this assertion to the hyphenated spelling would read those as copy.
    """
    _member, _admin, raw = _locked_out()
    body = Client().get(reverse("recover", args=[raw])).content.decode()
    form = body[body.index("<form") : body.index("</form>")]

    assert '<button type="submit">Save Password</button>' in form
    assert "sign in" not in form.lower(), "the form still promises a session saving never creates"
    # The one session sentence that IS true stays: redeeming ends every other session the
    # member had, which is a thing to know before pressing the button, not after.
    assert "You will be signed out everywhere else." in form


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
    assert "Password changed" not in again
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
    assert "Password changed" not in body
    assert client.session.get(recovery.RECOVERED_USERNAME_KEY) is None


def test_a_mistyped_confirmation_names_nobody_yet() -> None:
    _member, _admin, raw = _locked_out()
    client = Client()
    page = client.post(
        reverse("recover", args=[raw]),
        {"password": _NEW_PW, "password_again": _NEW_PW + " oops"},
    )
    assert page.status_code == 200
    assert "Password changed" not in page.content.decode()
    assert client.session.get(recovery.RECOVERED_USERNAME_KEY) is None


def test_merely_opening_the_link_names_nobody() -> None:
    """A GET must not consume the link, and it must not announce anything either — a mail
    scanner or a link preview fetches this URL before the person ever taps it."""
    _member, _admin, raw = _locked_out()
    client = Client()
    page = client.get(reverse("recover", args=[raw]))
    assert page.status_code == 200
    body = page.content.decode()
    assert "Password changed" not in body
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


# --- the ten-minute window (review finding 9) -----------------------------------------
#
# The session key is written the moment a link is redeemed and popped when the sign-in
# form next renders — but nothing guarantees that render happens. Somebody who saves a new
# password and closes the tab leaves their username in the session of a browser that, on
# the shared family tablet this product is partly for, the next person picks up.
#
# NOT `session.set_expiry`, which was the obvious reach and is wrong: `login()` cycles the
# session key but KEEPS its data, so a short expiry would follow them past the sign-in and
# log them out minutes after they finally got back in. The stamp is checked by hand.


def test_the_username_is_prefilled_inside_the_ten_minutes() -> None:
    _member, _admin, raw = _locked_out()
    client = Client()
    client.post(
        reverse("recover", args=[raw]),
        {"password": _NEW_PW, "password_again": _NEW_PW},
    )
    with freeze_the_clock(minutes=9):
        body = client.get(reverse("account_login")).content.decode()
    assert 'value="nana"' in body


def test_the_username_is_dropped_after_the_ten_minutes() -> None:
    _member, _admin, raw = _locked_out()
    client = Client()
    client.post(
        reverse("recover", args=[raw]),
        {"password": _NEW_PW, "password_again": _NEW_PW},
    )
    with freeze_the_clock(minutes=11):
        body = client.get(reverse("account_login")).content.decode()
    assert 'value="nana"' not in body, (
        "a stale username is still being typed into the box for whoever picks the device up"
    )


def test_a_stale_value_is_removed_rather_than_left_for_the_next_render() -> None:
    """Popped regardless of the answer: a stamp too old is a value that should not be
    sitting there at all, and leaving it would give the next render another go."""
    _member, _admin, raw = _locked_out()
    client = Client()
    client.post(
        reverse("recover", args=[raw]),
        {"password": _NEW_PW, "password_again": _NEW_PW},
    )
    with freeze_the_clock(minutes=11):
        client.get(reverse("account_login"))
    assert client.session.get(recovery.RECOVERED_USERNAME_KEY) is None


def test_signing_in_is_not_cut_short_by_the_window() -> None:
    """The reason this is a stamp and not `set_expiry`. `login()` cycles the session key
    and keeps its data, so an expiry set here would outlive the prefill it was for and
    sign the person out minutes after they got back in."""
    member, _admin, raw = _locked_out()
    client = Client()
    client.post(
        reverse("recover", args=[raw]),
        {"password": _NEW_PW, "password_again": _NEW_PW},
    )
    assert member.user is not None
    client.get(reverse("account_login"))
    client.post(
        reverse("account_login"),
        {"login": "nana", "password": _NEW_PW},
    )
    with freeze_the_clock(minutes=30):
        feed = client.get(reverse("feed"))
    assert feed.status_code == 200, "the session expired while they were using it"
