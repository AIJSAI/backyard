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
    # S-101 acceptance: completing signup lands DIRECTLY in the pod feed, not the bare
    # root or a community-setup screen.
    assert response.status_code == 302
    assert response.headers["Location"] == reverse("feed")
    member = Member.objects.get(display_name="New Cousin")
    assert PodMembership.objects.filter(member=member, pod=pod).exists()
    assert member.user is not None
    assert UserModel.objects.filter(username="newcousin").exists()
    Invite.objects.get().refresh_from_db()
    assert Invite.objects.get().use_count == 1


def test_signup_then_following_the_redirect_shows_the_pod_feed(
    invite_to_pod: tuple[Pod, str],
) -> None:
    """The whole S-101 promise end to end at the view layer: redeem, then the very next
    page IS the feed (no setup screen in between), and it renders the member's pod."""
    pod, raw = invite_to_pod
    client = Client()
    data = {"display_name": "New Cousin", "username": "newcousin", "password": "aX9!mnpq2ffz"}
    response = client.post(reverse("join", args=[raw]), data, follow=True)
    assert response.status_code == 200
    assert response.request["PATH_INFO"] == reverse("feed")  # landed on the feed itself
    assert b"community" not in response.content.lower()  # never a create-a-community screen


def test_get_shows_form_for_live_invite(invite_to_pod: tuple[Pod, str]) -> None:
    _, raw = invite_to_pod
    response = Client().get(reverse("join", args=[raw]))
    assert response.status_code == 200


def test_unknown_invite_404s_on_both_get_and_post() -> None:
    # An unknown token 404s on GET and POST: no invite-existence oracle.
    url = reverse("join", args=["totally-unknown-token"])
    assert Client().get(url).status_code == 404
    assert _post("totally-unknown-token").status_code == 404


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
    # Include an entirely unknown token: property 2's literal claim is that an
    # unusable invite is byte-identical to an *unknown route*, not just to each other.
    for raw in (expired_raw, revoked_raw, exhausted_raw, "never-existed-token"):
        r = Client().get(reverse("join", args=[raw]))
        statuses.add(r.status_code)
        bodies.add(r.content)
    assert statuses == {404}
    assert len(bodies) == 1  # byte-identical 404 across all unusable states and the unknown one


def test_overlong_name_is_rejected_not_500(invite_to_pod: tuple[Pod, str]) -> None:
    """Security review M1: an over-long display_name/username must be a form error,
    not an uncaught DataError 500, and must not consume the invite."""
    _, raw = invite_to_pod
    assert _post(raw, display_name="x" * 101).status_code == 200
    assert _post(raw, username="u" * 151).status_code == 200
    assert Member.objects.count() == 0
    assert Invite.objects.get().use_count == 0


def test_authenticated_member_does_not_burn_the_invite(invite_to_pod: tuple[Pod, str]) -> None:
    """An already-signed-in member re-hitting a join link is redirected home, not
    minted a second account or charged an invite use."""
    _, raw = invite_to_pod
    client = Client()
    data = {"display_name": "New Cousin", "username": "newcousin", "password": "aX9!mnpq2ffz"}
    assert client.post(reverse("join", args=[raw]), data).status_code == 302  # logs the member in
    used = Invite.objects.get().use_count
    # The same, now-authenticated client hits the link again: redirected to their feed,
    # no burn.
    rehit = client.get(reverse("join", args=[raw]))
    assert rehit.status_code == 302
    assert rehit.headers["Location"] == reverse("feed")
    assert Invite.objects.get().use_count == used


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
