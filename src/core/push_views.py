"""The four routes behind Settings > Notifications > On This Device (S-107).

All four are POST-only, login-required, CSRF-enforced and member-scoped, and all four
take JSON. JSON because the whole section is driven from the page's own script — iOS only
grants notification permission from inside a user gesture, so there is no no-JavaScript
version of "tap this and the phone asks you", and inventing form posts for half of it
would leave two shapes for one section. CSRF still applies exactly as it does to a form:
the script reads the token out of the `{% csrf_token %}` input already on the page and
sends it as `X-CSRFToken`, which is the header Django's own middleware checks.

NOTHING HERE READS AN UNTRUSTED DICT DIRECTLY. Every field goes through `_string` or
`_flag`, which check presence, type and length before a value is used, so a body of
`{"endpoint": {"__proto__": ...}}`, a list where a string was expected, or a megabyte of
JSON is a 400 and never an AttributeError in a log. The endpoint and the two keys then go
through `core/push_endpoints.py`, which is where the SSRF refusals live.

MEMBER SCOPE IS THE FILTER, NOT A CHECK AFTER THE FACT: every query here starts from
`member=member`, so removing a device by id that belongs to somebody else resolves
nothing and answers the same 404 as an id that never existed (S-202's parity rule applied
to a JSON route). There is no branch in which one member's row is fetched and then
rejected, because that branch is where an IDOR usually survives review.
"""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_POST

from . import notifications, push_endpoints
from .models import Member, PushSubscription

# One member, ten devices. A family member has a phone, maybe a tablet and a laptop; ten
# is far above that and is a bound on what one account can make this server hold and POST
# to. It REFUSES rather than evicting the oldest, because evicting would silently turn a
# relative's other phone off and they would never learn why — the Settings page lists
# every device with a Remove button beside it, so the member can act, and rows for
# endpoints a browser has rotated away from delete themselves at the next send (a push
# service answers 404 or 410 for them).
MAX_DEVICES_PER_MEMBER = 10
# A body larger than this is not a subscription. Read before parsing.
MAX_BODY_BYTES = 4096


class BadRequest(ValueError):
    """The request body is not the shape this route takes."""


def _member(request: HttpRequest) -> Member:
    """The signed-in member, or a 404 for a user with no member row.

    The same shape as `feed_views._acting_member`: a `User` created at a shell has no
    Member, and these routes answer that with the product's ordinary 404 rather than a
    500 out of a reverse one-to-one.
    """
    if not request.user.is_authenticated or request.user.pk is None:
        raise Http404
    member = Member.objects.filter(user_id=request.user.pk).first()
    if member is None:
        raise Http404
    return member


def _body(request: HttpRequest) -> dict[str, Any]:
    if len(request.body) > MAX_BODY_BYTES:
        raise BadRequest("That request is too large.")
    try:
        parsed = json.loads(request.body or b"{}")
    except ValueError as exc:
        raise BadRequest("That request was not understood.") from exc
    if not isinstance(parsed, dict):
        raise BadRequest("That request was not understood.")
    return parsed


def _string(data: dict[str, Any], key: str, *, max_length: int) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise BadRequest("That request was not understood.")
    return value.strip()


def _flag(data: dict[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise BadRequest("That request was not understood.")
    return value


def _refused(message: str) -> JsonResponse:
    """A refusal a person can read. It never names an internal, and never echoes back
    the value it refused — an error page that quotes a capability URL is a capability
    URL in a screenshot."""
    return JsonResponse({"ok": False, "message": message}, status=400)


def device_label(user_agent: str) -> str:
    """A coarse name for the device in the member's own Remove list.

    Deliberately one word from a fixed set. The job is "which of my two phones is this",
    not identification: a stored user-agent string is a fingerprint, a browser version and
    a per-device identifier all at once, and none of that belongs in a family's database
    for the sake of a label. An agent that matches nothing is left blank and the page says
    the date instead.
    """
    agent = user_agent or ""
    for needle, label in (
        ("iPhone", "iPhone"),
        ("iPad", "iPad"),
        ("Android", "Android"),
        ("Macintosh", "Mac"),
        ("Mac OS X", "Mac"),
        ("Windows", "Windows"),
        ("CrOS", "Chromebook"),
        ("Linux", "Linux"),
    ):
        if needle in agent:
            return label
    return ""


@login_required
@require_POST
def subscribe(request: HttpRequest) -> HttpResponse:
    """Store one device's push subscription for the signed-in member.

    The endpoint is client-supplied and this server will POST to it, so it is validated
    here before it is ever written (core/push_endpoints.py) and again on the outbound
    request itself (core/push.py). Both, because the row outlives the configuration it was
    written under.

    An endpoint that already exists is REASSIGNED to the requesting member rather than
    refused. It is unique instance-wide because a browser profile has exactly one
    registration, so an existing row for this endpoint means this same browser profile was
    somebody else's — the family tablet somebody else signed in on. The row must follow
    the sign-in, or the next notification for the old member lands on a phone that is now
    in somebody else's hands.
    """
    member = _member(request)
    if not settings.PUSH_ENABLED:
        return _refused("Notifications are not set up on this Backyard.")
    if member.is_supervised:
        return _refused("This account cannot turn on notifications.")
    try:
        data = _body(request)
        endpoint = push_endpoints.validate_endpoint(
            _string(data, "endpoint", max_length=push_endpoints.MAX_ENDPOINT_LENGTH)
        )
        p256dh = push_endpoints.validate_p256dh(
            _string(data, "p256dh", max_length=push_endpoints.MAX_P256DH_LENGTH)
        )
        auth = push_endpoints.validate_auth(
            _string(data, "auth", max_length=push_endpoints.MAX_AUTH_LENGTH)
        )
    except (BadRequest, push_endpoints.UnsafeEndpoint) as exc:
        return _refused(str(exc))

    mine = PushSubscription.objects.filter(member=member)
    if not mine.filter(endpoint=endpoint).exists() and mine.count() >= MAX_DEVICES_PER_MEMBER:
        return _refused("Remove a device below before adding another.")

    # Delete-then-create rather than update_or_create: `created_at` should say when THIS
    # member added THIS device, and a reassigned row carrying somebody else's date would
    # be the one piece of another member's history visible on this page.
    PushSubscription.objects.filter(endpoint=endpoint).delete()
    PushSubscription.objects.create(
        member=member,
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth,
        label=device_label(request.META.get("HTTP_USER_AGENT", "")),
    )
    return JsonResponse({"ok": True})


@login_required
@require_POST
def unsubscribe(request: HttpRequest) -> HttpResponse:
    """Forget the device this request came from. Idempotent, and scoped to the member.

    Used by Turn Off Notifications On This Device and by the sign-out page, which is why
    it takes the endpoint rather than a row id: at sign-out the page knows what the
    browser holds, not which row it is, and the whole point is that the next person
    holding the phone is not notified about this family.

    Never REFUSED on the allowlist, deliberately. This only ever DELETES, and an endpoint
    that would fail validation is precisely a row that should go. It is still normalised
    the same way `subscribe` normalises, because a stored row carries the normalised form
    and a browser that reports its endpoint with a differently-cased host would otherwise
    match nothing and leave the row behind — on the sign-out path, which is the one where
    a leftover row keeps notifying somebody else's phone. A value that cannot be
    normalised at all is deleted as typed, which is the same best-effort answer as before.
    """
    member = _member(request)
    try:
        endpoint = _string(
            _body(request), "endpoint", max_length=push_endpoints.MAX_ENDPOINT_LENGTH
        )
    except BadRequest as exc:
        return _refused(str(exc))
    try:
        endpoint = push_endpoints.validate_endpoint(endpoint)
    except push_endpoints.UnsafeEndpoint:
        pass  # delete whatever was stored under the raw value instead
    PushSubscription.objects.filter(member=member, endpoint=endpoint).delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def remove_device(request: HttpRequest) -> HttpResponse:
    """Remove one of the member's own devices from the list, by row id.

    Scoped in the FILTER (`member=member`), so another member's id deletes nothing and
    answers exactly as an id that does not exist. There is no fetch-then-check branch here
    for the same reason there is none in `scoping._require`.

    `this_device` in the answer is how the page knows to tear the browser's OWN
    registration down as well. The alternative was rendering each row's endpoint into the
    settings page so the script could compare them itself, and an endpoint is a capability
    (push_endpoints.redact says why) — it does not belong in a page's markup, a
    screenshot, or view-source. The client sends the endpoint it holds, the server answers
    one boolean, and the capability stays where it already was.
    """
    member = _member(request)
    try:
        data = _body(request)
        raw = data.get("id")
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
            raise BadRequest("That request was not understood.")
        here = data.get("endpoint")
        if here is not None and (
            not isinstance(here, str) or len(here) > push_endpoints.MAX_ENDPOINT_LENGTH
        ):
            raise BadRequest("That request was not understood.")
    except BadRequest as exc:
        return _refused(str(exc))
    doomed = PushSubscription.objects.filter(member=member, pk=raw).first()
    if doomed is None:
        return JsonResponse({"ok": True, "this_device": False})
    this_device = bool(here) and doomed.endpoint == here
    doomed.delete()
    return JsonResponse({"ok": True, "this_device": this_device})


@login_required
@require_POST
def preferences(request: HttpRequest) -> HttpResponse:
    """Set the two web-push toggles: New Posts and Replies."""
    member = _member(request)
    try:
        data = _body(request)
        new_posts = _flag(data, "new_posts")
        replies = _flag(data, "replies")
    except BadRequest as exc:
        return _refused(str(exc))
    preference = notifications.preference_for(member)
    preference.push_new_posts = new_posts
    preference.push_replies = replies
    preference.save(update_fields=["push_new_posts", "push_replies"])
    return JsonResponse({"ok": True})
