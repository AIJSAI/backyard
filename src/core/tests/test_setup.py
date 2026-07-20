"""Tests for the first-run wizard and the TM-8 gate.

These are the seed of S-801's acceptance tests: the wizard exists only while no
admin exists, it is protected by the console secret, and it closes for good once
the first admin is created.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from core.models import SetupToken

User = get_user_model()
SECRET = "correct-horse-battery-staple-42"


@pytest.fixture
def token(db: None) -> SetupToken:
    return SetupToken.objects.create(token_hash=make_password(SECRET))


def test_home_redirects_to_setup_when_no_admin(db: None) -> None:
    resp = Client().get(reverse("home"))
    assert resp.status_code == 302
    assert resp.headers["Location"] == reverse("setup")


def test_setup_creates_admin_with_correct_secret(token: SetupToken) -> None:
    resp = Client().post(
        reverse("setup"),
        {"setup_secret": SECRET, "username": "james", "password": "a-Strong-passphrase-9"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == reverse("home")
    admin = User.objects.get(username="james")
    assert admin.is_superuser
    # The gate closes: the token is consumed.
    assert not SetupToken.objects.exists()


def test_setup_rejects_wrong_secret(token: SetupToken) -> None:
    resp = Client().post(
        reverse("setup"),
        {"setup_secret": "wrong", "username": "james", "password": "a-Strong-passphrase-9"},
    )
    assert resp.status_code == 200
    assert not User.objects.filter(is_superuser=True).exists()
    assert SetupToken.objects.exists()


def test_setup_rejects_weak_password(token: SetupToken) -> None:
    resp = Client().post(
        reverse("setup"),
        {"setup_secret": SECRET, "username": "james", "password": "123"},
    )
    assert resp.status_code == 200
    assert not User.objects.filter(is_superuser=True).exists()


def test_setup_404s_after_admin_exists(db: None) -> None:
    User.objects.create_superuser(username="already", password="a-Strong-passphrase-9")
    assert Client().get(reverse("setup")).status_code == 404
    assert Client().post(reverse("setup"), {}).status_code == 404


def test_setup_gate_closes_under_lock(token: SetupToken) -> None:
    # An admin appears after the early check but before the atomic create; the POST,
    # carrying a valid secret, must still 404 rather than create a second admin.
    User.objects.create_superuser(username="racer", password="a-Strong-passphrase-9")
    resp = Client().post(
        reverse("setup"),
        {"setup_secret": SECRET, "username": "second", "password": "a-Strong-passphrase-9"},
    )
    assert resp.status_code == 404
    assert User.objects.filter(is_superuser=True).count() == 1


def test_setup_rejects_bad_username(token: SetupToken) -> None:
    resp = Client().post(
        reverse("setup"),
        {"setup_secret": SECRET, "username": "no spaces!", "password": "a-Strong-passphrase-9"},
    )
    assert resp.status_code == 200
    assert not User.objects.filter(is_superuser=True).exists()


def test_setup_rejects_password_equal_to_username(token: SetupToken) -> None:
    resp = Client().post(
        reverse("setup"),
        {"setup_secret": SECRET, "username": "solitude-92", "password": "solitude-92"},
    )
    assert resp.status_code == 200
    assert not User.objects.filter(is_superuser=True).exists()


def test_setup_enforces_csrf(token: SetupToken) -> None:
    # With CSRF enforcement on and no token supplied, the POST is rejected (403),
    # proving the wizard is CSRF-protected.
    resp = Client(enforce_csrf_checks=True).post(
        reverse("setup"),
        {"setup_secret": SECRET, "username": "james", "password": "a-Strong-passphrase-9"},
    )
    assert resp.status_code == 403
    assert not User.objects.filter(is_superuser=True).exists()


def test_home_shows_admin_after_setup(db: None) -> None:
    User.objects.create_superuser(username="nana", password="a-Strong-passphrase-9")
    resp = Client().get(reverse("home"))
    assert resp.status_code == 200
    assert b"Backyard is running" in resp.content


def test_healthz_ok(db: None) -> None:
    resp = Client().get(reverse("healthz"))
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
