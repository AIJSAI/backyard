"""S-805 break-glass admin recovery tests.

The console command is the ONLY source of a reset token; the view consumes one
and resets a password; every invalid/expired/tampered token 404s uniformly; and
there is no web path that mints a token (T-AUTH-G1).
"""

from __future__ import annotations

import io

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

pytestmark = pytest.mark.django_db
User = get_user_model()


def _admin(username: str = "james") -> object:
    return User.objects.create_superuser(username=username, password="old-Passphrase-9")


def _url_for(user: object) -> str:
    uid = urlsafe_base64_encode(force_bytes(user.pk))  # type: ignore[attr-defined]
    token = default_token_generator.make_token(user)
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
    User.objects.create_user(username="plain", password="old-Passphrase-9")  # not a superuser
    with pytest.raises(CommandError):
        call_command("break_glass", "plain")


def test_reset_sets_new_password_and_kills_the_token() -> None:
    admin = _admin()
    url = _url_for(admin)
    response = Client().post(url, {"password": "a-New-Passphrase-42"})
    assert response.status_code == 302  # to login
    admin.refresh_from_db()  # type: ignore[attr-defined]
    assert admin.check_password("a-New-Passphrase-42")  # type: ignore[attr-defined]
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
    admin.refresh_from_db()  # type: ignore[attr-defined]
    assert admin.check_password("old-Passphrase-9")  # type: ignore[attr-defined]  # unchanged


def test_no_web_route_mints_a_token() -> None:
    """There is no self-serve admin-recovery endpoint: the only token source is the
    console command. A GET to a recover-style path is not routed."""
    _admin()
    for path in ("/break-glass/", "/accounts/recover-admin/", "/break-glass/request/"):
        assert Client().get(path).status_code == 404
