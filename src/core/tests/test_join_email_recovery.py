"""An invite-joined member must have a way back in after forgetting their password.

The defect: `join.html` collected display name, username and password and NOTHING else, so
the account had no `allauth.account.models.EmailAddress` row. allauth resolves a password
reset against `EmailAddress`, not `User.email`, so "Forgot your password?" found nothing to
send to -- and because `ACCOUNT_PREVENT_ENUMERATION = True` (correctly) makes that page say
"check your inbox" either way, the member got no signal at all that they were locked out
permanently. There is no admin control to fix it afterwards either.

Email stays OPTIONAL -- an invite-token member may genuinely not have one, and that is the
reason this custom view exists (`ACCOUNT_EMAIL_VERIFICATION = "optional"`). The fix is that
supplying one has to actually BUY the recovery path it implies.

These assert the reset path end to end rather than that a form field renders: a field that
collects an address nothing ever reads would satisfy a template test and still leave the
member locked out.
"""

from __future__ import annotations

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client
from django.urls import reverse

from core.invites import mint_invite
from core.models import Member, Pod, Yard

User = get_user_model()
_PW = "a-Strong-passphrase-9"


def _pod() -> Pod:
    yard = Yard.objects.create(name="Y", slug="y")
    pod = Pod.objects.create(name="P")
    pod.yards.set([yard])
    return pod


def _join(pod: Pod, **extra: str) -> Client:
    _, raw = mint_invite(pod, None)
    client = Client()
    response = client.post(
        reverse("join", args=[raw]),
        {"display_name": "Cousin Reed", "username": "cousinreed", "password": _PW, **extra},
    )
    assert response.status_code == 302, response.status_code
    return client


@pytest.mark.django_db
def test_an_address_given_at_join_can_actually_reset_the_password() -> None:
    """The whole point: a member who supplies an address gets a real recovery path."""
    _join(_pod(), email="reed@example.com")
    member = Member.objects.get(display_name="Cousin Reed")
    assert member.user is not None

    # The row allauth actually looks a reset up against.
    address = EmailAddress.objects.get(user=member.user)
    assert address.email == "reed@example.com"
    assert address.primary is True
    assert address.verified is False, (
        "unconfirmed on purpose: a typo must not hand recovery of this account to whoever "
        "owns the address that was actually typed"
    )

    mail.outbox.clear()
    response = Client().post(reverse("account_reset_password"), {"email": "reed@example.com"})
    assert response.status_code in (302, 200)
    assert len(mail.outbox) == 1, (
        "a member who gave an address at join still cannot reset their password -- "
        "allauth resolves resets against EmailAddress, not User.email"
    )
    assert "reed@example.com" in mail.outbox[0].to


@pytest.mark.django_db
def test_joining_without_an_address_still_works_and_creates_no_row() -> None:
    """Email is optional and must stay optional: requiring it would lock out exactly the
    members this custom view exists for (ADR-002 / S-101, `ACCOUNT_EMAIL_VERIFICATION`)."""
    _join(_pod())
    member = Member.objects.get(display_name="Cousin Reed")
    assert member.user is not None
    assert not EmailAddress.objects.filter(user=member.user).exists()
    assert member.user.email == ""


@pytest.mark.django_db
def test_a_malformed_address_is_refused_rather_than_silently_dropped() -> None:
    """A typo'd address is worse than a blank one, because it is a recovery path the member
    believes they have and does not. The invite must survive the rejection."""
    pod = _pod()
    _, raw = mint_invite(pod, None)
    response = Client().post(
        reverse("join", args=[raw]),
        {
            "display_name": "Cousin Reed",
            "username": "cousinreed",
            "password": _PW,
            "email": "reed-at-example-dot-com",
        },
    )
    assert response.status_code == 200, "a bad address must re-render, not redirect"
    assert not Member.objects.filter(display_name="Cousin Reed").exists()

    # The invite was NOT burned by the rejected attempt: they can fix the typo and retry.
    retry = Client().post(
        reverse("join", args=[raw]),
        {
            "display_name": "Cousin Reed",
            "username": "cousinreed",
            "password": _PW,
            "email": "reed@example.com",
        },
    )
    assert retry.status_code == 302, "the rejected attempt consumed the invite"
    assert EmailAddress.objects.filter(email="reed@example.com").exists()


@pytest.mark.django_db
def test_the_join_form_says_what_skipping_the_address_costs() -> None:
    """The consequence is invisible at the moment of choosing, and irreversible after.

    Asserted on the RENDERED page, not the template source, so a comment cannot satisfy it --
    the failure mode that made an earlier guard in this repo vacuous.
    """
    pod = _pod()
    _, raw = mint_invite(pod, None)
    html = Client().get(reverse("join", args=[raw])).content.decode()
    assert 'name="email"' in html
    assert "optional" in html.lower(), "the field must not read as required"
    assert "forget your password" in html.lower(), (
        "the form must say what skipping the address costs; without it the member is "
        "choosing permanent lockout with no way to know"
    )
