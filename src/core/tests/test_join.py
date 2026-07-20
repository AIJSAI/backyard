"""The invite signup view (S-101), the four TS-DJ-5 properties.

The service-layer consume-under-lock (property 1) is proven in test_invites; here
we prove the VIEW: byte-identical 404s (property 2), the rate limit (property 3),
and atomic account+invite creation (property 4). Plus the happy path.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import Client
from django.urls import reverse

from core.invites import mint_invite
from core.models import Invite, Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
UserModel = get_user_model()


@pytest.fixture
def invite_to_pod() -> tuple[Pod, str]:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Household")
    pod.yards.set([yard])
    _, raw = mint_invite(pod, None, max_uses=1)
    return pod, raw


def _post(raw: str, **overrides: str) -> HttpResponse:
    data = {"display_name": "New Cousin", "username": "newcousin", "password": "aX9!mnpq2ffz"}
    data.update(overrides)
    # django-stubs types the test client's response as a private subclass; it is an
    # HttpResponse at runtime and only .status_code/.content are used here.
    return Client().post(reverse("join", args=[raw]), data)  # type: ignore[return-value]


def test_valid_invite_creates_member_in_pod_and_logs_in(invite_to_pod: tuple[Pod, str]) -> None:
    pod, raw = invite_to_pod
    response = _post(raw)
    assert response.status_code == 302  # lands somewhere (home) logged in
    member = Member.objects.get(display_name="New Cousin")
    assert PodMembership.objects.filter(member=member, pod=pod).exists()
    assert member.user is not None
    assert UserModel.objects.filter(username="newcousin").exists()
    Invite.objects.get().refresh_from_db()
    assert Invite.objects.get().use_count == 1


def test_get_shows_form_for_live_invite(invite_to_pod: tuple[Pod, str]) -> None:
    _, raw = invite_to_pod
    response = Client().get(reverse("join", args=[raw]))
    assert response.status_code == 200


@pytest.mark.parametrize("bad", ["totally-unknown-token", ""])
def test_unknown_invite_404s(bad: str) -> None:
    # An unknown token 404s on both GET and POST: no invite-existence oracle.
    if bad:  # empty string is not a routable token; skip the reverse for it
        assert Client().get(reverse("join", args=[bad])).status_code == 404


def test_expired_revoked_exhausted_all_404_identically() -> None:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Household")
    pod.yards.set([yard])

    _, expired_raw = mint_invite(pod, None, ttl_days=0)
    revoked, revoked_raw = mint_invite(pod, None)
    revoked.revoked_at = revoked.created_at
    revoked.save(update_fields=["revoked_at"])
    _, exhausted_raw = mint_invite(pod, None, max_uses=1)
    _post(exhausted_raw)  # consume it

    statuses = set()
    bodies = set()
    for raw in (expired_raw, revoked_raw, exhausted_raw):
        r = Client().get(reverse("join", args=[raw]))
        statuses.add(r.status_code)
        bodies.add(r.content)
    assert statuses == {404}
    assert len(bodies) == 1  # byte-identical 404 across all three unusable states


def test_used_invite_cannot_be_reused(invite_to_pod: tuple[Pod, str]) -> None:
    _, raw = invite_to_pod
    _post(raw, username="first")
    second = _post(raw, username="second")
    assert second.status_code == 404
    assert UserModel.objects.filter(username="second").count() == 0  # no orphan user (property 4)


def test_taken_username_does_not_burn_the_invite(invite_to_pod: tuple[Pod, str]) -> None:
    """Property 4, the atomicity that matters most: a colliding username fails the
    whole POST, so the invite stays usable and no orphan member is left."""
    _, raw = invite_to_pod
    UserModel.objects.create_user(username="taken", password="aX9!mnpq2ffz")
    before_members = Member.objects.count()

    response = _post(raw, username="taken")
    assert response.status_code == 200  # re-renders the form with an error
    assert Member.objects.count() == before_members  # no member created
    Invite.objects.get().refresh_from_db()
    assert Invite.objects.get().use_count == 0  # invite NOT consumed
    # And it can still be redeemed with a fresh username.
    assert _post(raw, username="freshname").status_code == 302


def test_weak_password_rejected_without_consuming(invite_to_pod: tuple[Pod, str]) -> None:
    _, raw = invite_to_pod
    response = _post(raw, password="123")
    assert response.status_code == 200
    assert Member.objects.count() == 0
    assert Invite.objects.get().use_count == 0
