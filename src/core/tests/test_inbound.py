"""Reply-by-email (S-502): the inbound pipeline against a real-client corpus.

Properties under test: attribution comes from the capability alone, and a
spoofed From with a valid capability quarantines without posting (T-EMAIL-1);
the quoted-digest strip keeps only the sender's words across Gmail, Apple
Mail, Outlook, and bare-client quoting — a two-yard member's full-quote reply
never republishes the other yard's section (T-EMAIL-G2); a missing separator
quarantines, never posts the tail; bounces for no-such-thread and
not-your-thread are byte-identical from one constructor; the Message-ID ledger
makes an IMAP re-poll a no-op; MIME bombs and oversized messages die before
parsing; the write path's own audience re-check is the second lock; and the
via-email badge marks every emailed comment.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from django.utils import timezone

from core import digest, inbound, reply_addresses
from core.mail_sources import FixtureMailSource, poll
from core.models import (
    Comment,
    DigestIssue,
    DigestSubscription,
    InboundQuarantine,
    Member,
    Pod,
    PodMembership,
    Post,
    ReplyAddress,
    Yard,
)

pytestmark = pytest.mark.django_db

_FIXTURES = Path(__file__).parent / "fixtures" / "inbound_mail"


def _member_in(pod: Pod, name: str) -> Member:
    member = Member.objects.create(display_name=name)
    PodMembership.objects.create(member=member, pod=pod)
    return member


@dataclass
class World:
    maternal: Yard
    paternal: Yard
    bridge_pod: Pod
    m_pod: Pod
    bridge: Member
    maternal_cousin: Member
    m_post: Post
    p_post: Post
    issue: DigestIssue
    local_part: str  # the bridge member's live capability for m_post


@pytest.fixture
def world() -> World:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    bridge_pod = Pod.objects.create(name="Bridge household")
    bridge_pod.yards.set([maternal, paternal])
    m_pod = Pod.objects.create(name="Maternal cousins")
    m_pod.yards.set([maternal])
    bridge = _member_in(bridge_pod, "Bridge parent")
    maternal_cousin = _member_in(m_pod, "Maternal cousin")
    m_post = Post.objects.create(author=maternal_cousin, pod=m_pod, body="maternal news")
    m_post.audience_yards.set([maternal])
    p_post = Post.objects.create(author=bridge, pod=bridge_pod, body="paternal-only send")
    p_post.audience_yards.set([paternal])
    now = timezone.now()
    issue = DigestIssue.objects.create(
        member=bridge,
        yard=maternal,
        window_start=now - datetime.timedelta(days=7),
        window_end=now,
    )
    DigestSubscription.objects.create(
        member=bridge,
        address="bridge@example.com",
        enabled=True,
        confirmed_at=now,
        unsubscribe_token_digest="x" * 64,
    )
    minted = reply_addresses.mint_for_issue(issue, [m_post.id])
    return World(
        maternal=maternal,
        paternal=paternal,
        bridge_pod=bridge_pod,
        m_pod=m_pod,
        bridge=bridge,
        maternal_cousin=maternal_cousin,
        m_post=m_post,
        p_post=p_post,
        issue=issue,
        local_part=minted[m_post.id],
    )


def _email(
    world: World,
    fixture: str = "gmail_reply.eml",
    *,
    reply_text: str = "So glad to see this!",
    from_addr: str = "bridge@example.com",
    local_part: str | None = None,
    message_id: str = "unique-1@mail.example",
    quoted_body: str = "the quoted maternal digest text",
) -> bytes:
    template = (_FIXTURES / fixture).read_text()
    return template.format(
        message_id=message_id,
        from_addr=from_addr,
        to_addr=f"{local_part or world.local_part}@localhost",
        subject="Maternal: your family digest",
        reply_text=reply_text,
        separator=digest.REPLY_SEPARATOR,
        quoted_body=quoted_body,
    ).encode()


# --- the corpus: only the sender's words survive, on every client shape ---


@pytest.mark.parametrize(
    "fixture",
    ["gmail_reply.eml", "apple_mail_reply.eml", "outlook_reply.eml", "plain_elder_reply.eml"],
)
def test_corpus_reply_posts_only_the_words_above_the_separator(world: World, fixture: str) -> None:
    result = inbound.process_inbound(_email(world, fixture, message_id=f"{fixture}@mail.example"))
    assert result.outcome == "posted"
    comment = Comment.objects.get()
    assert comment.author_id == world.bridge.id  # attributed from the capability
    assert comment.post_id == world.m_post.id
    assert comment.via_email is True
    assert "So glad to see this!" in comment.body
    assert "quoted maternal digest" not in comment.body  # the tail never posts
    assert digest.REPLY_SEPARATOR not in comment.body


def test_two_yard_members_full_quote_never_republishes_the_other_yard(world: World) -> None:
    """T-EMAIL-G2's named first-week failure: the bridge member replies to a
    MATERNAL digest and their client quotes... a mailbox that also holds the
    paternal digest. Whatever sits below the separator dies, so yard-B text
    never lands in a yard-A thread."""
    raw = _email(
        world,
        "plain_elder_reply.eml",
        reply_text="Lovely week everyone.",
        quoted_body="PATERNAL-SECTION paternal-only send from the other digest",
    )
    result = inbound.process_inbound(raw)
    assert result.outcome == "posted"
    comment = Comment.objects.get()
    assert "PATERNAL-SECTION" not in comment.body
    assert comment.body == "Lovely week everyone."


def test_missing_separator_quarantines_and_never_posts(world: World) -> None:
    raw = (
        f"Message-ID: <no-sep@x>\nFrom: bridge@example.com\n"
        f"To: {world.local_part}@localhost\nSubject: Re: hi\n"
        f"Content-Type: text/plain\n\nwords with no separator anywhere"
    ).encode()
    result = inbound.process_inbound(raw)
    assert result.outcome == "quarantined"
    assert Comment.objects.count() == 0
    row = InboundQuarantine.objects.get()
    assert row.reason == InboundQuarantine.NO_SEPARATOR


# --- From: is a consistency check, never attribution (T-EMAIL-1) ---


def test_spoofed_from_with_a_valid_capability_quarantines(world: World) -> None:
    result = inbound.process_inbound(
        _email(world, from_addr="attacker@evil.example", message_id="spoof@x")
    )
    assert result.outcome == "quarantined"
    assert Comment.objects.count() == 0  # never attributed, never posted
    row = InboundQuarantine.objects.get()
    assert row.reason == InboundQuarantine.FROM_MISMATCH
    assert row.member_id == world.bridge.id  # surfaced for the admin


# --- bounces: one constructor, byte-identical shapes ---


def test_no_such_thread_and_not_your_thread_bounce_identically(world: World) -> None:
    unknown = inbound.process_inbound(_email(world, local_part="reply-neverwas", message_id="u@x"))
    # A valid capability whose post has left the sender's CURRENT audience: the
    # write path's re-check refuses it (the second lock). The post moves to a
    # yard and pod the bridge member is in NEITHER of.
    elsewhere_yard = Yard.objects.create(name="Elsewhere", slug="elsewhere")
    elsewhere_pod = Pod.objects.create(name="Elsewhere pod")
    elsewhere_pod.yards.set([elsewhere_yard])
    world.m_post.audience_yards.set([elsewhere_yard])
    world.m_post.pod = elsewhere_pod
    world.m_post.save(update_fields=["pod"])
    not_yours = inbound.process_inbound(_email(world, message_id="n@x"))
    assert unknown.outcome == not_yours.outcome == "bounced"
    assert unknown.bounce_text is not None
    assert unknown.bounce_text.encode() == (not_yours.bounce_text or "").encode()
    assert Comment.objects.count() == 0


# --- the three kill clocks, each alone (S-502 hardening) ---


def test_superseded_beyond_grace_dies_but_grace_window_lives(world: World) -> None:
    ReplyAddress.objects.filter(member=world.bridge).update(
        superseded_at=timezone.now() - datetime.timedelta(days=5)
    )
    assert inbound.process_inbound(_email(world, message_id="g1@x")).outcome == "posted"
    ReplyAddress.objects.filter(member=world.bridge).update(
        superseded_at=timezone.now() - reply_addresses.REPLY_GRACE
    )
    assert inbound.process_inbound(_email(world, message_id="g2@x")).outcome == "bounced"


def test_voided_dies_immediately_even_unsuperseded(world: World) -> None:
    reply_addresses.void_for_member(world.bridge)
    assert inbound.process_inbound(_email(world, message_id="v@x")).outcome == "bounced"


def test_bare_generation_bump_kills_the_address(world: World) -> None:
    Member.objects.filter(pk=world.bridge.pk).update(token_generation=99)
    assert inbound.process_inbound(_email(world, message_id="b@x")).outcome == "bounced"


# --- idempotency, bombs, injection, rate ---


def test_imap_repoll_never_double_posts(world: World) -> None:
    raw = _email(world, message_id="same-message@x")
    source = FixtureMailSource([raw])
    poll(source)
    assert Comment.objects.count() == 1
    replay = FixtureMailSource([raw])  # the same message fetched again
    results = poll(replay)
    assert results[0].outcome == "duplicate"
    assert Comment.objects.count() == 1


def test_mime_bomb_and_oversize_die_before_content(world: World) -> None:
    nested = "Content-Type: multipart/mixed; boundary=b\n\n"
    inner = "--b\nContent-Type: text/plain\n\nx\n" * 40 + "--b--\n"
    bomb = (
        f"Message-ID: <bomb@x>\nFrom: bridge@example.com\n"
        f"To: {world.local_part}@localhost\n{nested}{inner}"
    ).encode()
    assert inbound.process_inbound(bomb).outcome == "quarantined"
    oversize = b"x" * (300 * 1024)
    assert inbound.process_inbound(oversize).outcome == "quarantined"
    assert Comment.objects.count() == 0


def test_injection_fixtures_stay_inert(world: World) -> None:
    crafted = 'sneaky <script>alert("x")</script>\r\nBcc: everyone\x00'
    result = inbound.process_inbound(_email(world, reply_text=crafted, message_id="inj@x"))
    assert result.outcome == "posted"
    comment = Comment.objects.get()
    assert "\x00" not in comment.body and "\r" not in comment.body
    # The body is data; rendering it goes through autoescape like any comment.
    assert "<script>" in comment.body  # stored as text, never executed markup


def test_rate_ceiling_quarantines_the_flood(world: World) -> None:
    outcomes = [
        inbound.process_inbound(_email(world, message_id=f"flood-{i}@x")).outcome for i in range(25)
    ]
    assert "quarantined" in outcomes
    assert outcomes.count("posted") <= inbound._RATE_LIMIT_PER_HOUR


def test_pod_leave_voids_that_pods_reply_capabilities(world: World) -> None:
    """S-502: revoked on ANY membership change — the pod-leave hook."""
    from core import pods as pods_service

    adhoc = Pod.objects.create(name="Cousins chat", kind=Pod.ADHOC)
    adhoc.yards.set([world.maternal])
    PodMembership.objects.create(member=world.bridge, pod=adhoc)
    adhoc_post = Post.objects.create(author=world.bridge, pod=adhoc, body="chat")
    minted = reply_addresses.mint_for_issue(world.issue, [adhoc_post.id])
    pods_service.leave_pod(member=world.bridge, pod=adhoc)
    with pytest.raises(reply_addresses.ReplyAddressInvalid):
        reply_addresses.resolve(minted[adhoc_post.id])


# --- folds from the #39 security review ---


def test_cache_eviction_race_never_raises(world: World, monkeypatch: Any) -> None:
    """#39 review MED-1: DatabaseCache can cull the rate key between get_or_set
    and incr; the pipeline restarts the counter instead of raising out of the
    never-raises contract (which would poison the poll loop)."""
    from django.core.cache import cache as real_cache

    calls = {"n": 0}
    real_incr = real_cache.incr

    def evicted_once(key: str, delta: int = 1) -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError(f"Key {key!r} not found")
        return real_incr(key, delta)

    monkeypatch.setattr("core.inbound.cache.incr", evicted_once)
    result = inbound.process_inbound(_email(world, message_id="evict@x"))
    assert result.outcome == "posted"  # weather, not a crash


def test_attribution_line_never_posts(world: World) -> None:
    """#39 review LOW-2: the trailing 'On ... wrote:' line a bottom-quoting
    client leaves above the separator is dropped, so the sending address never
    lands in the thread."""
    result = inbound.process_inbound(_email(world, "gmail_reply.eml", message_id="attr@x"))
    assert result.outcome == "posted"
    comment = Comment.objects.get()
    assert "wrote:" not in comment.body
    assert "family@example.com" not in comment.body
    assert comment.body == "So glad to see this!"


def test_badge_is_atomic_with_the_comment(world: World) -> None:
    """#39 review LOW-1: via_email is set in the single create, so no crash
    window can leave an email comment that reads as typed."""
    inbound.process_inbound(_email(world, message_id="atomic@x"))
    comment = Comment.objects.get()
    assert comment.via_email is True  # set at INSERT time, not a follow-up write


# --- the trusted envelope recipient (wave 4 webhook path, T-EMAIL-1) ---


def test_envelope_recipient_overrides_a_forged_to_header(world: World) -> None:
    """The webhook path trusts the ESP's envelope recipient, not a To header a
    sender can forge: a message whose To points at a bogus capability still posts
    when the trusted envelope carries the real one."""
    raw = _email(world, local_part="reply-forgednonsense", message_id="env1@x")
    result = inbound.process_inbound(
        raw, envelope_recipient=f"{world.local_part}@mail.backyard.family"
    )
    assert result.outcome == "posted"
    assert Comment.objects.get().post_id == world.m_post.id


def test_envelope_recipient_authoritative_even_when_to_header_is_valid(world: World) -> None:
    """The converse: a real-looking To header cannot rescue a dead envelope
    capability. When the transport supplies an envelope, attribution never falls
    back to the forgeable header."""
    raw = _email(world, message_id="env2@x")  # To carries the REAL capability
    result = inbound.process_inbound(raw, envelope_recipient="reply-neverwas@mail.backyard.family")
    assert result.outcome == "bounced"
    assert Comment.objects.count() == 0


def test_no_envelope_falls_back_to_the_header(world: World) -> None:
    """Raw-bytes sources (fixture, a future IMAP poll) pass no envelope and keep
    the existing MTA-prepended-header behavior."""
    assert inbound.process_inbound(_email(world, message_id="env3@x")).outcome == "posted"
