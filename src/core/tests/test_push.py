"""Who is notified, what the notification says, and what a failure does (S-107).

NOTHING HERE TOUCHES THE NETWORK, and nothing here mocks `webpush`. The one thing that is
stubbed is `requests.Session.request` — the socket — so the REAL encryption path runs on
every send: pywebpush derives a shared secret against a real P-256 key generated in the
fixture, `http_ece` encrypts the payload, `py_vapid` signs the assertion, and this suite
reads the request that would have gone out. Stubbing `webpush` itself would have proved
that this module calls a function, which is the one thing nobody doubts.

No key literal appears in this file. `_a_device` generates a fresh P-256 pair and a
16-byte secret per call, so `gitleaks git` has nothing to find (it walks every branch, and
one credential-shaped literal fails the secrets job on every open pull request at once)
and the fixtures are the shapes a browser actually produces.

The cross-side cases are the ones to read first. A bridging household belongs to both
sides of the family, and the two tests named `..._never_crosses_the_family` are the whole
promise of this product arriving on a lock screen.
"""

from __future__ import annotations

import base64
import json
import logging
import secrets as stdlib_secrets
import time
from dataclasses import dataclass
from typing import Any

import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.contrib.auth import get_user_model
from django.utils import timezone

from core import commenting, notifications, posting, push, push_endpoints, reacting
from core.management.commands.generate_vapid_keys import generate_pair
from core.models import (
    Comment,
    MediaAsset,
    Member,
    Pod,
    PodMembership,
    PushSubscription,
    Yard,
)

pytestmark = pytest.mark.django_db
User = get_user_model()


# --- fixtures --------------------------------------------------------------------------


@dataclass(frozen=True)
class Family:
    """Two sides and one bridging household, the founding shape (test_isolation.py).

    `bridge` belongs to both sides; `maternal` and `paternal` each belong to one and
    cannot see, name, or learn of each other.
    """

    maternal_yard: Yard
    paternal_yard: Yard
    bridge_pod: Pod
    maternal_pod: Pod
    paternal_pod: Pod
    bridge: Member
    maternal: Member
    paternal: Member
    maternal_cousin: Member


def _member(pod: Pod, name: str, *, supervised: bool = False) -> Member:
    tag = stdlib_secrets.token_hex(4)
    user = User.objects.create_user(username=f"{name.lower().replace(' ', '-')}-{tag}")
    member = Member.objects.create(display_name=name, user=user, is_supervised=supervised)
    PodMembership.objects.create(member=member, pod=pod)
    return member


@pytest.fixture
def family() -> Family:
    maternal_yard = Yard.objects.create(name="Maternal", slug="maternal")
    paternal_yard = Yard.objects.create(name="Paternal", slug="paternal")
    bridge_pod = Pod.objects.create(name="Bridge household", kind=Pod.HOUSEHOLD)
    bridge_pod.yards.set([maternal_yard, paternal_yard])
    maternal_pod = Pod.objects.create(name="Maternal cousins", kind=Pod.HOUSEHOLD)
    maternal_pod.yards.set([maternal_yard])
    paternal_pod = Pod.objects.create(name="Paternal cousins", kind=Pod.HOUSEHOLD)
    paternal_pod.yards.set([paternal_yard])
    return Family(
        maternal_yard=maternal_yard,
        paternal_yard=paternal_yard,
        bridge_pod=bridge_pod,
        maternal_pod=maternal_pod,
        paternal_pod=paternal_pod,
        bridge=_member(bridge_pod, "Bridging Parent"),
        maternal=_member(maternal_pod, "Ann Maternal"),
        paternal=_member(paternal_pod, "Bo Paternal"),
        maternal_cousin=_member(maternal_pod, "Cass Maternal"),
    )


def _a_device(member: Member, *, label: str = "iPhone") -> PushSubscription:
    """One subscribed device, with key material a browser would really send.

    Generated per call rather than written down: see the module docstring. The private
    half is thrown away — the server never has it, which is the whole point of RFC 8291.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    point = key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return PushSubscription.objects.create(
        member=member,
        endpoint=f"https://fcm.googleapis.com/fcm/send/{stdlib_secrets.token_urlsafe(16)}",
        p256dh=base64.urlsafe_b64encode(point).rstrip(b"=").decode(),
        auth=base64.urlsafe_b64encode(stdlib_secrets.token_bytes(16)).rstrip(b"=").decode(),
        label=label,
    )


def a_valid_subscription_body() -> dict[str, str]:
    """What `PushManager.subscribe().toJSON()` produces, generated per call.

    Shared with test_push_routes.py so the route tests post the shape a browser really
    sends rather than a shape somebody remembered.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    point = key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return {
        "endpoint": f"https://fcm.googleapis.com/fcm/send/{stdlib_secrets.token_urlsafe(16)}",
        "p256dh": base64.urlsafe_b64encode(point).rstrip(b"=").decode(),
        "auth": base64.urlsafe_b64encode(stdlib_secrets.token_bytes(16)).rstrip(b"=").decode(),
    }


@pytest.fixture
def push_on(settings: Any) -> None:
    """Turn the feature on with a key pair generated for this test run.

    `generate_pair` is the management command's own function, so the suite proves the
    documented way of producing keys makes keys this app accepts — rather than the test
    agreeing with itself about a format.
    """
    public, private = generate_pair()
    settings.VAPID_PUBLIC_KEY = public
    settings.VAPID_PRIVATE_KEY = private
    settings.VAPID_SUBJECT = "mailto:admin@example.test"
    settings.PUSH_ENABLED = True


class Wire:
    """Every request that would have left the box, and the answer it was given.

    What it deliberately does NOT offer is a decrypted payload: only the device's own
    private key opens one, and the server never has it. So this suite asserts WORDING
    against `push.post_payload` / `push.reply_payload` and DELIVERY against the wire.
    That split is the honest one — it is exactly what the server can know.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.status = 201
        self.status_for: dict[str, int] = {}

    def endpoints(self) -> list[str]:
        return [url for _method, url, _kwargs in self.calls]


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    """Stub the SOCKET, not the library. Everything above `requests` really runs."""
    recorder = Wire()

    def fake_request(
        self: requests.Session, method: str, url: str, **kwargs: Any
    ) -> requests.Response:
        recorder.calls.append((method, url, kwargs))
        response = requests.Response()
        response.status_code = recorder.status_for.get(url, recorder.status)
        response.url = url
        response.reason = "stubbed"
        response._content = b"a push service body nobody should log"
        return response

    monkeypatch.setattr(requests.Session, "request", fake_request)
    return recorder


# --- who gets one ----------------------------------------------------------------------


def test_a_post_reaches_everyone_who_can_see_it_except_its_author(
    family: Family, push_on: None, wire: Wire
) -> None:
    for member in (family.bridge, family.maternal, family.maternal_cousin):
        _a_device(member)
    post = posting.create_post(
        author=family.maternal,
        pod=family.maternal_pod,
        audience_yards=[family.maternal_yard],
        body="At the lake",
    )
    sent = push.deliver_new_post(post)
    assert sent == 2  # the bridge and the cousin; never the author
    notified = set(
        PushSubscription.objects.filter(endpoint__in=wire.endpoints()).values_list(
            "member__display_name", flat=True
        )
    )
    assert notified == {"Bridging Parent", "Cass Maternal"}


def test_a_post_never_crosses_the_family(family: Family, push_on: None, wire: Wire) -> None:
    """The central promise. A maternal post reaches the bridging household, which is in
    both sides, and NEVER the paternal member — who must not learn that Ann exists."""
    _a_device(family.paternal)
    _a_device(family.bridge)
    post = posting.create_post(
        author=family.maternal,
        pod=family.maternal_pod,
        audience_yards=[family.maternal_yard],
        body="Only my side sees this",
    )
    recipients = {m.pk for m in push.recipients_for_post(post)}
    assert recipients == {family.bridge.pk}
    push.deliver_new_post(post)
    assert len(wire.calls) == 1


def test_a_reply_on_a_bridging_post_never_crosses_the_family(
    family: Family, push_on: None, wire: Wire
) -> None:
    """A post addressed to BOTH sides is the one place where "can see the post" is not
    enough. Ann and Bo can both see the post. When Bo replies, Ann must not be told
    "Bo Replied" — she cannot see Bo at all, and the notification would name him.

    This is why `recipients_for_reply` asks `visible_comments`, which intersects with
    `visible_members` (the T-YARD-4 fix in scoping.py), and not `visible_posts`.
    """
    both_sides = posting.create_post(
        author=family.bridge,
        pod=family.bridge_pod,
        audience_yards=[family.maternal_yard, family.paternal_yard],
        body="A post to the whole family",
    )
    # Ann replies first, so she is "in the thread" and a candidate for Bo's reply.
    Comment.objects.create(post=both_sides, author=family.maternal, body="Lovely")
    for member in (family.maternal, family.bridge):
        _a_device(member)

    from_the_other_side = Comment.objects.create(
        post=both_sides, author=family.paternal, body="Wonderful"
    )
    recipients = {m.pk for m in push.recipients_for_reply(from_the_other_side)}
    assert family.maternal.pk not in recipients, (
        "a maternal member was told a paternal member's name on a lock screen"
    )
    assert recipients == {family.bridge.pk}


def test_a_reply_reaches_the_author_and_the_earlier_repliers(
    family: Family, push_on: None, wire: Wire
) -> None:
    post = posting.create_post(
        author=family.maternal,
        pod=family.maternal_pod,
        audience_yards=[family.maternal_yard],
        body="Who is coming?",
    )
    Comment.objects.create(post=post, author=family.maternal_cousin, body="Me")
    for member in (family.maternal, family.maternal_cousin, family.bridge):
        _a_device(member)
    # The bridge replies: the author and the earlier replier hear, the bridge does not.
    reply = Comment.objects.create(post=post, author=family.bridge, body="And me")
    recipients = {m.pk for m in push.recipients_for_reply(reply)}
    assert recipients == {family.maternal.pk, family.maternal_cousin.pk}


def test_somebody_who_only_read_the_post_is_not_told_about_a_reply(
    family: Family, push_on: None
) -> None:
    """A reply notifies the thread, not the audience. The cousin can see the post and has
    a device; she has not written in it, so she is not pulled into somebody else's
    conversation."""
    post = posting.create_post(
        author=family.maternal,
        pod=family.maternal_pod,
        audience_yards=[family.maternal_yard],
        body="Who is coming?",
    )
    _a_device(family.maternal_cousin)
    _a_device(family.maternal)
    reply = Comment.objects.create(post=post, author=family.bridge, body="Me")
    assert {m.pk for m in push.recipients_for_reply(reply)} == {family.maternal.pk}


def test_a_toggle_that_is_off_silences_that_event_type(family: Family, push_on: None) -> None:
    _a_device(family.bridge)
    _a_device(family.maternal)
    preference = notifications.preference_for(family.bridge)
    preference.push_new_posts = False
    preference.save(update_fields=["push_new_posts"])
    post = posting.create_post(
        author=family.maternal,
        pod=family.maternal_pod,
        audience_yards=[family.maternal_yard],
        body="Something",
    )
    assert push.recipients_for_post(post) == []
    # ...and the OTHER event type is untouched, which is what two toggles means.
    Comment.objects.create(post=post, author=family.bridge, body="I am here")
    reply = Comment.objects.create(post=post, author=family.maternal_cousin, body="So am I")
    assert {m.pk for m in push.recipients_for_reply(reply)} == {
        family.bridge.pk,
        family.maternal.pk,
    }


def test_a_member_who_never_opened_the_page_is_treated_as_on(family: Family, push_on: None) -> None:
    """No NotificationPreference row means the member has never opened Settings. The row
    `preference_for` would create defaults both push fields to True, so the absent row has
    to answer the same way — otherwise subscribing a device would silently do nothing
    until the member also visited a page they have no reason to visit."""
    _a_device(family.bridge)
    assert not hasattr(family.bridge, "notification_preference")
    post = posting.create_post(
        author=family.maternal,
        pod=family.maternal_pod,
        audience_yards=[family.maternal_yard],
        body="Something",
    )
    assert [m.pk for m in push.recipients_for_post(post)] == [family.bridge.pk]


def test_a_supervised_account_is_never_notified(family: Family, push_on: None) -> None:
    """TM-10: a child's account is parent-managed and has no sign-in of its own, so it
    can never have subscribed — and if a row existed anyway it is excluded here."""
    child = _member(family.maternal_pod, "A Child", supervised=True)
    _a_device(child)
    post = posting.create_post(
        author=family.maternal,
        pod=family.maternal_pod,
        audience_yards=[family.maternal_yard],
        body="Something",
    )
    assert push.recipients_for_post(post) == []


def test_a_deactivated_account_is_never_notified(family: Family, push_on: None) -> None:
    _a_device(family.bridge)
    assert family.bridge.user is not None
    family.bridge.user.is_active = False
    family.bridge.user.save(update_fields=["is_active"])
    post = posting.create_post(
        author=family.maternal,
        pod=family.maternal_pod,
        audience_yards=[family.maternal_yard],
        body="Something",
    )
    assert push.recipients_for_post(post) == []


# --- what stays silent -----------------------------------------------------------------


def test_the_arrival_card_notifies_nobody(
    family: Family, push_on: None, django_capture_on_commit_callbacks: Any
) -> None:
    """ "Just joined." is written by the product, not by a person. Ten relatives arriving
    over a week must not be ten lock-screen notifications. Enforced by `notify=False` at
    the one call site rather than by comparing the body text, so a relative who happens to
    type the same words is not silenced."""
    _a_device(family.maternal_cousin)
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        posting.announce_arrival(family.maternal, family.maternal_pod)
    assert callbacks == []


def test_an_ordinary_post_does_defer_a_job(
    family: Family, push_on: None, django_capture_on_commit_callbacks: Any
) -> None:
    """The denominator for the test above: if `create_post` stopped deferring at all, the
    arrival assertion would pass while the whole feature was dead."""
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        posting.create_post(
            author=family.maternal,
            pod=family.maternal_pod,
            audience_yards=[],
            body="A real post",
        )
    assert len(callbacks) == 1


def test_a_reaction_notifies_nobody(
    family: Family, push_on: None, wire: Wire, django_capture_on_commit_callbacks: Any
) -> None:
    """The easiest firehose to grow, and the product deliberately does not have it."""
    post = posting.create_post(
        author=family.maternal,
        pod=family.maternal_pod,
        audience_yards=[family.maternal_yard],
        body="A photo of the lake",
    )
    _a_device(family.maternal)
    with django_capture_on_commit_callbacks(execute=True):
        reacting.toggle_reaction(member=family.bridge, post=post, kind="heart")
    assert wire.calls == []


def test_the_feature_off_sends_nothing_and_opens_no_socket(
    family: Family, wire: Wire, settings: Any
) -> None:
    """A self-hoster with no VAPID pair. Not "it fails gracefully" — it never starts."""
    settings.PUSH_ENABLED = False
    _a_device(family.bridge)
    post = posting.create_post(
        author=family.maternal,
        pod=family.maternal_pod,
        audience_yards=[family.maternal_yard],
        body="Something",
    )
    assert push.deliver_new_post(post) == 0
    assert wire.calls == []


# --- what a notification says ----------------------------------------------------------


def test_a_post_payload_names_the_author_and_opens_the_post(family: Family) -> None:
    post = posting.create_post(
        author=family.maternal,
        pod=family.maternal_pod,
        audience_yards=[],
        body="We got the tickets",
    )
    payload = push.post_payload(post)
    assert payload["title"] == "Ann Posted"  # the FIRST name, via Member.short_name
    assert payload["body"] == "We got the tickets"
    assert payload["url"] == f"/posts/{post.pk}/"
    assert payload["tag"] == f"post-{post.pk}"


def test_a_reply_carries_its_post_s_tag_so_a_busy_thread_collapses(family: Family) -> None:
    """The tag is what makes fifty replies one entry on the device, and what makes a
    redelivered job replace its own notification instead of adding a second."""
    post = posting.create_post(
        author=family.maternal, pod=family.maternal_pod, audience_yards=[], body="A question"
    )
    reply = Comment.objects.create(post=post, author=family.bridge, body="An answer")
    assert push.reply_payload(reply)["tag"] == push.post_payload(post)["tag"]
    assert push.reply_payload(reply)["title"] == "Bridging Replied"


def test_a_long_body_is_cut_at_a_word_and_carries_no_ellipsis(family: Family) -> None:
    """The voice guide forbids the ellipsis character outright, and a phone truncates the
    line again to fit its own lock screen, so the cut simply stops."""
    words = "birthday " * 40
    post = posting.create_post(
        author=family.maternal, pod=family.maternal_pod, audience_yards=[], body=words
    )
    body = push.post_payload(post)["body"]
    assert len(body) <= push.BODY_CHARACTERS
    assert not body.endswith(" ")
    assert "…" not in body and "..." not in body
    assert body.split()[-1] == "birthday"  # cut on a boundary, never mid-word


def test_a_body_with_newlines_becomes_one_line(family: Family) -> None:
    post = posting.create_post(
        author=family.maternal,
        pod=family.maternal_pod,
        audience_yards=[],
        body="Line one\n\nLine two",
    )
    assert push.post_payload(post)["body"] == "Line one Line two"


@pytest.mark.parametrize(
    ("photos", "videos", "expected"),
    [
        (1, 0, "Shared a photo."),
        (3, 0, "Shared 3 photos."),
        (0, 1, "Shared a video."),
        (0, 2, "Shared 2 videos."),
        (2, 1, "Shared 3 photos and videos."),
    ],
)
def test_a_post_with_no_words_says_what_was_shared(
    family: Family, photos: int, videos: int, expected: str
) -> None:
    post = posting.create_post(
        author=family.maternal, pod=family.maternal_pod, audience_yards=[], body=""
    )
    for _ in range(photos):
        MediaAsset.objects.create(post=post, media_kind=MediaAsset.PHOTO)
    for _ in range(videos):
        MediaAsset.objects.create(post=post, media_kind=MediaAsset.VIDEO)
    assert push.post_payload(post)["body"] == expected


def test_a_link_card_image_is_not_counted_as_a_photo(family: Family) -> None:
    """S-301's re-hosted og:image is the card's picture, not something anybody in this
    family would call a photo. `scoping.visible_attached_media` draws the same line."""
    post = posting.create_post(
        author=family.maternal, pod=family.maternal_pod, audience_yards=[], body=""
    )
    MediaAsset.objects.create(post=post, media_kind=MediaAsset.LINK_PREVIEW)
    MediaAsset.objects.create(post=post, media_kind=MediaAsset.PHOTO)
    assert push.post_payload(post)["body"] == "Shared a photo."


def test_the_members_own_words_beat_the_media_line(family: Family) -> None:
    post = posting.create_post(
        author=family.maternal, pod=family.maternal_pod, audience_yards=[], body="At the lake"
    )
    MediaAsset.objects.create(post=post, media_kind=MediaAsset.PHOTO)
    assert push.post_payload(post)["body"] == "At the lake"


def test_a_display_name_with_no_first_word_still_names_somebody(family: Family) -> None:
    """`short_name` is empty for a whitespace-only display name, and a notification
    reading " Posted" is worse than one naming somebody in full."""
    family.maternal.display_name = "Moone"
    family.maternal.save(update_fields=["display_name"])
    post = posting.create_post(
        author=family.maternal, pod=family.maternal_pod, audience_yards=[], body="x"
    )
    assert push.post_payload(post)["title"] == "Moone Posted"


# --- the send itself -------------------------------------------------------------------


def test_a_real_encrypted_request_reaches_the_push_service(
    family: Family, push_on: None, wire: Wire
) -> None:
    """The whole stack, with only the socket stubbed: ECDH against the device's key,
    aes128gcm encryption, the VAPID assertion, and the POST."""
    device = _a_device(family.bridge)
    assert push.send_one(device, {"title": "Ann Posted", "body": "x", "url": "/", "tag": "t"})
    (method, url, kwargs) = wire.calls[0]
    assert method == "POST"
    assert url == device.endpoint
    assert kwargs["headers"]["content-encoding"] == "aes128gcm"
    # RFC 8292's vapid01 scheme, which is what py_vapid signs and every push service
    # in the allowlist accepts. The assertion is a JWT, signed with the operator's own
    # private key -- so this line also proves the key pair reached the send at all.
    assert kwargs["headers"]["Authorization"].startswith("WebPush ")
    # The payload on the wire is CIPHERTEXT. If this ever reads as JSON, the encryption
    # has silently stopped happening and the push service can read the family's posts.
    assert isinstance(kwargs["data"], bytes)
    with pytest.raises(ValueError):
        json.loads(kwargs["data"])
    assert b"Ann Posted" not in kwargs["data"]


def test_the_outbound_request_follows_no_redirect_and_carries_a_timeout(
    family: Family, push_on: None, wire: Wire
) -> None:
    """A push service answering 302 to an internal address is the textbook way around a
    host allowlist, and `requests` follows redirects by default."""
    device = _a_device(family.bridge)
    push.send_one(device, {"title": "t", "body": "b", "url": "/", "tag": "t"})
    (_method, _url, kwargs) = wire.calls[0]
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == push.SEND_TIMEOUT
    assert kwargs["proxies"] == {}


def test_a_row_whose_host_left_the_allowlist_is_never_posted_to(
    family: Family, push_on: None, wire: Wire, settings: Any
) -> None:
    """The reason the endpoint is validated twice. A row outlives the configuration it was
    written under: an operator narrowing the allowlist, or a row edited at a database
    shell, must not become an outbound request."""
    device = _a_device(family.bridge)
    settings.PUSH_SERVICE_HOSTS = ("updates.push.services.mozilla.com",)
    assert push.send_one(device, {"title": "t", "body": "b", "url": "/", "tag": "t"}) is False
    assert wire.calls == []
    device.refresh_from_db()
    assert device.failure_count == 1  # counted as a failure, not silently ignored


def test_the_session_refuses_an_endpoint_it_is_handed_directly(push_on: None) -> None:
    """The control sits on the SESSION, so it holds for any caller inside pywebpush,
    including a future code path that does not go through `send_one`."""
    from core.push_endpoints import UnsafeEndpoint

    with pytest.raises(UnsafeEndpoint):
        push.PushServiceSession().post("https://169.254.169.254/latest/meta-data/")


def test_success_stamps_the_row_and_clears_the_failure_run(
    family: Family, push_on: None, wire: Wire
) -> None:
    device = _a_device(family.bridge)
    PushSubscription.objects.filter(pk=device.pk).update(failure_count=3)
    device.refresh_from_db()
    assert push.send_one(device, {"title": "t", "body": "b", "url": "/", "tag": "t"})
    device.refresh_from_db()
    assert device.failure_count == 0
    assert device.last_success_at is not None
    assert device.last_success_at <= timezone.now()


@pytest.mark.parametrize("status", [404, 410])
def test_a_gone_subscription_is_deleted(
    family: Family, push_on: None, wire: Wire, status: int
) -> None:
    """RFC 8030's own "this registration is finished". The ordinary end of a
    subscription's life: a browser rotating its endpoint, an app deleted from a home
    screen. Not a failure to count — a delete."""
    device = _a_device(family.bridge)
    wire.status = status
    assert push.send_one(device, {"title": "t", "body": "b", "url": "/", "tag": "t"}) is False
    assert not PushSubscription.objects.filter(pk=device.pk).exists()


def test_other_failures_are_counted_and_the_row_goes_after_enough_of_them(
    family: Family, push_on: None, wire: Wire
) -> None:
    device = _a_device(family.bridge)
    wire.status = 500
    for attempt in range(1, push.MAX_CONSECUTIVE_FAILURES):
        device.refresh_from_db()
        assert push.send_one(device, {"title": "t", "body": "b", "url": "/", "tag": "t"}) is False
        device.refresh_from_db()
        assert device.failure_count == attempt
    assert push.send_one(device, {"title": "t", "body": "b", "url": "/", "tag": "t"}) is False
    assert not PushSubscription.objects.filter(pk=device.pk).exists()


def test_one_dead_device_never_stops_the_others(family: Family, push_on: None, wire: Wire) -> None:
    """The property that matters most on a family instance: one relative's stale phone
    must not silence a post for everybody else."""
    dead = _a_device(family.bridge, label="Old Android")
    alive_one = _a_device(family.maternal_cousin)
    alive_two = _a_device(family.bridge, label="Mac")
    wire.status_for[dead.endpoint] = 410
    post = posting.create_post(
        author=family.maternal,
        pod=family.maternal_pod,
        audience_yards=[family.maternal_yard],
        body="Something",
    )
    assert push.deliver_new_post(post) == 2
    assert not PushSubscription.objects.filter(pk=dead.pk).exists()
    for survivor in (alive_one, alive_two):
        survivor.refresh_from_db()
        assert survivor.last_success_at is not None


def test_the_fan_out_stops_at_its_budget_without_punishing_anybody(
    family: Family, push_on: None, wire: Wire, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hanging push service must not hold the whole worker.

    docker-compose runs ONE Procrastinate worker at concurrency 1 across every queue, so a
    service that black-holes costs SEND_TIMEOUT twice per device, serially, with the
    transcode, the digest and the nightly BACKUP waiting behind it. Past the budget the
    remaining devices are simply skipped, and skipped is not failed: a slow service is not
    a dead one, so nothing is deleted, no failure is counted, and the next post reaches
    them.

    The clock is stubbed rather than the sleep, so the test costs nothing: the first
    device is inside the budget and every device after it is past it.
    """
    for label in ("iPhone", "Mac", "Android"):
        _a_device(family.bridge, label=label)
    post = posting.create_post(
        author=family.maternal,
        pod=family.maternal_pod,
        audience_yards=[family.maternal_yard],
        body="Something",
    )
    # Patched on `time` itself, not on `push.time`: strict mypy refuses to treat a
    # module's imports as its exported attributes, and `core.push` reads `time.monotonic`
    # through the same module object either way.
    ticks = iter([0.0, 0.0, push.DELIVERY_BUDGET + 1, push.DELIVERY_BUDGET + 2])
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))

    assert push.deliver_new_post(post) == 1  # the first device only
    assert len(wire.calls) == 1
    assert PushSubscription.objects.filter(member=family.bridge).count() == 3
    for skipped in PushSubscription.objects.filter(member=family.bridge):
        assert skipped.failure_count == 0, "a device that was never tried was counted against"


def test_one_session_serves_the_whole_fan_out_and_still_validates_every_request(
    family: Family, push_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One TLS handshake for a family, not one per phone — and the SSRF control unchanged.

    The endpoint is re-validated inside `PushServiceSession.request`, so reusing the
    session across devices weakens nothing: every request still passes the allowlist. This
    asserts both halves, because the cheap version of this change (share the session) is
    exactly the one that would be wrong if the validation had lived in the constructor.
    """
    for label in ("iPhone", "Mac", "Android"):
        _a_device(family.bridge, label=label)
    post = posting.create_post(
        author=family.maternal,
        pod=family.maternal_pod,
        audience_yards=[family.maternal_yard],
        body="Something",
    )
    sessions_used: list[int] = []
    validated: list[str] = []
    real_validate = push_endpoints.validate_endpoint

    def counting_validate(raw: str) -> str:
        validated.append(raw)
        return real_validate(raw)

    def fake_request(
        self: requests.Session, method: str, url: str, **kwargs: Any
    ) -> requests.Response:
        sessions_used.append(id(self))
        response = requests.Response()
        response.status_code = 201
        response.url = url
        response._content = b""
        return response

    monkeypatch.setattr(push_endpoints, "validate_endpoint", counting_validate)
    monkeypatch.setattr(requests.Session, "request", fake_request)

    assert push.deliver_new_post(post) == 3
    assert len(set(sessions_used)) == 1, "a session was built per device"
    # Twice per device: once in send_one before the call, once inside the session on the
    # request that actually goes out. The second is the one that survives a row edited at
    # a database shell.
    assert len(validated) == 6


def test_a_transport_exception_is_a_counted_failure_not_a_crash(
    family: Family, push_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A push service that refuses the connection, a DNS failure, a timeout. The task must
    never raise out: a retried job would be a second notification on a lock screen."""
    device = _a_device(family.bridge)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise requests.ConnectionError("no route")

    monkeypatch.setattr(requests.Session, "request", boom)
    assert push.send_one(device, {"title": "t", "body": "b", "url": "/", "tag": "t"}) is False
    device.refresh_from_db()
    assert device.failure_count == 1


def test_neither_the_endpoint_nor_the_service_response_reaches_a_log(
    family: Family,
    push_on: None,
    wire: Wire,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-PUSH-2. The endpoint is a capability, and `WebPushException.__str__` embeds the
    push service's whole response body — so a naive `logger.warning("%s", exc)` would put
    a third party's response text AND a live send capability into the container log.

    `propagate` is forced on for the duration: settings.LOGGING deliberately gives the
    whole `core` logger `propagate: False` so its records reach the REDACTING handler and
    nothing else (TS-EDGE-LOG), which also means caplog's root handler never sees them.
    Turning it on here reads the same records the container log would get.
    """
    monkeypatch.setattr(logging.getLogger("core"), "propagate", True)
    device = _a_device(family.bridge)
    wire.status = 500
    with caplog.at_level(logging.INFO, logger="core.push"):
        push.send_one(device, {"title": "t", "body": "b", "url": "/", "tag": "t"})
    written = "\n".join(record.getMessage() for record in caplog.records)
    assert written, "the failure was not logged at all, so this proves nothing"
    assert device.endpoint.rsplit("/", 1)[-1] not in written
    assert "a push service body nobody should log" not in written
    assert "fcm.googleapis.com" in written  # the useful half is kept


# --- the worker jobs -------------------------------------------------------------------


def test_the_job_re_resolves_live_and_a_deleted_post_sends_nothing(
    family: Family, push_on: None, wire: Wire
) -> None:
    """TS-DJ-11: the job carries an id and nothing else, so a post deleted between the
    write and the tick simply is not there."""
    from core.tasks import push_new_post_task

    _a_device(family.bridge)
    post = posting.create_post(
        author=family.maternal,
        pod=family.maternal_pod,
        audience_yards=[family.maternal_yard],
        body="Something",
    )
    post.deleted_at = timezone.now()
    post.save(update_fields=["deleted_at"])
    push_new_post_task.func(post_id=post.pk)
    assert wire.calls == []


def test_the_reply_job_re_resolves_live(family: Family, push_on: None, wire: Wire) -> None:
    from core.tasks import push_reply_task

    post = posting.create_post(
        author=family.maternal,
        pod=family.maternal_pod,
        audience_yards=[family.maternal_yard],
        body="Something",
    )
    _a_device(family.maternal)
    reply = Comment.objects.create(post=post, author=family.bridge, body="hello")
    push_reply_task.func(comment_id=reply.pk)
    assert len(wire.calls) == 1
    wire.calls.clear()
    reply.deleted_at = timezone.now()
    reply.save(update_fields=["deleted_at"])
    push_reply_task.func(comment_id=reply.pk)
    assert wire.calls == []


def test_writing_a_reply_defers_both_the_email_nudge_and_the_push(
    family: Family, push_on: None, django_capture_on_commit_callbacks: Any
) -> None:
    """Two jobs, not one: different audiences, different failure modes, and a refusing
    push service must not take the e-mail nudge down with it."""
    post = posting.create_post(
        author=family.maternal,
        pod=family.maternal_pod,
        audience_yards=[family.maternal_yard],
        body="x",
    )
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        commenting.create_comment(author=family.bridge, post=post, body="hello")
    assert len(callbacks) == 2


# --- removal ---------------------------------------------------------------------------


def test_removing_a_member_takes_their_devices_with_them(family: Family, push_on: None) -> None:
    """T-MINOR-1 arriving by a new road: without this, a removed ex keeps receiving a
    first name and the opening words of a post on their lock screen."""
    from core import removal

    _a_device(family.maternal)
    _a_device(family.maternal, label="Mac")
    _a_device(family.bridge)
    removal.remove_member(family.maternal, content=removal.KEEP)
    assert not PushSubscription.objects.filter(member=family.maternal).exists()
    assert PushSubscription.objects.filter(member=family.bridge).exists()
