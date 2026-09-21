"""The four device routes, held to the rules every write route in this product has (S-107).

Login, CSRF, POST-only, schema-validated, member-scoped, bounded. Each of those is a
separate test rather than one "the route works" case, because each is a separate way in:
the IDOR tests in particular assert the SAME answer for another member's row as for a row
that never existed, which is S-202's parity rule applied to a JSON route.

`enforce_csrf_checks=True` on the clients here, deliberately. Django's test client
disables CSRF by default, so a route that forgot `@require_POST` or that was somehow
exempted would pass a whole suite silently.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core import notifications
from core.models import Member, Pod, PodMembership, PushSubscription, Yard
from core.push_views import MAX_DEVICES_PER_MEMBER, device_label
from core.tests.test_push import _a_device, a_valid_subscription_body

pytestmark = pytest.mark.django_db
User = get_user_model()
_PW = "a-Strong-passphrase-9"
_BACKEND = "django.contrib.auth.backends.ModelBackend"


@pytest.fixture
def push_on(settings: Any) -> None:
    from core.management.commands.generate_vapid_keys import generate_pair

    public, private = generate_pair()
    settings.VAPID_PUBLIC_KEY = public
    settings.VAPID_PRIVATE_KEY = private
    settings.VAPID_SUBJECT = "mailto:admin@example.test"
    settings.PUSH_ENABLED = True


def _member(name: str = "Ann Poster", *, supervised: bool = False) -> Member:
    tag = secrets.token_hex(4)
    yard, _ = Yard.objects.get_or_create(name="Maternal", slug="maternal")
    pod, _ = Pod.objects.get_or_create(name="The cousins", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = User.objects.create_user(username=f"{tag}", password=_PW)
    member = Member.objects.create(display_name=name, user=user, is_supervised=supervised)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _signed_in(member: Member) -> Client:
    """A client that ENFORCES CSRF, unlike the default test client."""
    client = Client(enforce_csrf_checks=True)
    assert member.user is not None
    client.force_login(member.user, backend=_BACKEND)
    return client


def _post(client: Client, route: str, body: dict[str, Any], *, csrf: bool = True) -> Any:
    # The CSRF cookie has to exist before the header can carry its value, which is exactly
    # what the page's own script does: it reads the token out of the form already rendered.
    client.get(reverse("notification_settings"))
    token = client.cookies["csrftoken"].value if "csrftoken" in client.cookies else ""
    # `headers=`, not the `HTTP_X_CSRFTOKEN=` extra-kwargs form: the test client's stubs
    # type the trailing keywords as its own named parameters, so a **dict of META keys
    # fails mypy on three of them at once.
    return client.post(
        reverse(route),
        data=json.dumps(body),
        content_type="application/json",
        headers={"x-csrftoken": token} if csrf else {},
    )


# --- the door ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "route", ["push_subscribe", "push_unsubscribe", "push_remove_device", "push_preferences"]
)
def test_every_route_refuses_a_stranger(route: str, push_on: None) -> None:
    assert Client().post(reverse(route)).status_code == 302  # to the sign-in page


@pytest.mark.parametrize(
    "route", ["push_subscribe", "push_unsubscribe", "push_remove_device", "push_preferences"]
)
def test_every_route_refuses_a_get(route: str, push_on: None) -> None:
    member = _member()
    assert _signed_in(member).get(reverse(route)).status_code == 405


@pytest.mark.parametrize(
    "route", ["push_subscribe", "push_unsubscribe", "push_remove_device", "push_preferences"]
)
def test_every_route_refuses_a_post_with_no_csrf_token(route: str, push_on: None) -> None:
    member = _member()
    assert _post(_signed_in(member), route, {}, csrf=False).status_code == 403


# --- subscribe ---------------------------------------------------------------------------


def test_a_member_subscribes_a_device(push_on: None) -> None:
    member = _member()
    body = a_valid_subscription_body()
    response = _post(_signed_in(member), "push_subscribe", body)
    assert response.status_code == 200
    device = PushSubscription.objects.get(member=member)
    assert device.endpoint == body["endpoint"]
    assert device.label == ""  # the test client sends no user agent


def test_the_label_is_coarse_and_never_the_whole_user_agent(push_on: None) -> None:
    """A stored user-agent string is a browser version, a device model and a
    fingerprint. The label answers "which of my two phones is this" and nothing else."""
    assert device_label("Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X)") == "iPhone"
    assert device_label("Mozilla/5.0 (Linux; Android 14; Pixel 8)") == "Android"
    assert device_label("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)") == "Mac"
    assert device_label("something nobody has heard of") == ""


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("endpoint", "https://example.com/push"),  # not a push service
        ("endpoint", "http://fcm.googleapis.com/x"),  # not https
        ("endpoint", "https://169.254.169.254/x"),  # an address, and the metadata one
        ("endpoint", ""),
        ("p256dh", "not-a-key"),
        ("auth", "!!!"),
    ],
)
def test_a_refused_subscription_writes_no_row(field: str, value: str, push_on: None) -> None:
    member = _member()
    body = a_valid_subscription_body()
    body[field] = value
    response = _post(_signed_in(member), "push_subscribe", body)
    assert response.status_code == 400
    assert not PushSubscription.objects.filter(member=member).exists()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"endpoint": 42, "p256dh": "x", "auth": "y"},  # a number where a string goes
        {"endpoint": {"a": 1}, "p256dh": "x", "auth": "y"},  # a nested object
        {"endpoint": ["https://fcm.googleapis.com/x"], "p256dh": "x", "auth": "y"},
    ],
)
def test_an_untyped_body_is_a_refusal_not_an_exception(body: dict[str, Any], push_on: None) -> None:
    """No raw dict access on untrusted input: a body of the wrong SHAPE is a 400, never an
    AttributeError in a log."""
    member = _member()
    assert _post(_signed_in(member), "push_subscribe", body).status_code == 400


def test_a_body_that_is_not_json_at_all_is_a_refusal(push_on: None) -> None:
    member = _member()
    client = _signed_in(member)
    client.get(reverse("notification_settings"))
    token = client.cookies["csrftoken"].value
    response = client.post(
        reverse("push_subscribe"),
        data=b"not json",
        content_type="application/json",
        headers={"x-csrftoken": token},
    )
    assert response.status_code == 400


def test_an_enormous_body_is_refused_before_it_is_parsed(push_on: None) -> None:
    member = _member()
    body = a_valid_subscription_body()
    body["p256dh"] = "a" * 100_000
    assert _post(_signed_in(member), "push_subscribe", body).status_code == 400


def test_a_member_is_capped_at_ten_devices(push_on: None) -> None:
    """A bound on what one account can make this server hold and POST to. It REFUSES
    rather than evicting, because evicting would silently turn a relative's other phone
    off and they would never learn why."""
    member = _member()
    for _ in range(MAX_DEVICES_PER_MEMBER):
        _a_device(member)
    response = _post(_signed_in(member), "push_subscribe", a_valid_subscription_body())
    assert response.status_code == 400
    assert PushSubscription.objects.filter(member=member).count() == MAX_DEVICES_PER_MEMBER


def test_re_subscribing_the_same_device_is_not_a_new_device(push_on: None) -> None:
    """A browser returns the same endpoint when asked twice, so opening Settings on a
    phone that is already on must not count against the cap."""
    member = _member()
    body = a_valid_subscription_body()
    client = _signed_in(member)
    assert _post(client, "push_subscribe", body).status_code == 200
    assert _post(client, "push_subscribe", body).status_code == 200
    assert PushSubscription.objects.filter(member=member).count() == 1


def test_a_phone_that_changed_hands_follows_the_new_sign_in(push_on: None) -> None:
    """One browser profile has one registration, so an existing row for this endpoint
    means this same profile was somebody else's. The row must follow the sign-in, or the
    next notification for the old member lands on a phone somebody else is holding."""
    first = _member("Ann Poster")
    second = _member("Bo Poster")
    body = a_valid_subscription_body()
    assert _post(_signed_in(first), "push_subscribe", body).status_code == 200
    assert _post(_signed_in(second), "push_subscribe", body).status_code == 200
    assert not PushSubscription.objects.filter(member=first).exists()
    assert PushSubscription.objects.filter(member=second).count() == 1


def test_a_host_typed_in_another_case_is_the_same_device(push_on: None) -> None:
    """D2: scheme and host are case-insensitive and the unique index is not, so without
    normalisation one phone reported twice is two rows — and on two members' lists, which
    is the one thing the unique constraint exists to make impossible."""
    first = _member("Ann Poster")
    second = _member("Bo Poster")
    body = a_valid_subscription_body()
    assert _post(_signed_in(first), "push_subscribe", body).status_code == 200

    shouted = dict(body)
    shouted["endpoint"] = body["endpoint"].replace("fcm.googleapis.com", "FCM.GoogleAPIs.com")
    assert _post(_signed_in(second), "push_subscribe", shouted).status_code == 200

    assert PushSubscription.objects.count() == 1
    assert PushSubscription.objects.get().member_id == second.pk
    assert PushSubscription.objects.get().endpoint == body["endpoint"]


def test_unsubscribe_normalises_before_it_filters(push_on: None) -> None:
    """The sign-out path is the one where a row left behind keeps notifying a phone
    somebody else is now holding, so a differently-cased host must still match."""
    member = _member()
    body = a_valid_subscription_body()
    assert _post(_signed_in(member), "push_subscribe", body).status_code == 200
    shouted = body["endpoint"].replace("fcm.googleapis.com", "FCM.GoogleAPIs.com")
    assert _post(_signed_in(member), "push_unsubscribe", {"endpoint": shouted}).status_code == 200
    assert not PushSubscription.objects.exists()


def test_a_supervised_account_cannot_subscribe(push_on: None) -> None:
    child = _member("A Child", supervised=True)
    response = _post(_signed_in(child), "push_subscribe", a_valid_subscription_body())
    assert response.status_code == 400
    assert not PushSubscription.objects.filter(member=child).exists()


def test_nothing_subscribes_when_the_feature_is_off(settings: Any) -> None:
    settings.PUSH_ENABLED = False
    member = _member()
    response = _post(_signed_in(member), "push_subscribe", a_valid_subscription_body())
    assert response.status_code == 400
    assert not PushSubscription.objects.filter(member=member).exists()


# --- unsubscribe and remove ---------------------------------------------------------------


def test_unsubscribe_forgets_only_this_device(push_on: None) -> None:
    member = _member()
    here = _a_device(member, label="iPhone")
    elsewhere = _a_device(member, label="Mac")
    response = _post(_signed_in(member), "push_unsubscribe", {"endpoint": here.endpoint})
    assert response.status_code == 200
    assert not PushSubscription.objects.filter(pk=here.pk).exists()
    assert PushSubscription.objects.filter(pk=elsewhere.pk).exists()


def test_unsubscribe_cannot_reach_another_members_row(push_on: None) -> None:
    """IDOR, by endpoint. Knowing somebody else's endpoint must not let you silence
    their phone."""
    mine = _member("Ann Poster")
    theirs = _member("Bo Poster")
    victim = _a_device(theirs)
    response = _post(_signed_in(mine), "push_unsubscribe", {"endpoint": victim.endpoint})
    assert response.status_code == 200  # same answer as an endpoint that is not here
    assert PushSubscription.objects.filter(pk=victim.pk).exists()


def test_remove_device_takes_one_of_my_own_rows(push_on: None) -> None:
    member = _member()
    doomed = _a_device(member)
    kept = _a_device(member, label="Mac")
    response = _post(_signed_in(member), "push_remove_device", {"id": doomed.pk})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "this_device": False}
    assert not PushSubscription.objects.filter(pk=doomed.pk).exists()
    assert PushSubscription.objects.filter(pk=kept.pk).exists()


def test_remove_device_says_when_the_row_was_this_browser_s(push_on: None) -> None:
    """How the page knows to tear the browser's own registration down, without the
    endpoint ever being rendered into the markup (T-PUSH-2)."""
    member = _member()
    device = _a_device(member)
    response = _post(
        _signed_in(member),
        "push_remove_device",
        {"id": device.pk, "endpoint": device.endpoint},
    )
    assert response.json() == {"ok": True, "this_device": True}


def test_remove_device_cannot_reach_another_members_row(push_on: None) -> None:
    """IDOR, by id, and the answer is byte-identical to an id that never existed — which
    is the same parity rule `scoping._require` holds for every read route."""
    mine = _member("Ann Poster")
    theirs = _member("Bo Poster")
    victim = _a_device(theirs)
    client = _signed_in(mine)
    refused = _post(client, "push_remove_device", {"id": victim.pk})
    never_existed = _post(client, "push_remove_device", {"id": 9_999_999})
    assert refused.status_code == never_existed.status_code == 200
    assert refused.content == never_existed.content
    assert PushSubscription.objects.filter(pk=victim.pk).exists()


@pytest.mark.parametrize("value", ["3", 0, -1, True, None, 3.5, {"pk": 3}])
def test_remove_device_refuses_an_id_that_is_not_a_positive_integer(
    value: Any, push_on: None
) -> None:
    """`True` is in this list on purpose: `isinstance(True, int)` is True in Python, so a
    JSON `true` would otherwise be read as the row with primary key 1."""
    member = _member()
    assert _post(_signed_in(member), "push_remove_device", {"id": value}).status_code == 400


# --- the two toggles ----------------------------------------------------------------------


def test_the_toggles_are_saved(push_on: None) -> None:
    member = _member()
    response = _post(_signed_in(member), "push_preferences", {"new_posts": False, "replies": True})
    assert response.status_code == 200
    preference = notifications.preference_for(member)
    assert preference.push_new_posts is False
    assert preference.push_replies is True


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"new_posts": "yes", "replies": True},  # a string, not a boolean
        {"new_posts": 1, "replies": 0},  # numbers are not booleans here
        {"new_posts": True},  # half a body
    ],
)
def test_the_toggles_refuse_anything_that_is_not_two_booleans(
    body: dict[str, Any], push_on: None
) -> None:
    member = _member()
    assert _post(_signed_in(member), "push_preferences", body).status_code == 400


def test_the_toggles_only_ever_touch_my_own_preference(push_on: None) -> None:
    mine = _member("Ann Poster")
    theirs = _member("Bo Poster")
    notifications.preference_for(theirs)
    _post(_signed_in(mine), "push_preferences", {"new_posts": False, "replies": False})
    assert notifications.preference_for(theirs).push_new_posts is True


# --- the page itself ----------------------------------------------------------------------


def test_the_page_offers_the_device_section_only_when_the_feature_is_on(push_on: None) -> None:
    member = _member()
    body = _signed_in(member).get(reverse("notification_settings")).content.decode()
    assert "Turn On Notifications" in body
    assert "On This Device" in body
    assert "Notifications are not set up on this Backyard." not in body


def test_a_supervised_account_is_shown_no_device_section(push_on: None) -> None:
    """TM-10: a child's account is parent-managed, so the control is absent rather than
    present-and-refused.

    Asserted on the MARKUP (`data-push`, the section's own hook) rather than on the button's
    words. A response carries this product's whole stylesheet, comments included, and a
    substring search for a label finds any CSS comment that happens to name it — which is
    exactly how this test first failed. Behaviour, not prose (docs/RESUME-HERE.md).
    """
    child = _member("A Child", supervised=True)
    body = _signed_in(child).get(reverse("notification_settings")).content.decode()
    assert "data-push-on" not in body
    assert "data-push=" not in body
    assert "Notifications are not set up on this Backyard." in body


def test_the_page_lists_a_device_without_ever_rendering_its_endpoint(push_on: None) -> None:
    """T-PUSH-2. The endpoint is a capability, so the row shows a coarse label and a date
    and the URL appears nowhere in the markup, view-source, or a screenshot."""
    member = _member()
    device = _a_device(member, label="iPhone")
    body = _signed_in(member).get(reverse("notification_settings")).content.decode()
    assert "Your Devices" in body
    assert "iPhone" in body
    assert device.endpoint not in body
    assert device.endpoint.rsplit("/", 1)[-1] not in body


def test_the_page_carries_the_public_key_and_not_the_private_one(
    push_on: None, settings: Any
) -> None:
    member = _member()
    body = _signed_in(member).get(reverse("notification_settings")).content.decode()
    assert settings.VAPID_PUBLIC_KEY in body
    assert settings.VAPID_PRIVATE_KEY not in body
