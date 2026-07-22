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

from core.models import Member, Pod, PodMembership, SetupToken, Yard

User = get_user_model()
SECRET = "correct-horse-battery-staple-42"
_PW = "a-Strong-passphrase-9"  # a throwaway test passphrase, not a credential


def _valid_data(**overrides: str) -> dict[str, str]:
    """A complete valid setup POST: the wizard now also names the first yard and
    pod (S-801), so every test starts from a full payload and overrides one field."""
    data = {
        "setup_secret": SECRET,
        "username": "james",
        "password": "a-Strong-passphrase-9",
        "display_name": "James",
        "yard_name": "Mom's side",
        "pod_name": "Our house",
    }
    data.update(overrides)
    return data


@pytest.fixture
def token(db: None) -> SetupToken:
    return SetupToken.objects.create(token_hash=make_password(SECRET))


def test_home_redirects_to_setup_when_no_admin(db: None) -> None:
    resp = Client().get(reverse("home"))
    assert resp.status_code == 302
    assert resp.headers["Location"] == reverse("setup")


def test_setup_creates_admin_with_correct_secret(token: SetupToken) -> None:
    resp = Client().post(reverse("setup"), _valid_data())
    assert resp.status_code == 302
    assert resp.headers["Location"] == reverse("home")
    admin = User.objects.get(username="james")
    assert admin.is_superuser
    # The gate closes: the token is consumed.
    assert not SetupToken.objects.exists()


def test_setup_creates_first_yard_pod_and_admin_membership(token: SetupToken) -> None:
    """S-801: the wizard creates the admin, the first yard, and the first pod, and
    makes the admin an instance-admin member of that pod, all in one atomic act."""
    Client().post(reverse("setup"), _valid_data())

    yard = Yard.objects.get()
    assert yard.name == "Mom's side"
    assert yard.slug  # a real slug was generated
    pod = Pod.objects.get()
    assert pod.name == "Our house"
    assert list(pod.yards.all()) == [yard]  # the pod belongs to the first yard
    member = Member.objects.get()
    assert member.display_name == "James"
    assert member.role == Member.INSTANCE_ADMIN
    assert member.user is not None and member.user.username == "james"
    assert PodMembership.objects.filter(member=member, pod=pod).exists()


def test_setup_rejects_missing_yard_or_pod_name(token: SetupToken) -> None:
    """Missing yard or pod name fails the wizard, and nothing is created: the
    admin, yard, and pod either all land or none do (atomic)."""
    resp = Client().post(reverse("setup"), _valid_data(yard_name=""))
    assert resp.status_code == 200
    assert not User.objects.filter(is_superuser=True).exists()
    assert Yard.objects.count() == 0 and Pod.objects.count() == 0 and Member.objects.count() == 0

    resp = Client().post(reverse("setup"), _valid_data(pod_name=""))
    assert resp.status_code == 200
    assert Member.objects.count() == 0


def test_setup_rejects_wrong_secret(token: SetupToken) -> None:
    resp = Client().post(reverse("setup"), _valid_data(setup_secret="wrong"))
    assert resp.status_code == 200
    assert not User.objects.filter(is_superuser=True).exists()
    assert SetupToken.objects.exists()


def test_setup_rejects_weak_password(token: SetupToken) -> None:
    resp = Client().post(reverse("setup"), _valid_data(password="123"))
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
    resp = Client().post(reverse("setup"), _valid_data(username="second"))
    assert resp.status_code == 404
    assert User.objects.filter(is_superuser=True).count() == 1


def test_setup_rejects_bad_username(token: SetupToken) -> None:
    resp = Client().post(reverse("setup"), _valid_data(username="no spaces!"))
    assert resp.status_code == 200
    assert not User.objects.filter(is_superuser=True).exists()


def test_setup_rejects_password_equal_to_username(token: SetupToken) -> None:
    resp = Client().post(
        reverse("setup"), _valid_data(username="solitude-92", password="solitude-92")
    )
    assert resp.status_code == 200
    assert not User.objects.filter(is_superuser=True).exists()


def test_setup_enforces_csrf(token: SetupToken) -> None:
    # With CSRF enforcement on and no token supplied, the POST is rejected (403),
    # proving the wizard is CSRF-protected.
    resp = Client(enforce_csrf_checks=True).post(reverse("setup"), _valid_data())
    assert resp.status_code == 403
    assert not User.objects.filter(is_superuser=True).exists()


def test_home_shows_landing_to_a_logged_out_visitor(db: None) -> None:
    User.objects.create_superuser(username="nana", password=_PW)
    resp = Client().get(reverse("home"))  # anonymous visitor to a set-up instance
    assert resp.status_code == 200
    assert b"Backyard is running" in resp.content


def test_home_routes_a_signed_in_member_to_their_feed(db: None) -> None:
    """S-101: the root is never a dead-end hello-world for someone with an account; a
    signed-in member is taken straight to their feed."""
    user = User.objects.create_user(username="cousin", password=_PW)
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Household")
    pod.yards.set([yard])
    member = Member.objects.create(display_name="Cousin", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    # An admin must exist for the root not to route to setup.
    User.objects.create_superuser(username="nana", password=_PW)

    client = Client()
    client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
    resp = client.get(reverse("home"))
    assert resp.status_code == 302
    assert resp.headers["Location"] == reverse("feed")


def test_healthz_ok(db: None) -> None:
    resp = Client().get(reverse("healthz"))
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
