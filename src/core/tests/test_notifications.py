"""Notification preferences (S-305): a negative guarantee, held by asserting absence.

Default push is zero for every event type; the only opt-in that exists is replies to
my own posts; there is no all-activity firehose. These tests fail if that promise
ever erodes, in particular if the preference model grows a second push option.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.db import models
from django.test import Client
from django.urls import reverse

from core import notifications
from core.models import Member, NotificationPreference, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_TEST_PW = "a-Strong-passphrase-9"


@pytest.fixture
def member() -> Member:
    yard = Yard.objects.create(name="Y", slug="y")
    pod = Pod.objects.create(name="P")
    pod.yards.set([yard])
    user = User.objects.create_user(username="m", password=_TEST_PW)
    m = Member.objects.create(display_name="M", user=user)
    PodMembership.objects.create(member=m, pod=pod)
    return m


def _client_for(member: Member) -> Client:
    assert member.user is not None
    c = Client()
    c.force_login(member.user, backend=_BACKEND)
    return c


def test_default_is_zero_push(member: Member) -> None:
    pref = notifications.preference_for(member)
    assert pref.notify_on_reply is False  # nothing is pushed unless explicitly enabled


def test_reply_optin_can_be_toggled(member: Member) -> None:
    notifications.set_reply_notification(member, enabled=True)
    assert notifications.preference_for(member).notify_on_reply is True
    notifications.set_reply_notification(member, enabled=False)
    assert notifications.preference_for(member).notify_on_reply is False


def test_the_preference_model_grows_no_firehose() -> None:
    """The negative guarantee as a drift guard, in the shape S-107 left it.

    It used to read `== {"notify_on_reply"}` and the name of the test was "the only push
    optin is reply". The PROMISE was never "one field" — it was that Backyard pushes
    nobody anything they did not switch on, and that there is no all-activity stream. Web
    push adds two event types, both of which are inert until the member has deliberately
    subscribed a device from Settings, and the set is pinned EXACTLY so a third one cannot
    arrive quietly. The two names that must never appear are the firehose shapes.
    """
    boolean_optins = {
        field.name
        for field in NotificationPreference._meta.get_fields()
        if isinstance(field, models.BooleanField)
    }
    assert boolean_optins == {"notify_on_reply", "push_new_posts", "push_replies"}
    # Reactions are the easiest firehose to grow and the product deliberately has none:
    # S-304 shows who reacted and never a count, and nothing anywhere pushes a "liked".
    assert not any("reaction" in name or "activity" in name for name in boolean_optins)


def test_web_push_defaults_on_once_a_device_is_subscribed() -> None:
    """The two push toggles default TRUE while the e-mail one defaults FALSE, and that is
    not an inconsistency: subscribing a device IS the opt-in for the push pair, and
    landing a member in Settings with both halves off would make them turn notifications
    on twice. With no subscription row they mean nothing at all."""
    pref = NotificationPreference()
    assert pref.notify_on_reply is False
    assert pref.push_new_posts is True
    assert pref.push_replies is True


def test_settings_page_offers_only_the_reply_optin(member: Member) -> None:
    """With no VAPID pair configured — which is every self-hoster who has not generated
    one, and the default in this suite — the page is exactly what it always was."""
    body = _client_for(member).get(reverse("notification_settings")).content.decode()
    assert 'name="notify_on_reply"' in body  # the one opt-in is present
    # structural drift guard: exactly one opt-in control, so no firehose toggle exists
    assert body.count('type="checkbox"') == 1
    assert "Notifications are not set up on this Backyard." in body


def test_settings_post_enables_then_disables(member: Member) -> None:
    client = _client_for(member)
    assert (
        client.post(reverse("notification_settings"), {"notify_on_reply": "on"}).status_code == 302
    )
    assert notifications.preference_for(member).notify_on_reply is True
    assert client.post(reverse("notification_settings"), {}).status_code == 302  # unchecked
    assert notifications.preference_for(member).notify_on_reply is False


def test_anonymous_is_redirected_from_settings() -> None:
    assert Client().get(reverse("notification_settings")).status_code == 302
