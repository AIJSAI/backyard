"""A password reset link is mailed only to an address its owner has confirmed.

core/join.py stores the address a relative types at join as `verified=False` "so a typo
cannot silently hand recovery of this account to whoever owns the address that was actually
typed". django-allauth's reset form looks the address up with `prefer_verified=True`, which
PREFERS a confirmed row and falls back to an unconfirmed one, so the guarantee that comment
states did not hold: the stranger who owns the mistyped mailbox gets the confirmation mail
(which names the site), asks for a reset, and is sent a link into somebody else's account.

Measured during the review of #209. These tests fail against allauth's own form.
"""

from __future__ import annotations

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client
from django.urls import reverse

from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db

_PW = "-".join(("a", "throwaway", "phrase", "for", "tests"))


def _member(username: str, address: str, *, verified: bool, primary: bool = True) -> None:
    yard, _ = Yard.objects.get_or_create(name="One side", slug="one-side")
    pod, _ = Pod.objects.get_or_create(name="A household", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = get_user_model().objects.create_user(username=username, password=_PW)
    member = Member.objects.create(display_name=username.title(), user=user)
    PodMembership.objects.create(member=member, pod=pod)
    EmailAddress.objects.create(user=user, email=address, primary=primary, verified=verified)


def _ask_for_a_reset(address: str) -> tuple[int, str]:
    response = Client().post(reverse("account_reset_password"), {"email": address})
    return response.status_code, response.headers.get("Location", "")


def _links() -> list[str]:
    return [str(m.body) for m in mail.outbox if "/accounts/password/reset/key/" in str(m.body)]


def test_an_unconfirmed_address_is_sent_no_reset_link() -> None:
    _member("nana", "mistyped@example.com", verified=False)
    status, where = _ask_for_a_reset("mistyped@example.com")
    assert status == 302
    assert not _links(), "a reset link went to an address nobody has confirmed"
    # Something is still sent, so the mailbox owner is told what happened and the page has
    # nothing to give away: allauth's "no such account" mail, in this product's words.
    assert len(mail.outbox) == 1
    assert "No account here has confirmed this address" in mail.outbox[0].body
    assert where == reverse("account_reset_password_done")


def test_a_confirmed_address_still_gets_its_link() -> None:
    _member("nana", "nana@example.com", verified=True)
    status, _where = _ask_for_a_reset("NaNa@Example.com")
    assert status == 302
    assert len(_links()) == 1, "a confirmed address must keep working, in any letter case"


def test_the_page_answers_the_same_way_either_way() -> None:
    """ACCOUNT_PREVENT_ENUMERATION is the reason this narrowing is safe to add: confirmed,
    unconfirmed and unknown all redirect to the same page, and each sends exactly one mail
    with the same subject."""
    _member("nana", "confirmed@example.com", verified=True)
    _member("papa", "unconfirmed@example.com", verified=False)
    answers = {
        address: _ask_for_a_reset(address)
        for address in ("confirmed@example.com", "unconfirmed@example.com", "nobody@example.com")
    }
    assert len(set(answers.values())) == 1, answers
    assert len(mail.outbox) == 3
    assert len({m.subject for m in mail.outbox}) == 1, [m.subject for m in mail.outbox]


def test_a_second_unconfirmed_address_cannot_borrow_the_first_ones_confirmation() -> None:
    """Confirmed means THIS address. A member with a confirmed primary and an unconfirmed
    second address gets no link at the second one."""
    _member("nana", "nana@example.com", verified=True)
    user = get_user_model().objects.get(username="nana")
    EmailAddress.objects.create(
        user=user, email="second@example.com", primary=False, verified=False
    )
    _ask_for_a_reset("second@example.com")
    assert not _links()
