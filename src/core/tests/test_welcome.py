"""The welcome, shown once, right after joining (owner direction 7, replacing S-906).

What this replaces: a green card at the top of the feed that named which sides of the
family you were in. It filled a phone screen before anyone had seen a photograph, and in
all that room it never said what this place IS, never offered the Family email, and never
helped with a first post — the three things a relative actually needs on day one.

The acceptance has four halves and three of them can rot quietly:
  * joining LANDS on it (not on the feed with an explanation stapled to the top);
  * every screen is skippable, and skipping leaves a complete, working member;
  * it is SEEN ONCE — the family already here never meets it;
  * the Family email offered there is the real opt-in, so the address still has to be
    confirmed before any family content goes to it.
"""

from __future__ import annotations

import datetime

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core.invites import mint_invite
from core.models import DigestSubscription, Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db

_PW = "aX9!mnpq2ffz"
_BACKEND = "django.contrib.auth.backends.ModelBackend"
User = get_user_model()


@pytest.fixture
def pod() -> Pod:
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds")
    pod.yards.set([yard])
    return pod


def _join(pod: Pod, *, email: str = "") -> tuple[Client, Member]:
    _, raw = mint_invite(pod, None)
    client = Client()
    form = {"display_name": "Cousin Reed", "username": "cousinreed", "password": _PW}
    if email:
        form["email"] = email
    response = client.post(reverse("join", args=[raw]), form)
    assert response.status_code == 302, response.status_code
    return client, Member.objects.get(display_name="Cousin Reed")


# --- landing on it ------------------------------------------------------------------


def test_joining_lands_on_the_welcome(pod: Pod) -> None:
    """The whole point of the change: the first screen after the join form is the one
    that says what this place is, not a feed with an explanation stapled to the top."""
    _, raw = mint_invite(pod, None)
    client = Client()
    response = client.post(
        reverse("join", args=[raw]),
        {"display_name": "Cousin Reed", "username": "cousinreed", "password": _PW},
    )
    assert response.headers["Location"] == reverse("welcome")


def test_the_first_screen_says_what_this_is_in_plain_words(pod: Pod) -> None:
    client, _ = _join(pod)
    body = client.get(reverse("welcome")).content.decode()
    assert "private place for our family" in body
    assert "No ads, no strangers" in body
    assert "goes to your household" in body
    # The vocabulary itself is held by test_one_word_per_concept.py, over every
    # template's visible text; repeating a weaker version of it here would only give
    # two places to weaken.


def test_the_three_screens_are_reachable_in_order(pod: Pod) -> None:
    client, _ = _join(pod)
    one = client.get(reverse("welcome")).content.decode()
    assert reverse("welcome_family_email") in one

    two = client.get(reverse("welcome_family_email"))
    assert two.status_code == 200
    assert "Want a family email?" in two.content.decode()

    three = client.get(reverse("welcome_hello"))
    assert three.status_code == 200
    assert "Say hello" in three.content.decode()


# --- skipping -----------------------------------------------------------------------


def test_skipping_leaves_a_complete_member_standing_in_the_feed(pod: Pod) -> None:
    """Skippable at every step has to mean the account is finished, not half-made."""
    client, member = _join(pod)
    response = client.post(reverse("welcome_skip"))
    assert response.headers["Location"] == reverse("feed")
    assert client.get(reverse("feed")).status_code == 200
    member.refresh_from_db()
    assert member.orientation_dismissed_at is not None


def test_a_get_cannot_skip_the_welcome(pod: Pod) -> None:
    """A link prefetch or a mail scanner must not put away the one thing a newcomer has
    not read yet — the same rule the dismissals in this product already follow."""
    client, member = _join(pod)
    assert client.get(reverse("welcome_skip")).status_code == 405
    member.refresh_from_db()
    assert member.orientation_dismissed_at is None


def test_skipping_twice_keeps_the_first_moment(pod: Pod) -> None:
    client, member = _join(pod)
    client.post(reverse("welcome_skip"))
    member.refresh_from_db()
    first = member.orientation_dismissed_at
    client.post(reverse("welcome_skip"))
    member.refresh_from_db()
    assert member.orientation_dismissed_at == first


def test_reaching_the_last_screen_marks_it_seen(pod: Pod) -> None:
    """They have now had all three in front of them, which is what the column claims.

    Deliberately NOT stamped on arrival at screen one: a refresh would then bounce them
    to the feed halfway through the first sentence.
    """
    client, member = _join(pod)
    client.get(reverse("welcome"))
    member.refresh_from_db()
    assert member.orientation_dismissed_at is None, "screen one must not consume it"

    client.get(reverse("welcome_hello"))
    member.refresh_from_db()
    assert member.orientation_dismissed_at is not None


# --- the Family email, screen two ----------------------------------------------------


def test_the_address_is_already_filled_in_from_the_join_form(pod: Pod) -> None:
    client, _ = _join(pod, email="cousin@example.com")
    body = client.get(reverse("welcome_family_email")).content.decode()
    assert 'value="cousin@example.com"' in body, "they had to type it again"


def test_choosing_weekly_enrolls_and_still_confirms_the_address(pod: Pod) -> None:
    """The welcome is not a second enrolment path: it goes through the ordinary opt-in,
    so the address gets its one content-free confirmation and nothing from the family
    flows until it is acknowledged (T-EMAIL-6)."""
    client, member = _join(pod, email="cousin@example.com")
    mail.outbox.clear()

    response = client.post(
        reverse("welcome_family_email"),
        {"choice": "weekly", "address": "cousin@example.com"},
    )
    assert response.headers["Location"] == reverse("welcome_hello")

    subscription = DigestSubscription.objects.get(member=member)
    assert subscription.cadence == DigestSubscription.WEEKLY
    assert subscription.confirmed_at is None, "family content would flow unconfirmed"
    assert len(mail.outbox) == 1
    assert mail.outbox[0].subject == "Is this your email address?"
    assert mail.outbox[0].to == ["cousin@example.com"]


def test_choosing_monthly_is_offered_and_daily_is_not(pod: Pod) -> None:
    """Owner direction 2: weekly and monthly only. Daily stays valid in the model for
    anyone who already has it and is offered nowhere."""
    client, member = _join(pod, email="cousin@example.com")
    body = client.get(reverse("welcome_family_email")).content.decode()
    assert 'value="monthly"' in body
    assert 'value="daily"' not in body
    assert "Daily" not in body

    client.post(
        reverse("welcome_family_email"),
        {"choice": "monthly", "address": "cousin@example.com"},
    )
    assert DigestSubscription.objects.get(member=member).cadence == DigestSubscription.MONTHLY


def test_no_thanks_writes_nothing_and_sends_nothing(pod: Pod) -> None:
    """ "Final and never asked again" (owner direction 7b): no row, no mail, and nothing
    anywhere that will raise it a second time."""
    client, member = _join(pod, email="cousin@example.com")
    mail.outbox.clear()

    response = client.post(reverse("welcome_family_email"), {"choice": "no"})
    assert response.headers["Location"] == reverse("welcome_hello")
    assert not DigestSubscription.objects.filter(member=member).exists()
    assert mail.outbox == []


def test_a_bad_address_is_refused_rather_than_enrolled(pod: Pod) -> None:
    client, member = _join(pod)
    response = client.post(
        reverse("welcome_family_email"), {"choice": "weekly", "address": "not-an-address"}
    )
    assert response.status_code == 200
    assert "does not look like an email address" in response.content.decode()
    assert not DigestSubscription.objects.filter(member=member).exists()
    assert mail.outbox == []


def test_a_submission_with_no_choice_asks_again(pod: Pod) -> None:
    """Neither a cadence nor a refusal is a half-submitted form, and guessing which
    answer somebody meant about their own inbox is not an option."""
    client, member = _join(pod, email="cousin@example.com")
    response = client.post(reverse("welcome_family_email"), {"address": "cousin@example.com"})
    assert response.status_code == 200
    assert "Choose how often" in response.content.decode()
    assert not DigestSubscription.objects.filter(member=member).exists()


# --- say hello, screen three ---------------------------------------------------------


def test_the_last_screen_offers_a_composer_with_a_line_already_written(pod: Pod) -> None:
    client, _ = _join(pod)
    body = client.get(reverse("welcome_hello")).content.decode()
    assert reverse("compose") in body
    assert "I just joined" in body, "an empty required box on their first minute here"
    assert 'type="file"' in body, "no way to add a photo"


def test_posting_from_the_welcome_really_posts(pod: Pod) -> None:
    """It submits to the ordinary compose endpoint, so there is one way to write a post
    in this product and one place the audience rule lives."""
    client, member = _join(pod)
    client.get(reverse("welcome_hello"))
    response = client.post(
        reverse("compose"), {"body": "Hi everyone, I just joined.", "pod_id": pod.id}
    )
    assert response.headers["Location"] == reverse("feed")
    assert Post.objects.filter(author=member, body="Hi everyone, I just joined.").exists()


def test_the_welcome_is_never_a_notification(pod: Pod) -> None:
    mail.outbox.clear()
    client, _ = _join(pod)
    client.get(reverse("welcome"))
    client.get(reverse("welcome_hello"))
    assert mail.outbox == [], [m.subject for m in mail.outbox]


# --- the family already here ---------------------------------------------------------


def test_the_feed_no_longer_carries_the_orientation_card(pod: Pod) -> None:
    """The card is gone from the feed entirely, for everyone, seen or not. Asserted on
    the rendered feed of a member who has NOT been through the welcome, which is the
    only state that could still produce it."""
    client, member = _join(pod)
    Member.objects.filter(pk=member.pk).update(orientation_dismissed_at=None)
    body = client.get(reverse("feed")).content.decode()
    assert 'class="orientation"' not in body
    assert "You&rsquo;re in" not in body and "You’re in" not in body


def test_an_existing_member_is_never_sent_to_the_welcome(pod: Pod) -> None:
    """Signing in lands where it always did. The welcome is reached from the join
    redirect and from nowhere else, so nothing can route the family back into it."""
    existing = Member.objects.create(
        display_name="Long-standing", orientation_dismissed_at=timezone.now()
    )
    PodMembership.objects.create(member=existing, pod=pod)
    user = User.objects.create_user(username="longstanding", password=_PW)
    existing.user = user
    existing.save(update_fields=["user"])

    client = Client()
    client.force_login(user, backend=_BACKEND)
    feed = client.get(reverse("feed"))
    assert feed.status_code == 200
    assert reverse("welcome") not in feed.content.decode()


def test_the_migration_really_stamps_existing_members(pod: Pod) -> None:
    """Call the migration's OWN backfill, not a hand-made stand-in for it.

    `orientation_dismissed_at` is now the seen-the-welcome marker, so this backfill is
    what keeps the family already here out of a flow written for newcomers. A backfill
    that silently matched no rows would put every one of them through it.
    """
    import importlib

    from django.apps import apps as real_apps

    migration = importlib.import_module("core.migrations.0022_member_orientation_dismissed_at")

    unstamped = Member.objects.create(display_name="Predates the feature")
    PodMembership.objects.create(member=unstamped, pod=pod)
    assert unstamped.orientation_dismissed_at is None

    migration.stamp_existing_members(real_apps, None)

    unstamped.refresh_from_db()
    assert unstamped.orientation_dismissed_at is not None, "the backfill matched nothing"


def test_the_backfill_does_not_re_stamp_someone_who_already_dismissed(pod: Pod) -> None:
    """It filters on isnull=True, so re-running the migration (a squash, a replay on a
    restored database) must not rewrite an existing moment."""
    import importlib

    from django.apps import apps as real_apps

    migration = importlib.import_module("core.migrations.0022_member_orientation_dismissed_at")
    moment = timezone.now() - datetime.timedelta(days=30)
    already = Member.objects.create(
        display_name="Dismissed ages ago", orientation_dismissed_at=moment
    )
    PodMembership.objects.create(member=already, pod=pod)

    migration.stamp_existing_members(real_apps, None)

    already.refresh_from_db()
    assert already.orientation_dismissed_at == moment
