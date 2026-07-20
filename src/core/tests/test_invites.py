"""Invite service tests: the TS-DJ-5 properties the service layer carries.

Property 1 (atomic consume under lock) and property 2 (indistinguishable
failures) live here. Property 3 (endpoint rate limit) and property 4
(EmailAddress.verified rules) bind when the allauth signup surface lands, and
their absence here is recorded in core/invites.py's docstring, not forgotten.
"""

from __future__ import annotations

import threading

import pytest
from django.db import connection, transaction
from django.utils import timezone

from core.invites import InviteInvalid, mint_invite, redeem_invite
from core.models import Invite, InviteRedemption, Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db


@pytest.fixture
def pod() -> Pod:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Household")
    pod.yards.set([yard])
    return pod


def test_mint_stores_only_the_digest(pod: Pod) -> None:
    invite, raw = mint_invite(pod, None)
    assert len(raw) >= 43  # token_urlsafe(32): 256 bits before encoding
    assert raw not in invite.token_digest
    assert len(invite.token_digest) == 64  # sha256 hex
    assert invite.expires_at > timezone.now()


def test_redeem_mints_member_in_pod_and_records_join(pod: Pod) -> None:
    invite, raw = mint_invite(pod, None)
    member = redeem_invite(raw, display_name="New cousin", user_id=None)
    assert PodMembership.objects.filter(member=member, pod=pod).exists()
    redemption = InviteRedemption.objects.get(invite=invite)
    assert redemption.member == member
    invite.refresh_from_db()
    assert invite.use_count == 1


def test_all_failure_modes_are_indistinguishable(pod: Pod) -> None:
    """Unknown, expired, revoked, and exhausted invites raise the same exception
    with the same message: no invite-existence oracle (TS-DJ-5 property 2)."""
    _, expired_raw = mint_invite(pod, None, ttl_days=0)
    revoked, revoked_raw = mint_invite(pod, None)
    revoked.revoked_at = timezone.now()
    revoked.save(update_fields=["revoked_at"])
    exhausted, exhausted_raw = mint_invite(pod, None, max_uses=1)
    redeem_invite(exhausted_raw, display_name="First", user_id=None)

    messages = set()
    for raw in ("no-such-token", expired_raw, revoked_raw, exhausted_raw):
        with pytest.raises(InviteInvalid) as exc:
            redeem_invite(raw, display_name="X", user_id=None)
        messages.add(str(exc.value))
    assert messages == {InviteInvalid.MESSAGE}


def test_exhausted_invite_stops_at_cap(pod: Pod) -> None:
    _, raw = mint_invite(pod, None, max_uses=2)
    redeem_invite(raw, display_name="One", user_id=None)
    redeem_invite(raw, display_name="Two", user_id=None)
    with pytest.raises(InviteInvalid):
        redeem_invite(raw, display_name="Three", user_id=None)
    assert Member.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_redeem_deterministically_blocks_on_the_row_lock() -> None:
    """TS-DJ-5 property 1, proved not raced: a holder thread takes the invite's
    row lock and keeps it; redeem_invite provably cannot finish while the lock is
    held, and once the holder commits the invite as exhausted, the unblocked
    redeemer re-reads that committed state and raises InviteInvalid. No member is
    minted. This is deterministic (barriers, not sleeps), so it distinguishes
    "the lock serialized them" from "they happened not to overlap"."""
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Household")
    pod.yards.set([yard])
    invite, raw = mint_invite(pod, None, max_uses=1)

    holder_locked = threading.Event()
    holder_release = threading.Event()
    redeem_done = threading.Event()
    results: list[str] = []

    def holder() -> None:
        with transaction.atomic():
            Invite.objects.select_for_update().get(pk=invite.pk)
            holder_locked.set()
            holder_release.wait(timeout=5)
            # Commit the invite as exhausted, so the unblocked redeemer sees it.
            Invite.objects.filter(pk=invite.pk).update(use_count=1)
        connection.close()

    def redeemer() -> None:
        try:
            redeem_invite(raw, display_name="Racer", user_id=None)
            results.append("ok")
        except InviteInvalid:
            results.append("invalid")
        finally:
            connection.close()
            redeem_done.set()

    holder_thread = threading.Thread(target=holder)
    holder_thread.start()
    assert holder_locked.wait(timeout=5)

    redeemer_thread = threading.Thread(target=redeemer)
    redeemer_thread.start()
    # The redeemer must block on the lock: it does not finish while the holder holds it.
    assert not redeem_done.wait(timeout=0.5)

    holder_release.set()  # holder commits use_count=1 and releases the lock
    redeemer_thread.join(timeout=5)
    holder_thread.join(timeout=5)

    assert results == ["invalid"]  # the unblocked redeemer saw the exhausted invite
    assert Member.objects.count() == 0
    invite.refresh_from_db()
    assert invite.use_count == 1


@pytest.mark.django_db(transaction=True)
def test_two_racing_redeems_mint_exactly_one() -> None:
    """Complementary stochastic check: two real threads redeem the same one-use
    invite. Whatever the interleaving, exactly one member is minted (the
    deterministic test above proves WHY: the row lock)."""
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Household")
    pod.yards.set([yard])
    _, raw = mint_invite(pod, None, max_uses=1)

    results: list[str] = []
    lock = threading.Lock()

    def attempt(name: str) -> None:
        try:
            redeem_invite(raw, display_name=name, user_id=None)
            outcome = "ok"
        except InviteInvalid:
            outcome = "invalid"
        finally:
            connection.close()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=attempt, args=(f"racer-{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count("ok") == 1
    assert Member.objects.count() == 1
    assert Invite.objects.get().use_count == 1
