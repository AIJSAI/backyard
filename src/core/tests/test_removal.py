"""S-702 removal tests: revoke, detach, deactivate, in that order.

The load-bearing one is the ordering regression the revocation review (H-1)
asked to land with S-702: removal must void the reachable invites, which only
works because it revokes while the member's memberships still exist. If a future
refactor reorders remove_member to tear down memberships first, that void goes
silent and this test fails.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session

from core.invites import mint_invite
from core.models import Member, Pod, PodMembership, Yard
from core.removal import remove_member

pytestmark = pytest.mark.django_db


@pytest.fixture
def yard_with_ex() -> dict[str, object]:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    ex_pod = Pod.objects.create(name="Ex household")
    ex_pod.yards.set([yard])
    sibling_pod = Pod.objects.create(name="Cousins")  # same yard, ex is NOT in it
    sibling_pod.yards.set([yard])

    user = User.objects.create_user(username="ex", password="a-fine-passphrase-1234")
    ex = Member.objects.create(display_name="Ex", user=user)
    PodMembership.objects.create(member=ex, pod=ex_pod)
    return {"yard": yard, "ex_pod": ex_pod, "sibling_pod": sibling_pod, "user": user, "ex": ex}


def _session_for(user: User) -> str:
    store = SessionStore()
    store["_auth_user_id"] = str(user.pk)
    store.create()
    assert store.session_key is not None
    return store.session_key


def test_removal_revokes_detaches_and_deactivates(yard_with_ex: dict[str, object]) -> None:
    ex = yard_with_ex["ex"]
    user = yard_with_ex["user"]
    ex_pod = yard_with_ex["ex_pod"]
    assert isinstance(ex, Member)
    assert isinstance(user, User)
    assert isinstance(ex_pod, Pod)

    key = _session_for(user)
    own_invite, _ = mint_invite(ex_pod, ex)
    generation_before = ex.token_generation

    remove_member(ex)

    assert not Session.objects.filter(session_key=key).exists()  # sessions gone
    own_invite.refresh_from_db()
    assert own_invite.revoked_at is not None  # invites voided
    ex.refresh_from_db()
    assert ex.token_generation == generation_before + 1  # generation bumped
    assert not PodMembership.objects.filter(member=ex).exists()  # detached
    user.refresh_from_db()
    assert user.is_active is False  # password login dead
    # The Member row is kept (deactivated), so authored content stays attributable.
    assert Member.objects.filter(pk=ex.pk).exists()


def test_removal_voids_reachable_invite_because_it_revokes_before_teardown(
    yard_with_ex: dict[str, object],
) -> None:
    """The H-1 ordering regression: a same-yard sibling-pod invite the ex was never
    in must be voided by removal. This only happens because remove_member revokes
    while the ex's memberships still exist; reorder it and this fails."""
    ex = yard_with_ex["ex"]
    sibling_pod = yard_with_ex["sibling_pod"]
    assert isinstance(ex, Member)
    assert isinstance(sibling_pod, Pod)

    sibling_invite, _ = mint_invite(sibling_pod, None)

    remove_member(ex)

    sibling_invite.refresh_from_db()
    assert sibling_invite.revoked_at is not None


def test_removal_of_accountless_member_is_clean(yard_with_ex: dict[str, object]) -> None:
    """A token-only or supervised member (no User) removes without error."""
    yard = yard_with_ex["yard"]
    ex_pod = yard_with_ex["ex_pod"]
    assert isinstance(ex_pod, Pod)

    accountless = Member.objects.create(display_name="Elder")
    PodMembership.objects.create(member=accountless, pod=ex_pod)

    remove_member(accountless)

    assert not PodMembership.objects.filter(member=accountless).exists()
    assert Member.objects.filter(pk=accountless.pk).exists()
