"""Sending a web push notification (S-107): who gets one, what it says, and the send.

THE AUDIENCE RULE IS NOT RE-IMPLEMENTED HERE, and that is the single most important
thing in this module. `scoping.visible_posts` / `scoping.visible_comments` are the one
audience query (TM-2, ADR-004), and they run member -> objects. A notification needs the
inverse, and the wrong way to get it would be to write "who can see this post?" as a new
query — a second audience implementation, on the one surface that pushes a name and the
first words of a post onto a lock screen, where a mistake is unrecallable.

So this does what the digest builder already does (TM-2: "the digest builder consumes the
same audience-resolution path as the feed, per recipient"): it narrows to a small set of
CANDIDATES with cheap non-audience filters, then asks the one query once per candidate.
The candidate set is bounded by subscribed DEVICES, not by family size — a household of
eight with a phone each is eight questions, once per post.

WHY THAT CANNOT CROSS THE SIDES OF THE FAMILY. A recipient is kept only if
`scoping.visible_posts(them).filter(pk=post.pk).exists()`, which is the same statement
the feed makes when it decides whether to draw the post at all. For a REPLY the question
is asked of `scoping.visible_comments`, which additionally intersects with
`visible_members` — so on a bridging post, where both sides can see the post, somebody on
one side is never told that somebody on the other side replied, and never learns their
name. That intersection is exactly the T-YARD-4 fix already in scoping.py; asking a
weaker question here would have reopened it on a new surface.

WHAT IS EXCLUDED BEFORE THE AUDIENCE QUESTION IS ASKED: the author (nobody is told about
their own writing), supervised members (TM-10 — a child's account is parent-managed and
gets no device of its own), members whose account has been deactivated, members with the
matching toggle off, and anyone with no subscribed device. Reactions notify nothing at
all, and the arrival card notifies nothing (posting.announce_arrival passes notify=False,
which is structural rather than a string comparison on the body).

THE PAYLOAD IS TINY AND END-TO-END ENCRYPTED. Web Push encrypts it to the device's own
key (RFC 8291), so the push service sees an endpoint, a length and a time, never the
words. What it carries is a title, one line, a path and a tag; there is no photograph, no
member id and no capability in it. The TAG is what makes a busy thread bearable and the
task safely retryable: every notification about one post carries `post-<id>`, so the
device collapses them into one entry and a redelivered job replaces its own notification
rather than adding a second.
"""

from __future__ import annotations

import json
import logging
import time
from http import cookiejar
from typing import Any

import requests
from django.conf import settings
from django.db import models
from django.db.models import F
from django.utils import timezone
from py_vapid import Vapid01
from pywebpush import WebPushException, webpush

from . import push_endpoints, scoping
from .models import Comment, MediaAsset, Member, Post, PushSubscription

logger = logging.getLogger(__name__)

# One socket budget for the whole exchange with a push service. The worker runs at
# concurrency 1 (docker-compose), so a hanging service must not hold the queue: ten
# seconds is generous for a request that is one small POST and no body to read.
SEND_TIMEOUT = 10
# The budget for a WHOLE fan-out, not for one device. The worker is one process at
# concurrency 1 over every queue (docker-compose), so without this a push service that
# hangs costs SEND_TIMEOUT twice -- connect and read -- for every device in the family,
# with the transcode, digest and nightly BACKUP jobs waiting behind it. Past the budget
# the remaining devices are simply not tried: nothing is deleted and no failure is
# counted, because a slow service is not a dead one, and the next post notifies them.
DELIVERY_BUDGET = 120
# Consecutive 4xx refusals ABOUT THIS REGISTRATION before the row is dropped (see
# `_failed`: a timeout, a 429 or a 5xx is not evidence and is never counted). A push
# service that has answered 4xx for five posts in a row is either gone or has rotated the
# endpoint without telling us, and a row that never delivers is a row that only ever costs
# a request. The member's device re-subscribes on its next visit to Settings.
#
# THE READ-MODIFY-WRITE IS SAFE ONLY AT WORKER CONCURRENCY 1, which is what
# docker-compose ships. Two workers sending to one device at once would both read the same
# `failure_count` and write the same `count`, so a run would be undercounted; nothing is
# corrupted and nothing is deleted early, it just takes longer to reach the threshold. A
# deployment that raises the worker's concurrency should make this an F() expression or a
# SELECT FOR UPDATE.
MAX_CONSECUTIVE_FAILURES = 5
# 404 (gone) and 410 (expired) are the push protocol's own "this device is finished"
# answers (RFC 8030). They are not failures to count; they are a delete.
_SUBSCRIPTION_IS_GONE = (404, 410)

# The body line is cut to about this many characters, at a word boundary, and simply
# STOPS. No trailing ellipsis: the voice guide forbids the character outright, and a
# phone truncates the line again to fit its own lock screen anyway.
BODY_CHARACTERS = 80
# A body this short beside a photograph is not a caption, it is punctuation, so the media
# line says more. The real case is an empty body, which the composer allows whenever there
# is at least one file attached.
_TOO_SHORT_TO_BE_A_LINE = 3


def enabled() -> bool:
    """Whether this instance can send at all (the operator set a VAPID pair)."""
    return bool(settings.PUSH_ENABLED)


# --- what a notification says -----------------------------------------------------


def _who(member: Member) -> str:
    """The first name the family would use, falling back to the whole display name.

    `short_name` is empty for a display name that is only whitespace, and a notification
    reading " Posted" is worse than one naming somebody in full.
    """
    return member.short_name or member.display_name


def _media_line(post: Post) -> str:
    """What a post with no words of its own is about: how many photographs, or clips.

    Counted off the post's own gallery, excluding the re-hosted link-preview card image
    (S-301), which is the same distinction `scoping.visible_attached_media` draws — a card
    picture is not something anybody in this family would call a photo.
    """
    gallery = MediaAsset.objects.filter(post=post, deleted_at__isnull=True).exclude(
        media_kind=MediaAsset.LINK_PREVIEW
    )
    photos = gallery.filter(media_kind=MediaAsset.PHOTO).count()
    videos = gallery.filter(media_kind=MediaAsset.VIDEO).count()
    if photos and videos:
        return f"Shared {photos + videos} photos and videos."
    if photos:
        return "Shared a photo." if photos == 1 else f"Shared {photos} photos."
    if videos:
        return "Shared a video." if videos == 1 else f"Shared {videos} videos."
    return ""


def _first_words(body: str) -> str:
    """The opening of a post, on one line, cut at a word boundary."""
    line = " ".join(body.split())
    if len(line) <= BODY_CHARACTERS:
        return line
    cut = line[:BODY_CHARACTERS]
    spaced = cut.rsplit(" ", 1)[0]
    return spaced or cut


def post_payload(post: Post) -> dict[str, str]:
    """The notification for a new post: who wrote it, its first words, where it is."""
    body = _first_words(post.body)
    if len(body) < _TOO_SHORT_TO_BE_A_LINE:
        body = _media_line(post)
    return {
        # TITLE CASE, because a notification title is the push analogue of an e-mail
        # subject and the guide capitalises every word in one (docs/design/voice.md). The
        # product already writes "<Name> Replied To Your Post" as the reply e-mail's
        # subject; a lock-screen line is the same kind of line. The BODY below stays
        # sentence case with a full stop, like every other piece of body text here.
        "title": f"{_who(post.author)} Posted",
        "body": body,
        "url": f"/posts/{post.pk}/",
        "tag": _tag(post.pk),
    }


def reply_payload(comment: Comment) -> dict[str, str]:
    """The notification for a reply. The same tag as its post, so a busy thread
    collapses into one entry on the device instead of fifty."""
    return {
        "title": f"{_who(comment.author)} Replied",
        "body": _first_words(comment.body),
        "url": f"/posts/{comment.post_id}/",
        "tag": _tag(comment.post_id),
    }


def _tag(post_id: int) -> str:
    return f"post-{post_id}"


# --- who gets one -----------------------------------------------------------------


def _subscribed_candidates(exclude_member_id: int, *, field: str) -> models.QuerySet[Member]:
    """Members who could be notified, before the audience question is asked.

    Everything here is cheap and non-audience: it has a device, it is not the person who
    just wrote the thing, it is not a supervised child (TM-10), its account is live, and
    the matching toggle is on. A member with no NotificationPreference row has never
    opened the page, and the field defaults to True on the row `preference_for` creates —
    so `isnull=True` is the same answer as the default and is counted as on.
    """
    return (
        Member.objects.filter(pk__in=PushSubscription.objects.values("member_id"))
        .exclude(pk=exclude_member_id)
        .exclude(is_supervised=True)
        .exclude(user__is_active=False)
        .filter(
            models.Q(**{f"notification_preference__{field}": True})
            | models.Q(notification_preference__isnull=True)
        )
        .distinct()
    )


def recipients_for_post(post: Post) -> list[Member]:
    """Everyone who may see this post, minus the author — one audience query per candidate.

    Re-resolved live at send time rather than captured when the post was written
    (TS-DJ-11): a member removed, or a household moved between sides, between the compose
    and the worker picking the job up is simply not in the answer.
    """
    return [
        member
        for member in _subscribed_candidates(post.author_id, field="push_new_posts")
        if scoping.visible_posts(member).filter(pk=post.pk).exists()
    ]


def recipients_for_reply(comment: Comment) -> list[Member]:
    """The post's author and everyone who replied before, minus this replier.

    The audience question here is asked of `visible_comments`, not `visible_posts`, and
    the difference is the whole cross-side guarantee: `visible_comments` intersects with
    `visible_members`, so on a post addressed to BOTH sides of the family nobody is told
    "<name> Replied" about a person they cannot see. Getting this wrong would name one
    side of the family to the other on a lock screen.
    """
    earlier = Comment.objects.filter(post_id=comment.post_id, deleted_at__isnull=True).exclude(
        pk=comment.pk
    )
    in_the_thread = set(earlier.values_list("author_id", flat=True))
    in_the_thread.add(comment.post.author_id)
    candidates = _subscribed_candidates(comment.author_id, field="push_replies").filter(
        pk__in=in_the_thread
    )
    return [
        member
        for member in candidates
        if scoping.visible_comments(member).filter(pk=comment.pk).exists()
    ]


# --- the send ---------------------------------------------------------------------


class PushServiceSession(requests.Session):
    """The outbound side of the SSRF control, on the request that actually goes out.

    `pywebpush` hands its POST to whatever session it is given, so this is where the
    server's own rules live rather than in the library:

    * the endpoint is validated AGAIN, here, against the live allowlist. The subscribe
      route already refused anything else, but a row outlives the configuration it was
      written under — an operator who narrows BACKYARD_PUSH_SERVICE_HOSTS, or a row edited
      at a database shell, must not become an outbound request;
    * redirects are OFF. A push service answering 302 to an internal address is the
      textbook way an allowlist is walked around, and `requests` follows redirects by
      default;
    * one hard timeout, so a hanging service cannot hold the worker;
    * `trust_env` off, so no proxy environment variable and no netrc file can re-point a
      request that has just been checked against a hostname.
    """

    def __init__(self) -> None:
        super().__init__()
        self.trust_env = False
        self.max_redirects = 0
        # NO COOKIES, IN EITHER DIRECTION. One session now serves a whole fan-out, so a
        # `Set-Cookie` from a push service would otherwise be kept and replayed on the
        # next relative's device at that same host. Web Push has no use for a cookie, and
        # a session this project owns should carry nothing between two family members'
        # phones. An empty allowed-domains policy refuses to STORE one, which is the half
        # that matters: requests builds a fresh jar per request from this one
        # (`Session.prepare_request` -> `merge_cookies`) and that copy carries the default
        # policy, so a jar-level policy governs what is kept rather than what is sent --
        # measured. Nothing kept is nothing to replay.
        self.cookies.set_policy(cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    # The override is narrowed deliberately: `requests.Session.request` takes fifteen
    # keywords, and this takes the two pywebpush passes plus a kwargs bag. Mirroring the
    # library's whole parameter list here would rot against the next release and would
    # bury the three lines that matter, so the Liskov complaint is silenced by name.
    def request(  # type: ignore[override]
        self, method: str, url: str | bytes, **kwargs: Any
    ) -> requests.Response:
        push_endpoints.validate_endpoint(url if isinstance(url, str) else url.decode())
        kwargs["allow_redirects"] = False
        kwargs["timeout"] = SEND_TIMEOUT
        kwargs["proxies"] = {}
        return super().request(method, url, **kwargs)


def _vapid() -> Vapid01:
    """The signing key, rebuilt per send rather than cached.

    Deriving a P-256 key from its scalar is microseconds and a send is a network round
    trip, so a cache would buy nothing and would hold the private key in module state
    across a settings change — which tests do, and which an operator does when they rotate.
    """
    return Vapid01.from_string(private_key=settings.VAPID_PRIVATE_KEY)


def send_one(
    subscription: PushSubscription,
    payload: dict[str, str],
    *,
    session: PushServiceSession | None = None,
) -> bool:
    """Push one payload to one device. Never raises; returns whether it landed.

    THE FAILURE RULES, which are the reason this returns rather than raises:

    * 404 or 410 — the push service says this registration is finished (RFC 8030). The
      row is deleted. This is the ordinary end of a subscription's life: a browser
      rotating its endpoint, an app deleted from a home screen.
    * another 4xx — one more consecutive failure, and the row goes once there have been
      MAX_CONSECUTIVE_FAILURES of them. Cleared by the next success. 403 is the real case:
      it is what a service answers after the VAPID pair has been rotated, and it
      self-heals when the member next opens Settings.
    * NO ANSWER, a 429, or a 5xx — not counted at all, and nothing is deleted. None of
      them is evidence about THIS registration: they fail every device on that service at
      once, and counting them emptied the family's whole subscription table after five
      posts of an outage, with nobody told. `_failed` carries the measurement.
    * THE ALLOWLIST REFUSING A STORED ROW — not counted either, and not deleted, but
      logged at WARNING with its own sentence: it is the operator's configuration rather
      than anybody's network, and it is the only refusal in this list that cannot heal on
      its own.
    * the exception is never rendered into the log. `WebPushException.__str__` embeds the
      push service's RESPONSE BODY, and `webpush()` builds its message from the same
      thing — so `logger.warning("...%s", exc)` would put a third party's response text,
      and in the exception's `.response` the endpoint itself, into the container log. Only
      the status code and the redacted endpoint are ever written down.
    """
    try:
        endpoint = push_endpoints.validate_endpoint(subscription.endpoint)
        webpush(
            subscription_info={
                "endpoint": endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps(payload, separators=(",", ":")),
            vapid_private_key=_vapid(),
            # A fresh dict every call: pywebpush WRITES `aud` and `exp` into whatever it
            # is handed, so a shared one would carry the first endpoint's audience to the
            # second device and every notification after the first would be refused.
            vapid_claims={"sub": settings.VAPID_SUBJECT},
            # Seven days. A phone that was off all week still gets the notification when
            # it comes back; the tag means a week of replies is still one entry.
            ttl=7 * 24 * 60 * 60,
            timeout=SEND_TIMEOUT,
            requests_session=session or PushServiceSession(),
        )
    except push_endpoints.UnsafeEndpoint:
        # THE ALLOWLIST REFUSED A STORED ROW. Not the push service's answer and not this
        # box's network: it is configuration, and it will refuse identically on every post
        # until an operator restores the host or the member removes the device. NOT
        # counted, for the same reason a timeout is not -- deleting rows on a setting
        # somebody may have mistyped is exactly the blast radius `_failed` exists to
        # refuse -- but logged at WARNING in its own words, because this is the one refusal
        # here that never heals by itself and the only one an operator can act on.
        #
        # It catches BOTH validations: the one above, and the one inside
        # `PushServiceSession.request`. Measured: pywebpush hands its POST straight to the
        # session and wraps nothing, so the refusal raised in the session arrives here as
        # itself rather than as a WebPushException.
        logger.warning(
            "push refused before it was sent: the host is not in BACKYARD_PUSH_SERVICE_HOSTS, "
            "so this row can never be delivered to and will repeat on every post until the "
            "host is restored or the member removes the device: %s",
            push_endpoints.redact(subscription.endpoint),
        )
        return False
    except WebPushException as exc:
        return _failed(subscription, status=exc.status_code)
    except Exception:  # noqa: BLE001 - one dead device must never stop the others
        return _failed(subscription, status=None)
    PushSubscription.objects.filter(pk=subscription.pk).update(
        last_success_at=timezone.now(), failure_count=0
    )
    return True


def _failed(subscription: PushSubscription, *, status: int | None) -> bool:
    if status in _SUBSCRIPTION_IS_GONE:
        logger.info(
            "push subscription gone (%s), deleting: %s",
            status,
            push_endpoints.redact(subscription.endpoint),
        )
        PushSubscription.objects.filter(pk=subscription.pk).delete()
        return False
    if status is None or status == 429 or status >= 500:
        # NOT COUNTED. No answer at all -- a DNS failure, a dropped route, a timeout -- is
        # this box's network; a 429 is the service asking everyone to slow down; a 5xx is the
        # service's own bad day. None of them says anything about THIS registration, and each
        # fails every device at once. Counting them deletes the family's whole subscription
        # table after five posts with nobody told: measured at six devices, five posts under
        # `requests.ConnectionError`, zero rows left. Only a 4xx FROM the service is evidence
        # about a registration (a rotated VAPID pair answers 403, which still counts and
        # still self-heals).
        logger.info(
            "push was not delivered and not counted (status %s): %s",
            status,
            push_endpoints.redact(subscription.endpoint),
        )
        return False
    count = subscription.failure_count + 1
    if count >= MAX_CONSECUTIVE_FAILURES:
        logger.warning(
            "push subscription failed %s times in a row (last status %s), deleting: %s",
            count,
            status,
            push_endpoints.redact(subscription.endpoint),
        )
        PushSubscription.objects.filter(pk=subscription.pk).delete()
        return False
    logger.info(
        "push failed (status %s, %s in a row): %s",
        status,
        count,
        push_endpoints.redact(subscription.endpoint),
    )
    PushSubscription.objects.filter(pk=subscription.pk).update(failure_count=count)
    return False


def _deliver(members: list[Member], payload: dict[str, str]) -> int:
    """Push one payload to every device of every recipient, isolating each failure.

    ONE session for the whole fan-out rather than one per device: the endpoint is
    re-validated on every request (PushServiceSession.request), so the control is
    unchanged, and a family-sized send stops paying a TLS handshake per phone. It is
    closed in a `finally`: the worker is long-lived, so the pooled sockets go when the
    fan-out does rather than when the garbage collector gets round to it.
    """
    session = PushServiceSession()
    started = time.monotonic()
    delivered = 0
    try:
        # LEAST RECENTLY DELIVERED FIRST, which is the only ordering under which the
        # budget's promise ("the next post notifies them") is true. `Meta.ordering` is
        # `created_at`, so a device that hangs stays at the head of every fan-out and the
        # same tail is skipped on every post, for ever -- measured at three consecutive
        # sends reaching the same two of six devices. Ordering by `last_success_at` floats
        # the starved devices to the front of the next send, and it gives that column its
        # first reader.
        for device in PushSubscription.objects.filter(member__in=members).order_by(
            F("last_success_at").asc(nulls_first=True), "created_at"
        ):
            if time.monotonic() - started > DELIVERY_BUDGET:
                logger.warning("push: delivery budget spent; some devices were not tried")
                break
            if send_one(device, payload, session=session):
                delivered += 1
    finally:
        session.close()
    return delivered


def deliver_new_post(post: Post) -> int:
    """Notify everyone who may see this post. Returns how many devices took it."""
    if not enabled():
        return 0
    return _deliver(recipients_for_post(post), post_payload(post))


def deliver_reply(comment: Comment) -> int:
    """Notify the post's author and the earlier repliers who may see this reply."""
    if not enabled():
        return 0
    return _deliver(recipients_for_reply(comment), reply_payload(comment))
