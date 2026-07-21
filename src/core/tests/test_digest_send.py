"""Send orchestration (S-501): the full pipeline on the locmem transport.

Properties under test: the bridge member yields exactly TWO messages, each
grepped clean of the other yard (the fused-email test at the transport level);
a member revoked between due-resolution and send yields ZERO (queued-send
cancellation, TM-1); a post deleted after the due list was computed is absent
from the sent payload (TS-DJ-11: identifiers only, content re-resolved at send
time); a hard crash mid-batch leaves earlier recipients fully recorded and the
crashed one fully absent (the TS-DJ-2 kill shape); a transport failure records
on the delivery panel and never flips subscription state (T-EMAIL-6); and
overlapping runs are idempotent per window.
"""

from __future__ import annotations

import datetime
import smtplib
from dataclasses import dataclass
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.utils import timezone

from core import digesting, emailing, revocation
from core.digest_send import send_due_digests
from core.models import (
    DigestDelivery,
    DigestIssue,
    DigestSubscription,
    Member,
    Pod,
    PodMembership,
    Post,
    Yard,
)

pytestmark = pytest.mark.django_db
User = get_user_model()
_TEST_PW = "a-Strong-passphrase-9"


def _member_in(pod: Pod, name: str) -> Member:
    user = User.objects.create_user(username=name.lower(), password=_TEST_PW)
    member = Member.objects.create(display_name=name, user=user)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _confirmed(member: Member, address: str) -> DigestSubscription:
    digesting.subscribe(member, address=address, cadence="weekly")
    subscription = DigestSubscription.objects.get(member=member)
    subscription.confirmed_at = timezone.now() - datetime.timedelta(days=8)
    subscription.save(update_fields=["confirmed_at"])
    mail.outbox.clear()  # drop the confirmation email; tests inspect digests only
    return subscription


@dataclass
class World:
    maternal: Yard
    paternal: Yard
    bridge_pod: Pod
    m_pod: Pod
    p_pod: Pod
    bridge: Member
    maternal_cousin: Member
    paternal_cousin: Member


@pytest.fixture
def world() -> World:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    bridge_pod = Pod.objects.create(name="Bridge household")
    bridge_pod.yards.set([maternal, paternal])
    m_pod = Pod.objects.create(name="Maternal cousins")
    m_pod.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal cousins")
    p_pod.yards.set([paternal])
    return World(
        maternal=maternal,
        paternal=paternal,
        bridge_pod=bridge_pod,
        m_pod=m_pod,
        p_pod=p_pod,
        bridge=_member_in(bridge_pod, "Bridge parent"),
        maternal_cousin=_member_in(m_pod, "Maternal cousin"),
        paternal_cousin=_member_in(p_pod, "Paternal cousin"),
    )


def test_bridge_member_gets_exactly_two_clean_emails(world: World) -> None:
    """The transport-level no-fusion proof: two separate messages, each free of
    the other yard's bodies and names."""
    _confirmed(world.bridge, "bridge@example.com")
    post_m = Post.objects.create(author=world.maternal_cousin, pod=world.m_pod, body="MAT-BODY")
    post_m.audience_yards.set([world.maternal])
    post_p = Post.objects.create(author=world.paternal_cousin, pod=world.p_pod, body="PAT-BODY")
    post_p.audience_yards.set([world.paternal])

    report = send_due_digests(timezone.now())
    assert report.sent == 2 and report.failed == 0
    assert len(mail.outbox) == 2
    by_subject = {message.subject: message for message in mail.outbox}
    maternal_message = by_subject["Maternal: your family digest"]
    paternal_message = by_subject["Paternal: your family digest"]
    assert "MAT-BODY" in maternal_message.body and "PAT-BODY" not in maternal_message.body
    assert "Paternal cousin" not in maternal_message.body
    assert "PAT-BODY" in paternal_message.body and "MAT-BODY" not in paternal_message.body
    assert "Maternal cousin" not in paternal_message.body
    assert maternal_message.to == ["bridge@example.com"]

    issues = DigestIssue.objects.filter(member=world.bridge)
    assert issues.count() == 2  # one per yard, never fused
    assert (
        DigestDelivery.objects.filter(
            issue__in=issues, status=DigestDelivery.HANDED_TO_RELAY
        ).count()
        == 2
    )


def test_revoked_between_due_and_send_yields_zero(world: World) -> None:
    """Queued-send cancellation (TM-1): the due list is stale the moment
    revocation runs, and the in-transaction re-check wins."""
    _confirmed(world.maternal_cousin, "cousin@example.com")
    due = digesting.due_recipients(timezone.now())
    assert len(due) == 1  # the member IS due...
    revocation.revoke_member_credentials(world.maternal_cousin)

    report = send_due_digests(timezone.now())
    assert report.sent == 0
    assert len(mail.outbox) == 0  # ...and still gets nothing
    assert not DigestIssue.objects.filter(member=world.maternal_cousin).exists()


def test_deleted_after_enqueue_is_absent_from_the_sent_payload(world: World) -> None:
    """TS-DJ-11's named acceptance test: the send path re-resolves through the
    builder at send time rather than trusting anything computed earlier."""
    _confirmed(world.maternal_cousin, "cousin@example.com")
    post = Post.objects.create(author=world.maternal_cousin, pod=world.m_pod, body="DOOMED-BODY")
    post.audience_yards.set([world.maternal])
    assert len(digesting.due_recipients(timezone.now())) == 1  # "enqueued" with the post live

    post.deleted_at = timezone.now()
    post.save(update_fields=["deleted_at"])

    send_due_digests(timezone.now())
    assert len(mail.outbox) == 1
    assert "DOOMED-BODY" not in mail.outbox[0].body


def test_hard_crash_is_isolated_and_leaves_no_half_state(world: World, monkeypatch: Any) -> None:
    """The TS-DJ-2 kill shape plus per-recipient isolation (#38 review): the
    crashed recipient is fully absent — no issue, no delivery, no email — while
    recipients before AND after it still send, and the report says so loudly."""
    _confirmed(world.maternal_cousin, "first@example.com")
    _confirmed(world.bridge, "second@example.com")
    _confirmed(world.paternal_cousin, "third@example.com")

    real_send = emailing.send_family_email

    def crashing_send(**kwargs: Any) -> None:
        if kwargs["to"] == "second@example.com":
            raise RuntimeError("power loss")  # not a transport error
        real_send(**kwargs)

    monkeypatch.setattr("core.digest_send.emailing.send_family_email", crashing_send)
    report = send_due_digests(timezone.now())

    assert report.crashed == 2  # the bridge member's two yard-sends both crashed
    assert report.sent == 2  # the recipients around the poisoned one still sent
    assert {message.to[0] for message in mail.outbox} == {
        "first@example.com",
        "third@example.com",
    }
    assert not DigestIssue.objects.filter(member=world.bridge).exists()  # fully absent
    assert DigestDelivery.objects.count() == 2  # only the real sends recorded


def test_transport_failure_records_and_never_flips_subscription(
    world: World, monkeypatch: Any
) -> None:
    """T-EMAIL-6: a bounce-shaped failure surfaces on the panel; the member is
    never silently severed, and the window is not re-hammered."""
    _confirmed(world.maternal_cousin, "cousin@example.com")

    def refusing_send(**kwargs: Any) -> None:
        raise smtplib.SMTPRecipientsRefused({"cousin@example.com": (550, b"mailbox unavailable")})

    monkeypatch.setattr("core.digest_send.emailing.send_family_email", refusing_send)
    report = send_due_digests(timezone.now())
    assert report.failed == 1 and report.sent == 0

    delivery = DigestDelivery.objects.get()
    assert delivery.status == DigestDelivery.REJECTED
    assert "550" in delivery.detail
    subscription = DigestSubscription.objects.get(member=world.maternal_cousin)
    assert subscription.enabled is True  # never auto-suppressed
    # The failed window is recorded, so a re-run does not hammer the relay.
    monkeypatch.undo()
    rerun = send_due_digests(timezone.now())
    assert rerun.sent == 0 and len(mail.outbox) == 0


def test_overlapping_runs_are_idempotent(world: World) -> None:
    _confirmed(world.maternal_cousin, "cousin@example.com")
    first = send_due_digests(timezone.now())
    second = send_due_digests(timezone.now())
    assert first.sent == 1
    assert second.sent == 0  # the cadence clock anchors on the new issue
    assert len(mail.outbox) == 1


def test_unsubscribe_link_in_the_sent_digest_works_and_rotates(world: World) -> None:
    """The emailed unsubscribe capability is the rotated one (the enrollment
    digest is never mailed), and a second issue's link supersedes it."""
    from django.test import Client

    _confirmed(world.maternal_cousin, "cousin@example.com")
    send_due_digests(timezone.now())
    body = mail.outbox[0].body
    marker = "/digest/unsubscribe/"
    raw = body[body.index(marker) + len(marker) :].split("/", 1)[0]
    response = Client().get(f"/digest/unsubscribe/{raw}/")
    assert response.status_code == 200  # the emailed link resolves

    # A later digest rotates the capability; the old link dies (T-EMAIL-2 shape).
    later = timezone.now() + datetime.timedelta(days=8)
    send_due_digests(later)
    assert Client().get(f"/digest/unsubscribe/{raw}/").status_code == 404


def test_multi_yard_emails_share_one_working_unsubscribe_link(world: World) -> None:
    """Live-repro finding: per-email rotation killed the first email's link the
    moment the second sent. One capability per subscription per run — both of
    the bridge member's emails carry it, and it works."""
    from django.test import Client

    _confirmed(world.bridge, "bridge@example.com")
    send_due_digests(timezone.now())
    assert len(mail.outbox) == 2
    marker = "/digest/unsubscribe/"
    raws = set()
    for message in mail.outbox:
        body = message.body
        raws.add(body[body.index(marker) + len(marker) :].split("/", 1)[0])
    assert len(raws) == 1  # the same capability in both emails...
    assert Client().get(f"/digest/unsubscribe/{raws.pop()}/").status_code == 200  # ...and it works


def test_transport_failure_never_kills_the_previous_emailed_unsubscribe_link(
    world: World, monkeypatch: Any
) -> None:
    """#38 review HIGH, the reviewer's exact probe: week-1 digest delivered;
    week-2 send greylisted. The rotation rolls back with the refused send, so
    week-1's emailed consent-revocation link still works."""
    from django.test import Client

    _confirmed(world.maternal_cousin, "cousin@example.com")
    send_due_digests(timezone.now())
    body = mail.outbox[0].body
    marker = "/digest/unsubscribe/"
    week1_raw = body[body.index(marker) + len(marker) :].split("/", 1)[0]
    assert Client().get(f"/digest/unsubscribe/{week1_raw}/").status_code == 200

    def greylisted(**kwargs: Any) -> None:
        raise smtplib.SMTPResponseException(450, b"try again later")

    monkeypatch.setattr("core.digest_send.emailing.send_family_email", greylisted)
    later = timezone.now() + datetime.timedelta(days=8)
    report = send_due_digests(later)
    assert report.failed == 1
    assert Client().get(f"/digest/unsubscribe/{week1_raw}/").status_code == 200  # still alive
    # And the orphan digest token from the refused send rolled back too.
    from core.models import DigestToken

    refused_issue = DigestIssue.objects.filter(member=world.maternal_cousin).order_by(
        "-created_at"
    )[0]
    assert not DigestToken.objects.filter(issue=refused_issue).exists()


def test_partial_crash_never_loses_a_yards_window(world: World, monkeypatch: Any) -> None:
    """#38 review MEDIUM, the reviewer's exact probe: the bridge member's
    maternal send commits, the paternal send crashes. Content posted in that
    window must still reach the paternal digest on the next run — the window
    anchors per (member, yard), never on a sibling yard's success."""
    _confirmed(world.bridge, "bridge@example.com")
    lost_post = Post.objects.create(
        author=world.paternal_cousin, pod=world.p_pod, body="ALMOST-LOST-BODY"
    )
    lost_post.audience_yards.set([world.paternal])

    real_send = emailing.send_family_email

    def crash_paternal(**kwargs: Any) -> None:
        if "Paternal" in kwargs["subject"]:
            raise RuntimeError("power loss")
        real_send(**kwargs)

    monkeypatch.setattr("core.digest_send.emailing.send_family_email", crash_paternal)
    first_run = send_due_digests(timezone.now())
    assert first_run.sent == 1 and first_run.crashed == 1

    monkeypatch.setattr("core.digest_send.emailing.send_family_email", real_send)
    second_run = send_due_digests(timezone.now() + datetime.timedelta(days=8))
    assert second_run.crashed == 0
    paternal_bodies = [m.body for m in mail.outbox if "Paternal" in m.subject]
    assert paternal_bodies and "ALMOST-LOST-BODY" in paternal_bodies[-1]


def test_sent_digest_carries_working_reply_addresses(world: World) -> None:
    """The emailed reply block is real end-to-end: the address in the sent
    digest resolves to the right (member, post), and a reply through the full
    inbound pipeline posts a badged comment."""
    from core import digest, inbound

    _confirmed(world.maternal_cousin, "cousin@example.com")
    post = Post.objects.create(author=world.maternal_cousin, pod=world.m_pod, body="reply to me")
    post.audience_yards.set([world.maternal])
    send_due_digests(timezone.now())
    body = mail.outbox[0].body
    assert digest.REPLY_SEPARATOR in body  # the separator ships in every digest
    line = next(line for line in body.splitlines() if "Reply to this post by email:" in line)
    address = line.split(":", 1)[1].strip()
    raw = (
        f"Message-ID: <e2e@x>\nFrom: cousin@example.com\nTo: {address}\n"
        f"Subject: Re: digest\nContent-Type: text/plain\n\n"
        f"Emailed reply!\n{digest.REPLY_SEPARATOR}\nquoted digest below"
    ).encode()
    assert inbound.process_inbound(raw).outcome == "posted"
    from core.models import Comment

    comment = Comment.objects.get(via_email=True)
    assert comment.post_id == post.id and comment.author_id == world.maternal_cousin.id


def test_transport_failure_rolls_back_supersession_of_old_reply_addresses(
    world: World, monkeypatch: Any
) -> None:
    """A refused send must not supersede last week's reply capabilities: the
    savepoint covers the reply-address minting too."""
    from core.models import ReplyAddress

    _confirmed(world.maternal_cousin, "cousin@example.com")
    post = Post.objects.create(author=world.maternal_cousin, pod=world.m_pod, body="week one")
    post.audience_yards.set([world.maternal])
    send_due_digests(timezone.now())
    week1 = ReplyAddress.objects.get()
    assert week1.superseded_at is None

    def greylisted(**kwargs: Any) -> None:
        raise smtplib.SMTPResponseException(450, b"try again later")

    monkeypatch.setattr("core.digest_send.emailing.send_family_email", greylisted)
    send_due_digests(timezone.now() + datetime.timedelta(days=8))
    week1.refresh_from_db()
    assert week1.superseded_at is None  # the failed send never started the grace clock
    assert ReplyAddress.objects.count() == 1  # and minted nothing durable


def test_same_run_yards_do_not_supersede_each_other(world: World) -> None:
    """#39 review MED-2: the bridge member's two same-run issues each keep
    their own unsuperseded reply addresses; supersession is per yard stream."""
    from core.models import ReplyAddress

    _confirmed(world.bridge, "bridge@example.com")
    post = Post.objects.create(author=world.bridge, pod=world.bridge_pod, body="both sides")
    send_due_digests(timezone.now())
    # The MED-2 regression: after ONE run, the bridge member's two per-yard
    # mints have NOT stamped each other — zero superseded addresses.
    assert ReplyAddress.objects.filter(post=post).count() == 2
    assert ReplyAddress.objects.filter(superseded_at__isnull=False).count() == 0
    # The NEXT run supersedes each yard's own predecessor (starting its grace
    # window, T-EMAIL-2) — per-yard streams age independently, and both aged
    # addresses stay within grace rather than dying.
    send_due_digests(timezone.now() + datetime.timedelta(days=8))
    for yard in (world.maternal, world.paternal):
        aged = ReplyAddress.objects.get(issue__yard=yard, post=post)
        assert aged.superseded_at is not None
        assert aged.superseded_at > timezone.now() - datetime.timedelta(hours=1)
