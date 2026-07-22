"""The Resend inbound webhook adapter (core/inbound_webhook, wave 4).

The one bridge from Anymail's inbound signal to the shared pipeline. These drive
the REAL Resend event shape: the message is parsed from raw MIME (so
``envelope_recipient`` is None, exactly as Anymail's Resend handler leaves it —
unlike its other ESPs), and the trusted recipient rides in ``esp_event['data']``
the way Resend sends it. Properties: a valid reply posts a comment attributed
from the capability; the recipient is taken from Resend's delivery record, so a
forged To header cannot redirect attribution (T-EMAIL-1); the From-consistency
check still quarantines a spoof; a dead recipient bounces without posting; and a
message-less event is dropped (no poison retry). Signature verification itself is
Anymail's (svix, RESEND_INBOUND_SECRET) and out of scope here.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest
from anymail.inbound import AnymailInboundMessage
from django.utils import timezone

from core import digest, inbound_webhook, reply_addresses
from core.models import (
    Comment,
    DigestIssue,
    DigestSubscription,
    Member,
    Pod,
    PodMembership,
    Post,
    Yard,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def reply_setup() -> tuple[Member, Post, str]:
    """One member, one visible post, one live reply capability for it."""
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Household")
    pod.yards.set([yard])
    member = Member.objects.create(display_name="Gran")
    PodMembership.objects.create(member=member, pod=pod)
    post = Post.objects.create(author=member, pod=pod, body="news")
    post.audience_yards.set([yard])
    now = timezone.now()
    issue = DigestIssue.objects.create(
        member=member,
        yard=yard,
        window_start=now - datetime.timedelta(days=7),
        window_end=now,
    )
    DigestSubscription.objects.create(
        member=member,
        address="gran@example.com",
        enabled=True,
        confirmed_at=now,
        unsubscribe_token_digest="y" * 64,
    )
    local = reply_addresses.mint_for_issue(issue, [post.id])[post.id]
    return member, post, local


def _event(*, to_header: str, recipient: str, from_addr: str, text: str) -> SimpleNamespace:
    """A realistic Anymail inbound event for Resend: the message parsed from raw
    MIME (envelope_recipient is None, as Anymail's Resend handler leaves it), and
    the trusted recipient carried in esp_event['data']['to'] as Resend sends it."""
    raw = (
        f"Message-ID: <wh-1@mail.example>\nFrom: {from_addr}\nTo: {to_header}\n"
        f"Subject: Re: your family digest\nContent-Type: text/plain\n\n"
        f"{text}\n{digest.REPLY_SEPARATOR}\nquoted digest tail below"
    )
    message = AnymailInboundMessage.parse_raw_mime(raw)
    assert message.envelope_recipient is None  # the exact production shape we adapt around
    esp_event = {"type": "email.received", "data": {"to": [recipient], "from": from_addr}}
    return SimpleNamespace(message=message, esp_event=esp_event)


def _fire(event: SimpleNamespace) -> None:
    inbound_webhook.handle_inbound(sender=None, event=event, esp_name="resend")


def test_webhook_posts_a_reply_from_the_delivered_recipient(
    reply_setup: tuple[Member, Post, str],
) -> None:
    member, post, local = reply_setup
    addr = f"{local}@mail.backyard.family"
    _fire(_event(to_header=addr, recipient=addr, from_addr="gran@example.com", text="So proud!"))
    comment = Comment.objects.get()
    assert comment.post_id == post.id
    assert comment.author_id == member.id
    assert comment.via_email is True
    assert comment.body == "So proud!"


def test_webhook_trusts_the_delivered_recipient_not_a_forged_to_header(
    reply_setup: tuple[Member, Post, str],
) -> None:
    """The raw To header is attacker-controlled; Resend's delivery record is not.
    A forged To must not change attribution — the real capability is the address
    Resend delivered to (esp_event data), not the header."""
    member, post, local = reply_setup
    _fire(
        _event(
            to_header="reply-forged@mail.backyard.family",  # attacker-set raw header
            recipient=f"{local}@mail.backyard.family",  # Resend's delivery record
            from_addr="gran@example.com",
            text="Real reply.",
        )
    )
    comment = Comment.objects.get()
    assert comment.post_id == post.id and comment.author_id == member.id
    assert comment.body == "Real reply."


def test_webhook_spoofed_from_still_quarantines(reply_setup: tuple[Member, Post, str]) -> None:
    """The From-consistency check (T-EMAIL-1) flows through the webhook path: a
    valid capability with a mismatched From never posts."""
    _member, _post, local = reply_setup
    addr = f"{local}@mail.backyard.family"
    _fire(_event(to_header=addr, recipient=addr, from_addr="attacker@evil.example", text="spoof"))
    assert Comment.objects.count() == 0


def test_webhook_dead_recipient_bounces_without_posting(
    reply_setup: tuple[Member, Post, str],
) -> None:
    _member, _post, local = reply_setup
    _fire(
        _event(
            to_header=f"{local}@mail.backyard.family",  # valid-looking raw header
            recipient="reply-neverwas@mail.backyard.family",  # dead delivery recipient
            from_addr="gran@example.com",
            text="Should not post.",
        )
    )
    assert Comment.objects.count() == 0


def test_webhook_message_none_event_is_dropped(reply_setup: tuple[Member, Post, str]) -> None:
    """Anymail sets message=None for an email.received event with no email_id;
    the adapter returns without raising, so no poison HTTP-500 retry loop and no
    post (security review LOW-1)."""
    event = SimpleNamespace(message=None, esp_event={"type": "email.received", "data": {}})
    inbound_webhook.handle_inbound(sender=None, event=event, esp_name="resend")
    assert Comment.objects.count() == 0
