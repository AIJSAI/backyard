"""TM-1 revocation-completeness tests.

The threat model's rule: after revocation, every credential class the member held
returns 404 or bounces on its next use, and the whole act is atomic (a crash
mid-revocation leaves no half-revoked state, TS-DJ-2's kill-test). The classes
that exist this wave are sessions and invites; every future class adds its step
to the registry and its assertion here, in the same commit.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session

from core import revocation
from core.invites import mint_invite
from core.models import Invite, Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db


@pytest.fixture
def household() -> dict[str, object]:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Household")
    pod.yards.set([yard])
    user = User.objects.create_user(username="ex", password="a-fine-password-1234")
    member = Member.objects.create(display_name="Ex", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    other = Member.objects.create(display_name="Sibling")
    PodMembership.objects.create(member=other, pod=pod)
    return {"yard": yard, "pod": pod, "user": user, "member": member, "other": other}


def _make_session(user: User) -> str:
    store = SessionStore()
    store["_auth_user_id"] = str(user.pk)
    store.create()
    assert store.session_key is not None
    return store.session_key


def test_revocation_kills_sessions_and_bumps_generation(household: dict[str, object]) -> None:
    member = household["member"]
    user = household["user"]
    assert isinstance(member, Member)
    assert isinstance(user, User)

    key = _make_session(user)
    other_user = User.objects.create_user(username="bystander", password="a-fine-password-1234")
    bystander_key = _make_session(other_user)
    generation_before = member.token_generation

    revocation.revoke_member_credentials(member)

    assert not Session.objects.filter(session_key=key).exists()
    # A bystander's session survives: revocation is per member, never a purge.
    assert Session.objects.filter(session_key=bystander_key).exists()
    member.refresh_from_db()
    assert member.token_generation == generation_before + 1


def test_revocation_voids_created_and_reachable_invites(household: dict[str, object]) -> None:
    """T-AUTH-G3: the removed ex must not re-enter through the original household
    invite someone else created, so revocation voids invites they created AND live
    invites reaching their pods."""
    member = household["member"]
    other = household["other"]
    pod = household["pod"]
    assert isinstance(member, Member)
    assert isinstance(other, Member)
    assert isinstance(pod, Pod)

    own_invite, _ = mint_invite(pod, member)
    household_invite, _ = mint_invite(pod, other)  # created by someone else
    unrelated_pod = Pod.objects.create(name="Elsewhere")
    unrelated_invite, _ = mint_invite(unrelated_pod, None)

    revocation.revoke_member_credentials(member)

    own_invite.refresh_from_db()
    household_invite.refresh_from_db()
    unrelated_invite.refresh_from_db()
    assert own_invite.revoked_at is not None
    assert household_invite.revoked_at is not None
    # An invite to a pod in a yard the member never belonged to is untouched.
    assert unrelated_invite.revoked_at is None


def test_revocation_voids_same_yard_different_pod_invite(household: dict[str, object]) -> None:
    """The yard-scope arm (M-1): an invite to a DIFFERENT pod in the member's yard
    must also be voided, or the ex re-enters the yard through a sibling pod's invite
    pasted into a group chat (T-AUTH-G3, threat-model line 206 "pods and yards")."""
    member = household["member"]
    yard = household["yard"]
    assert isinstance(member, Member)
    assert isinstance(yard, Yard)

    sibling_pod = Pod.objects.create(name="Cousins")  # same yard, member is NOT in it
    sibling_pod.yards.set([yard])
    sibling_invite, _ = mint_invite(sibling_pod, None)

    revocation.revoke_member_credentials(member)

    sibling_invite.refresh_from_db()
    assert sibling_invite.revoked_at is not None


def test_revocation_is_atomic_no_half_revoked_state(
    household: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The kill-test (TM-1, TS-DJ-2): if a later step raises, the earlier steps
    roll back too. Sessions survive, invites stay live, the generation is
    unchanged: all classes alive, none half-dead."""
    member = household["member"]
    user = household["user"]
    pod = household["pod"]
    assert isinstance(member, Member)
    assert isinstance(user, User)
    assert isinstance(pod, Pod)

    key = _make_session(user)
    invite, _ = mint_invite(pod, member)
    generation_before = member.token_generation

    def boom(_: Member) -> int:
        raise RuntimeError("crash mid-revocation")

    # The crash comes AFTER both real steps run (session delete + invite void), so
    # every assertion below is load-bearing: each proves a genuine write was rolled
    # back, not that a step never executed (TS-DJ-2: "raises after the first
    # credential class, asserts zero were revoked").
    monkeypatch.setattr(
        revocation,
        "_REVOCATION_STEPS",
        (revocation._revoke_sessions, revocation._void_invites, boom),
    )
    with pytest.raises(RuntimeError):
        revocation.revoke_member_credentials(member)

    assert Session.objects.filter(session_key=key).exists()  # session delete rolled back
    invite.refresh_from_db()
    assert invite.revoked_at is None  # invite void rolled back
    member.refresh_from_db()
    assert member.token_generation == generation_before  # generation bump never reached


def test_registry_is_the_only_shape(household: dict[str, object]) -> None:
    """Pin the registry pattern: the handler executes exactly the registered
    steps. A new credential class that forgets to register does not get revoked,
    which is why this test exists and why the completeness assertions above grow
    with every class, in the same commit that ships it."""
    assert revocation._REVOCATION_STEPS == (
        revocation._revoke_sessions,
        revocation._void_invites,
        revocation._cancel_digest_subscription,  # wave 4: the digest joins the registry
        revocation._void_digest_tokens,  # wave 4: per-digest read links, row-level belt
        revocation._void_reply_addresses,  # wave 4: reply-by-email capabilities
    )
    member = household["member"]
    assert isinstance(member, Member)
    revocation.revoke_member_credentials(member)  # runs the full registry cleanly
    voided = Invite.objects.filter(revoked_at__isnull=False).count()
    assert voided == 0  # no invites existed; the act still completes atomically


def test_revocation_cancels_the_digest_subscription(household: dict[str, object]) -> None:
    """The digest joins the registry (wave 4): after revocation the member is due
    no digest ever again, and both emailed capabilities (confirm, unsubscribe)
    resolve like tokens that never existed."""
    import datetime

    from django.utils import timezone

    from core import digesting
    from core.models import DigestSubscription

    member = household["member"]
    assert isinstance(member, Member)
    digesting.subscribe(member, address="ex@example.com", cadence="weekly")
    DigestSubscription.objects.filter(member=member).update(
        confirmed_at=timezone.now(),
        unsubscribe_token_digest=digesting._digest("raw-unsub"),
        confirm_token_digest=digesting._digest("raw-confirm"),
    )

    revocation.revoke_member_credentials(member)

    subscription = DigestSubscription.objects.get(member=member)
    assert subscription.enabled is False
    later = timezone.now() + datetime.timedelta(days=60)
    assert digesting.due_recipients(later) == []  # never due again
    for peek in (digesting.peek_confirmation, digesting.peek_unsubscribe):
        with pytest.raises(digesting.DigestTokenInvalid):
            peek("raw-confirm")
        with pytest.raises(digesting.DigestTokenInvalid):
            peek("raw-unsub")


def test_revocation_voids_reply_addresses(household: dict[str, object]) -> None:
    """Reply capabilities join the registry (wave 4): after the one revocation
    act, a minted address resolves like it never existed — the voided clock,
    independent of grace and generation."""
    import datetime

    from django.utils import timezone

    from core import reply_addresses
    from core.models import DigestIssue, Pod, Post, Yard

    member = household["member"]
    pod = household["pod"]
    yard = household["yard"]
    assert isinstance(member, Member)
    assert isinstance(pod, Pod)
    assert isinstance(yard, Yard)
    post = Post.objects.create(author=member, pod=pod, body="a post")
    now = timezone.now()
    issue = DigestIssue.objects.create(
        member=member, yard=yard, window_start=now - datetime.timedelta(days=7), window_end=now
    )
    minted = reply_addresses.mint_for_issue(issue, [post.id])
    assert reply_addresses.resolve(minted[post.id])  # live before

    revocation.revoke_member_credentials(member)

    with pytest.raises(reply_addresses.ReplyAddressInvalid):
        reply_addresses.resolve(minted[post.id])
