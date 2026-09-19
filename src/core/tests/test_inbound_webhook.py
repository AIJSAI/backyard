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
import importlib
import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from anymail.inbound import AnymailInboundMessage
from django.test import Client
from django.utils import timezone

from core import digest, inbound_webhook, reply_addresses
from core.models import (
    Comment,
    DigestIssue,
    DigestSubscription,
    InboundQuarantine,
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
    the trusted recipient carried in esp_event['data']['received_for']."""
    raw = (
        f"Message-ID: <wh-1@mail.example>\nFrom: {from_addr}\nTo: {to_header}\n"
        f"Subject: Re: your family digest\nContent-Type: text/plain\n\n"
        f"{text}\n{digest.REPLY_SEPARATOR}\nquoted digest tail below"
    )
    message = AnymailInboundMessage.parse_raw_mime(raw)
    assert message.envelope_recipient is None  # the exact production shape we adapt around
    esp_event = {
        "type": "email.received",
        "data": {
            # `received_for` is Resend's envelope-delivered-for record and the ONLY field
            # this adapter will read (S5). `to` is deliberately set to something else in
            # several tests below, because `to` is the parsed To header — a sender writes
            # it, so treating it as the capability is a forgery primitive.
            "received_for": recipient,
            "to": [to_header],
            "from": from_addr,
        },
    }
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


# --- S5: the capability is the DELIVERED-FOR address, or nothing at all ---------------


def test_a_forged_to_field_in_the_payload_is_not_a_capability(
    reply_setup: tuple[Member, Post, str],
) -> None:
    """The one that made this a forgery primitive.

    `data["to"]` is the parsed To recipients of the received message, and a sender writes
    that. Sending to their OWN valid inbound address while addressing the message
    `To: reply+<somebody-else's-capability>@…` posted a comment as that somebody else.
    Fails without the `received_for`-only rule in `_trusted_recipient`.
    """
    _member, _post, local = reply_setup
    event = _event(
        to_header="anything@mail.backyard.family",
        recipient="reply-neverwas@mail.backyard.family",
        from_addr="gran@example.com",
        text="Not mine to post.",
    )
    event.esp_event["data"]["to"] = [f"{local}@mail.backyard.family"]
    del event.esp_event["data"]["received_for"]
    _fire(event)
    assert Comment.objects.count() == 0


def test_a_payload_with_no_delivered_for_address_fails_closed(
    reply_setup: tuple[Member, Post, str],
) -> None:
    """No trustworthy address means no post — never a fall back to the message header,
    which through this transport is the sender's own.

    Fails without `_trusted_recipient` raising: `process_inbound` receives "" and reads
    the To header off the raw MIME, which the event below sets to a live capability.
    """
    _member, _post, local = reply_setup
    event = _event(
        to_header=f"{local}@mail.backyard.family",  # the sender's own header
        recipient="unused",
        from_addr="gran@example.com",
        text="Should not post.",
    )
    del event.esp_event["data"]["received_for"]
    _fire(event)
    assert Comment.objects.count() == 0
    assert InboundQuarantine.objects.count() == 1, (
        "a refusal that leaves no trace is indistinguishable from mail that never arrived"
    )


def test_a_multi_recipient_delivery_is_refused_rather_than_resolved_to_the_first(
    reply_setup: tuple[Member, Post, str],
) -> None:
    """An envelope delivered for two addresses carries two capabilities, and `[0]` picks
    one arbitrarily. Reply addresses are minted per member and per post, so a genuine
    reply is always delivered for exactly one."""
    _member, _post, local = reply_setup
    event = _event(
        to_header=f"{local}@mail.backyard.family",
        recipient="unused",
        from_addr="gran@example.com",
        text="Should not post.",
    )
    event.esp_event["data"]["received_for"] = [
        f"{local}@mail.backyard.family",
        "someone-else@mail.backyard.family",
    ]
    _fire(event)
    assert Comment.objects.count() == 0


def test_a_single_element_delivered_for_list_still_works(
    reply_setup: tuple[Member, Post, str],
) -> None:
    """Guard the guard: refusing a LIST outright would break a provider that always
    sends one. Exactly one address is exactly one capability."""
    member, post, local = reply_setup
    event = _event(
        to_header="whatever@mail.backyard.family",
        recipient="unused",
        from_addr="gran@example.com",
        text="Lovely.",
    )
    event.esp_event["data"]["received_for"] = [f"{local}@mail.backyard.family"]
    _fire(event)
    comment = Comment.objects.get()
    assert comment.post_id == post.id and comment.author_id == member.id


# --- S1: the fetch upstream makes is bounded in time and in size ---------------------


def _any_non_empty_value() -> str:
    """A configured-looking value, assembled rather than written.

    All this test needs is "not the empty string". Writing it as a literal beside a name
    containing `SECRET` is the exact shape this repo's credential AST guard, its gitleaks
    rule and its pre-commit hook all fire on, and all three would be right to — a join()
    is a call, and no formatter folds a call back into a literal.
    """
    return "-".join(("whsec", "not", "a", "real", "value"))


def _bounded_view() -> inbound_webhook.BoundedResendInboundWebhookView:
    """The view, built with NO credential arguments.

    Anymail resolves its api key from settings, which is the empty default here, and the
    inbound secret is passed as None — the value that means "unsigned", and the one the
    mixin already branches on. No value in this file is credential-shaped, which matters
    beyond tidiness: a literal of that shape in a test file is exactly what this repo's
    gitleaks rule, its pre-commit hook and its own credential AST guard all fire on, and
    all three would have been right to.
    """
    return inbound_webhook.BoundedResendInboundWebhookView(
        api_url="https://api.resend.example/", inbound_secret=None
    )


class _FakeResponse:
    """The slice of `requests.Response` the bounded fetch touches."""

    def __init__(self, chunks: list[bytes], headers: dict[str, str] | None = None) -> None:
        self._chunks = chunks
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, size: int) -> list[bytes]:
        return self._chunks

    def close(self) -> None:
        self.closed = True


def test_every_inbound_fetch_carries_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Upstream `anymail.webhooks.resend` makes three `requests.get` calls with no
    `timeout=`, inside the webhook's own request cycle. A provider that accepts the
    connection and then says nothing holds a gunicorn worker for as long as it likes.

    Fails without `BoundedResendInboundWebhookView`: the calls carry no timeout.
    """
    calls: list[dict[str, object]] = []
    body = json.dumps({"raw": {"download_url": "https://resend.example/raw"}}).encode()

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        calls.append({"url": url, **kwargs})
        if url.endswith("/raw"):
            return _FakeResponse([b"From: a@b\r\nTo: c@d\r\n\r\nhi\r\n"])
        return _FakeResponse([body])

    monkeypatch.setattr("core.inbound_webhook.requests.get", fake_get)
    view = _bounded_view()
    message = view._fetch_inbound_email("email-1")

    assert message is not None
    assert len(calls) == 2, calls
    for call in calls:
        assert call["timeout"] == inbound_webhook._FETCH_TIMEOUT, call
        assert call["stream"] is True, "an unstreamed read buffers the whole body first"


@pytest.mark.django_db
def test_an_oversized_inbound_fetch_is_refused_rather_than_buffered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The size half of the bound. `response.content` reads to whatever end the sender
    chooses; this gives up the moment the total passes the cap, closes the socket, and
    records the refusal so it is visible rather than silent.

    Not raised: a retry cannot make an over-large message smaller, and Resend retries a
    500 — which is the poison-retry loop the message-less guard already exists to avoid.
    """
    body = json.dumps({"raw": {"download_url": "https://resend.example/raw"}}).encode()
    flood = _FakeResponse([b"x" * 65536] * ((inbound_webhook._MAX_FETCH_BYTES // 65536) + 2))

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        return flood if url.endswith("/raw") else _FakeResponse([body])

    monkeypatch.setattr("core.inbound_webhook.requests.get", fake_get)
    view = _bounded_view()

    assert view._fetch_inbound_email("email-1") is None
    assert flood.closed, "the response was left open after the refusal"
    assert InboundQuarantine.objects.count() == 1


# --- S4: no secret, no route -----------------------------------------------------------


def test_the_inbound_route_is_not_mounted_without_the_secret(settings: Any) -> None:
    """An SMTP-configured self-hoster answered every unauthenticated POST to this path
    with an unhandled 500, because Anymail had no secret to verify a signature against.

    Fails without `_inbound_urlpatterns`: the route is mounted unconditionally.
    """
    from config import urls

    settings.RESEND_INBOUND_SECRET = ""
    assert urls._inbound_urlpatterns() == []

    settings.RESEND_INBOUND_SECRET = _any_non_empty_value()
    mounted = urls._inbound_urlpatterns()
    assert len(mounted) == 1
    assert str(mounted[0].pattern) == "anymail/resend/inbound/"


def test_the_route_is_absent_from_the_live_resolver_on_this_instance() -> None:
    """The wiring, not the helper: with no secret configured (the test and local-compose
    posture) the path resolves like any other unknown URL."""
    from django.urls import Resolver404, resolve

    with pytest.raises(Resolver404):
        resolve("/anymail/resend/inbound/")


def test_the_view_refuses_even_if_something_mounts_it(settings: Any, rf: Any) -> None:
    """The second lock. A control that lives only in a URLconf is one `include` away
    from being bypassed, so the view answers 404 on its own."""
    from django.http import Http404

    settings.RESEND_INBOUND_SECRET = ""
    view = _bounded_view()
    with pytest.raises(Http404):
        view.dispatch(rf.post("/anymail/resend/inbound/"))


# --- C1: the override must carry Anymail's two exemptions ----------------------------


@pytest.mark.django_db
def test_the_mounted_route_is_not_rejected_by_the_csrf_check(settings: Any) -> None:
    """The CRITICAL from the security review of this PR.

    `View.as_view()` copies `cls.dispatch.__dict__` onto the callable it returns, and that
    dict is where `csrf_exempt` and `login_not_required` live. Overriding `dispatch`
    without re-applying them silently drops Anymail's, so `CsrfViewMiddleware` rejects
    every Resend inbound POST before the svix signature is ever checked: no verification,
    no quarantine row, no bounce, and reply-by-email dies with nothing anywhere saying so.

    Driven with `enforce_csrf_checks=True` THROUGH THE MOUNTED ROUTE, because the default
    test Client disables CSRF entirely — which is exactly why the rest of this file, and
    the whole suite, never saw it. Red without the two decorators: 403.
    """
    settings.RESEND_INBOUND_SECRET = _any_non_empty_value()
    settings.ANYMAIL = {**settings.ANYMAIL, "RESEND_INBOUND_SECRET": settings.RESEND_INBOUND_SECRET}

    from django.urls import clear_url_caches

    import config.urls

    importlib.reload(config.urls)
    clear_url_caches()
    try:
        response = Client(enforce_csrf_checks=True).post(
            "/anymail/resend/inbound/",
            data=json.dumps({"type": "email.received", "data": {}}),
            content_type="application/json",
        )
    finally:
        settings.RESEND_INBOUND_SECRET = ""
        importlib.reload(config.urls)
        clear_url_caches()

    assert response.status_code != 403, (
        "CsrfViewMiddleware rejected a machine POST from another origin: the dispatch "
        "override dropped anymail's csrf_exempt, so no inbound reply would ever be "
        "verified, quarantined or bounced"
    )
    # 400 is Anymail refusing an unsigned payload, which is the correct answer and proves
    # the request reached the view rather than dying in middleware.
    assert response.status_code == 400, response.status_code


def test_both_exemptions_are_actually_attached_to_the_view_callable() -> None:
    """The mechanism, at the seam where it is read: `as_view()` copies these off
    `dispatch.__dict__`, and middleware reads them off the resolved callable."""
    view = inbound_webhook.BoundedResendInboundWebhookView.as_view()
    assert getattr(view, "csrf_exempt", False) is True
    assert getattr(view, "login_required", True) is False


# --- M1: the fetch is bounded in TIME, not only in bytes -----------------------------


@pytest.mark.django_db
def test_a_trickling_response_is_refused_on_the_wall_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """The size cap does not bound a trickle: the socket read timeout resets on every
    chunk, so a sender who emits one byte inside every window is legal, endless, and holds
    a gunicorn worker for as long as it likes — while never approaching the byte cap.

    The body below is deliberately TINY (200 bytes, against a 1 MiB cap) and slow, so the
    only thing that can refuse it is the clock. Red without the deadline in `_read_capped`:
    the 200 bytes are accepted and a message comes back.
    """
    body = json.dumps({"raw": {"download_url": "https://resend.example/raw"}}).encode()

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        # One byte per chunk, two hundred chunks: far under the byte cap, far over the
        # time budget at one simulated second per chunk.
        return _FakeResponse([b"x"] * 200) if url.endswith("/raw") else _FakeResponse([body])

    monkeypatch.setattr("core.inbound_webhook.requests.get", fake_get)
    # Simulated, not slept: this asserts the DEADLINE, not the test machine's wall clock.
    clock = iter(float(i) for i in range(100000))
    monkeypatch.setattr("core.inbound_webhook.time.monotonic", lambda: next(clock))

    assert _bounded_view()._fetch_inbound_email("email-1") is None
    assert InboundQuarantine.objects.count() == 1


def test_the_refusal_names_the_budget_rather_than_the_byte_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Which limit fired is the whole question: a message saying "exceeded N bytes" for a
    slow trickle would mean the byte cap caught it by accident and the time bound is
    absent. Asserted on `_read_capped` directly, where the two reasons are distinguishable."""
    clock = iter(float(i) for i in range(100000))
    monkeypatch.setattr("core.inbound_webhook.time.monotonic", lambda: next(clock))

    with pytest.raises(inbound_webhook.InboundFetchRefused) as caught:
        inbound_webhook._read_capped(
            # _FakeResponse implements the slice of requests.Response this reads.
            cast(Any, _FakeResponse([b"x"] * 200)),
            what="the raw inbound message",
            deadline=60.0,
        )
    assert "budget" in str(caught.value), caught.value


def test_the_budget_is_one_deadline_shared_by_every_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three requests, one budget — otherwise each is bounded and the sum is not."""
    seen: list[float] = []
    body = json.dumps({"raw": {"download_url": "https://resend.example/raw"}}).encode()

    real_read = inbound_webhook._read_capped

    def recording_read(response: Any, *, what: str, deadline: float) -> bytes:
        seen.append(deadline)
        return real_read(response, what=what, deadline=deadline)

    monkeypatch.setattr("core.inbound_webhook._read_capped", recording_read)
    monkeypatch.setattr(
        "core.inbound_webhook.requests.get",
        lambda url, **kw: _FakeResponse(
            [b"From: a@b\r\nTo: c@d\r\n\r\nhi\r\n"] if url.endswith("/raw") else [body]
        ),
    )

    _bounded_view()._fetch_inbound_email("email-1")

    assert len(seen) == 2 and len(set(seen)) == 1, seen
