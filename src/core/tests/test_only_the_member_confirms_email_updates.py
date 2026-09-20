"""An Email Updates confirmation link proves a mailbox. Only the member who asked may spend it.

A signed-in member can point Email Updates at any address, and a mistyped one is delivered
to a stranger. His tap used to be the whole gate: the family's posts, names and next week's
birthdays then went to him on every send, with links that render that slice of the feed, its
replies and its photos to anybody who opens them. Measured end to end on 2026-09-19 in a
throwaway database, by the security review that also closed the account-confirmation form of
the same hole (test_only_the_owner_confirms_an_address.py).
"""

from __future__ import annotations

import datetime
import re

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import digesting
from core.models import DigestSubscription, Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db

_PW = "-".join(("a", "throwaway", "phrase", "for", "tests"))


def _member(username: str) -> Member:
    yard, _ = Yard.objects.get_or_create(name="One side", slug="one-side")
    pod, _ = Pod.objects.get_or_create(name="A household", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = get_user_model().objects.create_user(username=username, password=_PW)
    member = Member.objects.create(display_name=username.title(), user=user)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _asked_for_updates_at_a_mistyped_address(member: Member) -> str:
    digesting.subscribe(member, address="mistyped@example.com", cadence="weekly")
    found = re.search(r"/digest/confirm/([^/\s]+)/", str(mail.outbox[-1].body))
    assert found, "no confirmation link was mailed"
    return reverse("digest_confirm", args=[found.group(1)])


def _confirmed(member: Member) -> bool:
    return DigestSubscription.objects.get(member=member).confirmed_at is not None


def test_a_stranger_holding_the_link_cannot_start_the_updates() -> None:
    nana = _member("nana")
    url = _asked_for_updates_at_a_mistyped_address(nana)
    stranger = Client()  # never signed in as anybody

    assert stranger.get(url).status_code == 200, "the question still loads from an inbox"
    response = stranger.post(url)

    assert not _confirmed(nana), "a stranger's tap started family mail to his own mailbox"
    assert reverse("account_login") in response.headers.get("Location", "")
    later = timezone.now() + datetime.timedelta(days=30)
    assert digesting.due_recipients(later) == []


def test_another_relative_cannot_confirm_it_for_them() -> None:
    nana = _member("nana")
    _member("papa")
    url = _asked_for_updates_at_a_mistyped_address(nana)
    client = Client()
    assert client.login(username="papa", password=_PW)

    client.post(url)

    assert not _confirmed(nana)


def test_the_member_who_asked_confirms_in_one_tap() -> None:
    nana = _member("nana")
    url = _asked_for_updates_at_a_mistyped_address(nana)
    client = Client()
    assert client.login(username="nana", password=_PW)

    response = client.post(url)

    assert response.status_code == 200
    assert _confirmed(nana)


def test_a_signed_out_member_is_sent_to_sign_in_and_lands_back_on_the_link() -> None:
    """The cost of the rule, stated: one sign-in, then the same link works. The page says so
    before the button does it."""
    nana = _member("nana")
    url = _asked_for_updates_at_a_mistyped_address(nana)
    client = Client()

    assert "You will be asked to sign in first." in client.get(url).content.decode()
    where = client.post(url).headers.get("Location", "")
    assert reverse("account_login") in where and "next=" in where

    client.post(reverse("account_login"), {"login": "nana", "password": _PW})
    assert "You will be asked to sign in first." not in client.get(url).content.decode()
    client.post(url)
    assert _confirmed(nana)


def test_stopping_the_updates_still_needs_nothing_but_the_link() -> None:
    """The other direction stays open on purpose: anybody holding a mailbox must be able to
    make mail to it stop, signed in or not."""
    nana = _member("nana")
    url = _asked_for_updates_at_a_mistyped_address(nana)
    client = Client()
    assert client.login(username="nana", password=_PW)
    client.post(url)
    subscription = DigestSubscription.objects.get(member=nana)
    raw = digesting.rotate_unsubscribe_token(subscription)

    Client().post(reverse("digest_unsubscribe", args=[raw]))

    subscription.refresh_from_db()
    assert subscription.enabled is False


def test_a_relative_signed_in_as_themselves_is_told_and_not_looped() -> None:
    """Signed in as somebody else is not the same as signed out. Bouncing them to sign in
    sends an already-authenticated reader straight back here, whose button bounces them
    again: a silent loop with no exit, on the shared tablet that makes it likely. The
    refusal test above proves nothing is written; this one proves somebody is told."""
    nana = _member("nana")
    _member("papa")
    url = _asked_for_updates_at_a_mistyped_address(nana)
    client = Client()
    assert client.login(username="papa", password=_PW)

    response = client.post(url, follow=True)

    assert response.redirect_chain == [], response.redirect_chain
    assert "signed in as somebody else" in response.content.decode().lower()
    assert not _confirmed(nana)
