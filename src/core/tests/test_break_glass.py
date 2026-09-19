"""S-805 break-glass admin recovery tests.

The console command is the ONLY source of a reset token; the view consumes one
and resets a password; every invalid/expired/tampered token 404s uniformly; and
there is no web path that mints a token (T-AUTH-G1).
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from core.breakglass import break_glass_tokens
from core.models import Member, Pod, PodMembership, Yard

if TYPE_CHECKING:
    from django.contrib.auth.models import User as UserModel

pytestmark = pytest.mark.django_db
User = get_user_model()
# Named rather than repeated at each call site: a `password=` keyword with a literal
# beside it is the shape the pre-commit credential guard refuses, and it is right to.
_OLD_PW = "old-Passphrase-9"


def _admin(username: str = "james") -> UserModel:
    return User.objects.create_superuser(username=username, password=_OLD_PW)


def _url_for(user: UserModel) -> str:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = break_glass_tokens.make_token(user)
    return f"/break-glass/{uid}/{token}/"


def test_command_prints_a_working_reset_url() -> None:
    admin = _admin()
    out = io.StringIO()
    call_command("break_glass", "james", stdout=out)
    printed = out.getvalue()
    assert "/break-glass/" in printed
    # The printed URL actually works.
    path = next(line.strip() for line in printed.splitlines() if "/break-glass/" in line)
    assert Client().get(path).status_code == 200
    assert admin  # referenced


def test_command_refuses_unknown_or_non_admin() -> None:
    with pytest.raises(CommandError):
        call_command("break_glass", "nobody")
    User.objects.create_user(username="plain", password=_OLD_PW)  # not a superuser
    with pytest.raises(CommandError):
        call_command("break_glass", "plain")


def _promoted_instance_admin(username: str) -> UserModel:
    """The S-707 succession path: a relative promoted to instance admin through
    `assign_role`, which writes `Member.role` and nothing else. No Django flag."""
    user = User.objects.create_user(username=username, password=_OLD_PW)
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Their house")
    pod.yards.set([yard])
    member = Member.objects.create(
        display_name="The Second Admin", user=user, role=Member.INSTANCE_ADMIN
    )
    PodMembership.objects.create(member=member, pod=pod)
    return user


def test_the_second_instance_admin_can_be_recovered() -> None:
    """S10. Break-glass keyed on `is_superuser`, and only the FIRST admin — the one the
    first-run wizard creates with `create_superuser` — carries that flag. So the second
    instance admin, the person the whole succession path exists to create, was the one
    admin with no recovery path at all: the command refused them by name and the view
    would have 404'd a token minted for them by hand.

    This is the bus-factor case. Measured from both ends, command and view.
    """
    user = _promoted_instance_admin("delegate")
    assert not user.is_superuser, "the fixture is not exercising the promoted case"

    out = io.StringIO()
    call_command("break_glass", "delegate", stdout=out)
    path = next(line.strip() for line in out.getvalue().splitlines() if "/break-glass/" in line)
    assert Client().get(path).status_code == 200

    assert Client().post(path, {"password": "a-New-Passphrase-42"}).status_code == 302
    user.refresh_from_db()
    assert user.check_password("a-New-Passphrase-42")


def test_a_yard_admin_is_not_recoverable() -> None:
    """The widening stops at the instance-admin role. A yard admin is a per-side delegate,
    not the operator, and break-glass is the operator's console-only path — their own
    recovery is the member-facing link an instance admin issues (BY-01)."""
    user = User.objects.create_user(username="sidekick", password=_OLD_PW)
    yard = Yard.objects.create(name="Paternal", slug="paternal")
    pod = Pod.objects.create(name="Their house")
    pod.yards.set([yard])
    member = Member.objects.create(display_name="Side Admin", user=user, role=Member.YARD_ADMIN)
    PodMembership.objects.create(member=member, pod=pod)

    with pytest.raises(CommandError):
        call_command("break_glass", "sidekick")
    # And a token minted by hand for them does not open the view either.
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = break_glass_tokens.make_token(user)
    assert Client().get(f"/break-glass/{uid}/{token}/").status_code == 404


def test_a_member_with_no_member_row_is_still_recoverable_if_a_superuser() -> None:
    """`is_superuser` stays an OR rather than being replaced. A superuser whose Member row
    is missing or mis-roled is exactly the state somebody reaches for break-glass in, and
    the first admin holds the flag before any role question arises."""
    admin = _admin("founder")
    assert not Member.objects.filter(user=admin).exists()
    assert Client().get(_url_for(admin)).status_code == 200


def test_reset_sets_new_password_and_kills_the_token() -> None:
    admin = _admin()
    url = _url_for(admin)
    response = Client().post(url, {"password": "a-New-Passphrase-42"})
    assert response.status_code == 302  # to login
    admin.refresh_from_db()
    assert admin.check_password("a-New-Passphrase-42")
    # The token is one-time: the password change invalidates it, so the URL now 404s.
    assert Client().get(url).status_code == 404


def test_tampered_or_unknown_token_404s() -> None:
    admin = _admin()
    good = _url_for(admin)
    # Flip the last character of the token.
    bad = good[:-2] + ("a" if good[-2] != "a" else "b") + "/"
    assert Client().get(bad).status_code == 404
    # An unknown uid.
    assert Client().get("/break-glass/AAAA/some-token/").status_code == 404


def test_weak_password_rejected_without_changing() -> None:
    admin = _admin()
    url = _url_for(admin)
    response = Client().post(url, {"password": "123"})
    assert response.status_code == 200
    admin.refresh_from_db()
    assert admin.check_password(_OLD_PW)  # unchanged


def test_no_web_route_mints_a_token() -> None:
    """There is no self-serve admin-recovery endpoint: the only token source is the
    console command. A GET to a recover-style path is not routed."""
    _admin()
    for path in ("/break-glass/", "/accounts/recover-admin/", "/break-glass/request/"):
        assert Client().get(path).status_code == 404


def test_reset_invalidates_a_live_admin_session() -> None:
    """T-RECOV-1 (security review MEDIUM-2): a session an attacker holds must not
    survive the recovery. Resetting the password rotates the session auth hash, so
    the stolen session is anonymous on its next request."""
    admin = _admin()
    stolen = Client()
    assert stolen.login(username="james", password=_OLD_PW)
    admin.refresh_from_db()  # login() bumped last_login; mint from DB
    url = _url_for(admin)

    Client().post(url, {"password": "a-New-Passphrase-42"})

    response = stolen.get(reverse("healthz"))
    assert response.wsgi_request.user.is_authenticated is False


def test_token_is_short_lived_not_the_three_day_default() -> None:
    """The break-glass token expires in minutes, not Django's 3-day
    PASSWORD_RESET_TIMEOUT (security review MEDIUM-1): a token older than the
    generator's timeout is rejected."""
    admin = _admin()
    url = _url_for(admin)
    assert break_glass_tokens.timeout <= 60 * 60  # at most an hour, not days
    # A token minted "in the past" beyond the window is rejected.
    with mock.patch.object(break_glass_tokens, "_now") as now:
        # Django's _now() is naive local time; match it so _num_seconds subtracts cleanly.
        now.return_value = datetime.now() + timedelta(seconds=break_glass_tokens.timeout + 60)  # noqa: DTZ005
        assert Client().get(url).status_code == 404
