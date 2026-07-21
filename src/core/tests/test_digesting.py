"""The digest lifecycle (S-501): confirm-first, unsubscribe-with-confirm, cadence.

The properties under test are the wave-4 security blocks: no family content ever
flows to an unconfirmed address (T-EMAIL-6, the typo'd-enrollment killer); the
confirmation email itself is content-free by construction; unsubscribe is a
two-step confirm that flips email off and never touches membership; token failure
shapes are byte-identical 404s; removal drops the member from recipients and
voids both emailed capabilities (TM-1); and the cadence clock hands each member
their own rhythm over a simulated multi-week run.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import digesting, emailing
from core.models import DigestIssue, DigestSubscription, Member, Pod, PodMembership, Yard
from core.removal import remove_member

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_TEST_PW = "a-Strong-passphrase-9"


def _member_with_user(pod: Pod, name: str, role: str = Member.MEMBER) -> Member:
    user = User.objects.create_user(username=name.lower(), password=_TEST_PW)
    member = Member.objects.create(display_name=name, user=user, role=role)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _client_for(member: Member) -> Client:
    assert member.user is not None
    c = Client()
    c.force_login(member.user, backend=_BACKEND)
    return c


@dataclass
class World:
    maternal: Yard
    paternal: Yard
    m_pod: Pod
    nana: Member  # maternal
    admin: Member  # maternal, instance admin
    other: Member  # paternal


@pytest.fixture
def world() -> World:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    m_pod = Pod.objects.create(name="Maternal cousins")
    m_pod.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal cousins")
    p_pod.yards.set([paternal])
    return World(
        maternal=maternal,
        paternal=paternal,
        m_pod=m_pod,
        nana=_member_with_user(m_pod, "Nana"),
        admin=_member_with_user(m_pod, "Admin", role=Member.INSTANCE_ADMIN),
        other=_member_with_user(p_pod, "Other"),
    )


def _confirm_link_token() -> str:
    """The raw confirm token, recovered from the link in the sent email — the only
    place it ever appears."""
    body = mail.outbox[-1].body
    marker = "/digest/confirm/"
    start = body.index(marker) + len(marker)
    return body[start:].split("/", 1)[0]


def _subscribe_and_confirm(member: Member, address: str = "nana@example.com") -> DigestSubscription:
    digesting.subscribe(member, address=address, cadence=DigestSubscription.WEEKLY)
    subscription = digesting.confirm(_confirm_link_token())
    return subscription


# --- confirm-before-first-content (T-EMAIL-6) ---


def test_subscribe_sends_a_content_free_confirmation(world: World) -> None:
    digesting.subscribe(world.nana, address="nana@example.com", cadence="weekly")
    sent = mail.outbox[-1]
    assert sent.to == ["nana@example.com"]
    # Content-free: no member name, no family/yard/pod name reaches the address
    # before it is confirmed as really being Nana's (the typo'd-enrollment path).
    for name in ("Nana", "Admin", "Maternal", "Paternal", "cousins"):
        assert name not in sent.body and name not in sent.subject
    assert "/digest/confirm/" in sent.body
    assert emailing.STANDING_FOOTER in sent.body


def test_unconfirmed_address_is_never_due(world: World) -> None:
    digesting.subscribe(world.nana, address="nana@example.com", cadence="daily")
    later = timezone.now() + datetime.timedelta(days=30)
    assert digesting.due_recipients(later) == []  # no content until acknowledged


def test_confirm_flow_is_get_page_then_post(world: World) -> None:
    digesting.subscribe(world.nana, address="nana@example.com", cadence="weekly")
    token = _confirm_link_token()
    url = reverse("digest_confirm", args=[token])
    client = Client()  # the address holder needs no login (email-link surface)
    assert client.get(url).status_code == 200  # loading never confirms...
    world.nana.refresh_from_db()
    assert DigestSubscription.objects.get(member=world.nana).confirmed_at is None
    assert client.post(url).status_code == 200  # ...POST is the acknowledgment
    assert DigestSubscription.objects.get(member=world.nana).confirmed_at is not None


def test_confirm_token_is_single_use_and_failures_are_uniform(world: World) -> None:
    digesting.subscribe(world.nana, address="nana@example.com", cadence="weekly")
    token = _confirm_link_token()
    client = Client()
    assert client.post(reverse("digest_confirm", args=[token])).status_code == 200
    replay = client.get(reverse("digest_confirm", args=[token]))
    unknown = client.get(reverse("digest_confirm", args=["never-was-a-token"]))
    assert replay.status_code == unknown.status_code == 404
    assert replay.content == unknown.content  # byte-identical failure shapes


def test_address_change_resets_confirmation(world: World) -> None:
    _subscribe_and_confirm(world.nana)
    digesting.subscribe(world.nana, address="new@example.com", cadence="weekly")
    subscription = DigestSubscription.objects.get(member=world.nana)
    assert subscription.confirmed_at is None  # the new address must confirm too
    assert subscription.address == "new@example.com"


# --- unsubscribe: two-step, email-only, never silent (S-501) ---


def test_unsubscribe_is_two_step_and_never_touches_membership(world: World) -> None:
    _subscribe_and_confirm(world.nana)
    raw = "raw-unsubscribe-token"
    # Mint a known unsubscribe token directly (the digest email that would carry
    # it is the send increment's job).
    DigestSubscription.objects.filter(member=world.nana).update(
        unsubscribe_token_digest=digesting._digest(raw)
    )
    memberships_before = world.nana.pod_memberships.count()
    client = Client()
    url = reverse("digest_unsubscribe", args=[raw])
    assert client.get(url).status_code == 200  # the confirm step
    assert DigestSubscription.objects.get(member=world.nana).enabled is True
    assert client.post(url).status_code == 200
    subscription = DigestSubscription.objects.get(member=world.nana)
    assert subscription.enabled is False  # email off...
    assert world.nana.pod_memberships.count() == memberships_before  # ...membership intact


def test_member_can_turn_the_digest_back_on(world: World) -> None:
    _subscribe_and_confirm(world.nana)
    DigestSubscription.objects.filter(member=world.nana).update(enabled=False)
    response = _client_for(world.nana).post(
        reverse("digest_settings"), {"address": "nana@example.com", "cadence": "weekly"}
    )
    assert response.status_code == 200
    assert DigestSubscription.objects.get(member=world.nana).enabled is True


# --- cadence: each member on their own clock ---


def test_cadence_clocks_over_a_simulated_month(world: World) -> None:
    start = timezone.now()
    daily = _subscribe_and_confirm(world.nana, "daily@example.com")
    daily.cadence = DigestSubscription.DAILY
    daily.save(update_fields=["cadence"])
    weekly = _subscribe_and_confirm(world.admin, "weekly@example.com")
    assert weekly.cadence == DigestSubscription.WEEKLY

    # Just under a day: nobody is due.
    assert digesting.due_recipients(start + datetime.timedelta(hours=23)) == []
    # A day and a bit: the daily member only.
    due = digesting.due_recipients(start + datetime.timedelta(days=1, hours=1))
    assert {d.subscription.member.display_name for d in due} == {"Nana"}
    # Simulate that send: an issue lands; the daily clock re-anchors to it.
    sent_at = start + datetime.timedelta(days=1, hours=1)
    DigestIssue.objects.create(
        member=world.nana, yard=world.maternal, window_start=start, window_end=sent_at
    )
    assert digesting.due_recipients(sent_at + datetime.timedelta(hours=12)) == []
    # Day 8: daily member due again (since their last issue), weekly member due
    # for the first time (since confirmation), each on their own clock.
    due = digesting.due_recipients(start + datetime.timedelta(days=8))
    assert {d.subscription.member.display_name for d in due} == {"Nana", "Admin"}
    window = next(d for d in due if d.subscription.member_id == world.nana.id)
    assert window.window_start == sent_at  # the window resumes where the last issue ended


def test_removal_drops_the_member_from_recipients(world: World) -> None:
    _subscribe_and_confirm(world.nana)
    remove_member(world.nana)
    later = timezone.now() + datetime.timedelta(days=30)
    assert digesting.due_recipients(later) == []  # TM-1: removal cancels the digest


# --- the admin delivery panel, scoped like the roster ---


def test_delivery_panel_is_admin_only_and_yard_scoped(world: World) -> None:
    _subscribe_and_confirm(world.nana)
    digesting.subscribe(world.other, address="other@example.com", cadence="weekly")
    body = _client_for(world.admin).get(reverse("member_digests")).content.decode()
    assert "nana@example.com" in body  # own-yard member's state
    assert "other@example.com" not in body  # cross-yard subscription absent (S-202)
    assert _client_for(world.nana).get(reverse("member_digests")).status_code == 403


def test_settings_page_rejects_a_non_address(world: World) -> None:
    response = _client_for(world.nana).post(
        reverse("digest_settings"), {"address": "not-an-email", "cadence": "weekly"}
    )
    assert response.status_code == 200
    assert not DigestSubscription.objects.filter(member=world.nana).exists()
    assert len(mail.outbox) == 0  # nothing sent for a rejected address
