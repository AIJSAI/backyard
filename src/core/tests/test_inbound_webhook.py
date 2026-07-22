"""The Resend inbound webhook adapter (core/inbound_webhook, wave 4).

The one bridge from Anymail's inbound signal to the shared pipeline. Properties:
a valid reply posts a comment attributed from the capability; the capability is
taken from the TRUSTED envelope recipient, so a forged To header cannot redirect
attribution (T-EMAIL-1); the From-consistency check still quarantines a spoof;
and a dead envelope capability bounces without posting. The signature
verification itself is Anymail's (svix, RESEND_INBOUND_SECRET) and out of scope
here — this exercises our adapter and its integration with process_inbound.
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


def _message(*, to_header: str, envelope: str, from_addr: str, text: str) -> AnymailInboundMessage:
    raw = (
        f"Message-ID: <wh-1@mail.example>\nFrom: {from_addr}\nTo: {to_header}\n"
        f"Subject: Re: your family digest\nContent-Type: text/plain\n\n"
        f"{text}\n{digest.REPLY_SEPARATOR}\nquoted digest tail below"
    )
    message = AnymailInboundMessage.parse_raw_mime(raw)
    message.envelope_recipient = envelope
    return message


def _fire(message: AnymailInboundMessage) -> None:
    inbound_webhook.handle_inbound(
        sender=None, event=SimpleNamespace(message=message), esp_name="resend"
    )


def test_webhook_posts_a_reply_from_the_envelope_capability(
    reply_setup: tuple[Member, Post, str],
) -> None:
    member, post, local = reply_setup
    addr = f"{local}@mail.backyard.family"
    _fire(_message(to_header=addr, envelope=addr, from_addr="gran@example.com", text="So proud!"))
    comment = Comment.objects.get()
    assert comment.post_id == post.id
    assert comment.author_id == member.id
    assert comment.via_email is True
    assert comment.body == "So proud!"


def test_webhook_trusts_the_envelope_not_a_forged_to_header(
    reply_setup: tuple[Member, Post, str],
) -> None:
    """The To header is attacker-controlled; the ESP envelope is not. A forged To
    must not change attribution — the real capability rides in the envelope."""
    member, post, local = reply_setup
    _fire(
        _message(
            to_header="reply-forged@mail.backyard.family",  # attacker-set header
            envelope=f"{local}@mail.backyard.family",  # trusted envelope
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
    _fire(_message(to_header=addr, envelope=addr, from_addr="attacker@evil.example", text="spoof"))
    assert Comment.objects.count() == 0


def test_webhook_dead_envelope_capability_bounces_without_posting(
    reply_setup: tuple[Member, Post, str],
) -> None:
    _member, _post, local = reply_setup
    _fire(
        _message(
            to_header=f"{local}@mail.backyard.family",  # valid-looking header
            envelope="reply-neverwas@mail.backyard.family",  # dead envelope capability
            from_addr="gran@example.com",
            text="Should not post.",
        )
    )
    assert Comment.objects.count() == 0
