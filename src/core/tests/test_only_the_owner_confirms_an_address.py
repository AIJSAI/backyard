"""A confirmation link proves a mailbox. Only its own account may spend it.

The reset narrowing (test_a_reset_goes_only_to_a_confirmed_address.py) keys on
`EmailAddress.verified`, so whoever can SET that flag can take the account. allauth's
confirmation view is `login_not_required`, so before core.adapters.AccountAdapter.
confirm_email the stranger who received a mistyped join mail could set it himself: confirm,
ask for a reset, receive the link. Measured end to end on 2026-09-19 in a throwaway
database, by the security review of the narrowing.
"""

from __future__ import annotations

import pytest
from allauth.account import app_settings
from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client
from django.urls import reverse

from core.models import DigestSubscription, Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db

_PW = "-".join(("a", "throwaway", "phrase", "for", "tests"))


def _member(username: str, address: str) -> EmailAddress:
    yard, _ = Yard.objects.get_or_create(name="One side", slug="one-side")
    pod, _ = Pod.objects.get_or_create(name="A household", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = get_user_model().objects.create_user(username=username, password=_PW)
    member = Member.objects.create(display_name=username.title(), user=user)
    PodMembership.objects.create(member=member, pod=pod)
    return EmailAddress.objects.create(user=user, email=address, primary=True, verified=False)


def _links() -> list[str]:
    return [str(m.body) for m in mail.outbox if "/accounts/password/reset/key/" in str(m.body)]


def _confirm_url(address: EmailAddress) -> str:
    return reverse("account_confirm_email", args=[EmailConfirmationHMAC(address).key])


def test_a_stranger_holding_the_link_cannot_confirm_and_cannot_then_reset() -> None:
    address = _member("nana", "mistyped@example.com")
    stranger = Client()  # never signed in as anybody

    response = stranger.post(_confirm_url(address))

    address.refresh_from_db()
    assert address.verified is False, "a stranger set the flag the reset trusts"
    assert reverse("account_login") in response.headers.get("Location", "")
    mail.outbox.clear()
    stranger.post(reverse("account_reset_password"), {"email": "mistyped@example.com"})
    assert not _links(), "confirm-then-reset handed an account to whoever owns the mailbox"


def test_a_strangers_tap_does_not_start_email_updates_either() -> None:
    """core/signals.py starts Email Updates when a PRIMARY address is confirmed, so the same
    tap used to start family posts flowing to the mistyped mailbox."""
    address = _member("nana", "mistyped@example.com")
    member = Member.objects.get(user=address.user)
    DigestSubscription.objects.create(member=member, address="mistyped@example.com")

    Client().post(_confirm_url(address))

    assert DigestSubscription.objects.get(member=member).confirmed_at is None


def test_another_relative_cannot_confirm_it_for_them() -> None:
    address = _member("nana", "nana@example.com")
    _member("papa", "papa@example.com")
    client = Client()
    assert client.login(username="papa", password=_PW)

    client.post(_confirm_url(address))

    address.refresh_from_db()
    assert address.verified is False


def test_the_member_whose_address_it_is_still_confirms_in_one_tap() -> None:
    address = _member("nana", "nana@example.com")
    client = Client()
    assert client.login(username="nana", password=_PW)

    client.post(_confirm_url(address))

    address.refresh_from_db()
    assert address.verified is True, "the owner's own confirmation must still work"
    mail.outbox.clear()
    Client().post(reverse("account_reset_password"), {"email": "nana@example.com"})
    assert len(_links()) == 1


def test_a_signed_out_member_is_sent_to_sign_in_and_lands_back_on_the_link() -> None:
    """The cost of the rule, stated: one sign-in, then the same link works."""
    address = _member("nana", "nana@example.com")
    url = _confirm_url(address)
    client = Client()

    where = client.post(url).headers.get("Location", "")

    assert reverse("account_login") in where and "next=" in where
    client.post(reverse("account_login"), {"login": "nana", "password": _PW})
    client.post(url)
    address.refresh_from_db()
    assert address.verified is True


def test_the_two_by_code_flows_that_bypass_the_hook_stay_off() -> None:
    """allauth's verify_email_indirectly marks an address confirmed WITHOUT calling the
    adapter hook above, and only these two features reach it. Turning either on re-opens
    the hole unless it grows its own check, so the precondition is pinned."""
    assert app_settings.LOGIN_BY_CODE_ENABLED is False
    assert app_settings.PASSWORD_RESET_BY_CODE_ENABLED is False
