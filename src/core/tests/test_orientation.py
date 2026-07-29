"""S-906: what the arriving person sees.

Found by walking a delegate's onboarding: someone completes the join and lands on
`/feed/` with a composer and other people's posts and no orientation whatsoever. At the
founder's scale — two relatives onboarding roughly ten people — that gets explained by
voice ten times.

Distinct from S-905, which tells the FAMILY that someone arrived. This is the other
direction.

The acceptance has two halves and the second is the one that can rot quietly:
"dismissible and never returns; not a notification and not a tour".
"""

from __future__ import annotations

import datetime

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse

from core.invites import mint_invite
from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db

_PW = "aX9!mnpq2ffz"


@pytest.fixture
def pod() -> Pod:
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds")
    pod.yards.set([yard])
    return pod


def _join(pod: Pod) -> tuple[Client, Member]:
    _, raw = mint_invite(pod, None)
    client = Client()
    response = client.post(
        reverse("join", args=[raw]),
        {"display_name": "Cousin Reed", "username": "cousinreed", "password": _PW},
    )
    assert response.status_code == 302
    return client, Member.objects.get(display_name="Cousin Reed")


def test_a_newcomers_first_feed_says_where_they_are(pod: Pod) -> None:
    client, _ = _join(pod)
    html = client.get(reverse("feed")).content.decode()
    assert 'class="orientation"' in html
    assert "Mom&#x27;s side" in html or "Mom's side" in html, "it does not name their side"
    assert "your household only" in html, "it does not say who sees what they post"
    assert "unless you turn it on" in html, "it does not say nothing is pushed at them"


def test_it_survives_navigating_away_and_back(pod: Pod) -> None:
    """The reason this is a stored flag rather than a first-render check.

    `feed_last_seen_at` advances on the first feed render, so an orientation keyed to
    it would disappear the moment a newcomer tapped Pods and came back — before they
    had read it. Loading the feed twice must not consume it.
    """
    client, _ = _join(pod)
    client.get(reverse("feed"))
    client.get(reverse("pod_list"))
    assert 'class="orientation"' in client.get(reverse("feed")).content.decode()


def test_dismissing_it_makes_it_never_return(pod: Pod) -> None:
    client, member = _join(pod)
    assert client.post(reverse("dismiss_orientation")).status_code == 302
    member.refresh_from_db()
    assert member.orientation_dismissed_at is not None
    assert 'class="orientation"' not in client.get(reverse("feed")).content.decode()


def test_dismissing_twice_keeps_the_first_moment(pod: Pod) -> None:
    """The column is a record of when they said they were oriented, so a second POST
    (a double tap, a refresh of the redirect) must not rewrite it."""
    client, member = _join(pod)
    client.post(reverse("dismiss_orientation"))
    member.refresh_from_db()
    first = member.orientation_dismissed_at
    client.post(reverse("dismiss_orientation"))
    member.refresh_from_db()
    assert member.orientation_dismissed_at == first


def test_a_GET_cannot_dismiss_it(pod: Pod) -> None:
    """A prefetch or a link preview must not clear the one thing a newcomer has not
    read yet — the same class of mistake the compose-cancel route already guards."""
    client, member = _join(pod)
    assert client.get(reverse("dismiss_orientation")).status_code == 405
    member.refresh_from_db()
    assert member.orientation_dismissed_at is None


def test_it_is_not_a_notification(pod: Pod) -> None:
    mail.outbox.clear()
    client, _ = _join(pod)
    client.get(reverse("feed"))
    assert mail.outbox == [], [m.subject for m in mail.outbox]


def test_it_never_appears_for_members_who_predate_it(pod: Pod) -> None:
    """The migration stamps everyone alive at deploy time, so the whole family does not
    open their feed to a "you're in" block the morning after a release. Simulated here
    the way the migration leaves them: dismissed at some past moment."""
    from django.utils import timezone

    existing = Member.objects.create(
        display_name="Long-standing", orientation_dismissed_at=timezone.now()
    )
    PodMembership.objects.create(member=existing, pod=pod)
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(username="longstanding", password=_PW)
    existing.user = user
    existing.save(update_fields=["user"])

    client = Client()
    client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
    assert 'class="orientation"' not in client.get(reverse("feed")).content.decode()


def test_the_migration_really_stamps_existing_members(pod: Pod) -> None:
    """Call the migration's OWN backfill, not a hand-made stand-in for it.

    The test above proves a stamped member sees nothing; this proves the thing that
    does the stamping works. Without it, a backfill that silently matched no rows
    would leave the whole family staring at an orientation block, and every other
    test here would still be green.
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
    from django.utils import timezone

    migration = importlib.import_module("core.migrations.0022_member_orientation_dismissed_at")
    moment = timezone.now() - datetime.timedelta(days=30)
    already = Member.objects.create(
        display_name="Dismissed ages ago", orientation_dismissed_at=moment
    )
    PodMembership.objects.create(member=already, pod=pod)

    migration.stamp_existing_members(real_apps, None)

    already.refresh_from_db()
    assert already.orientation_dismissed_at == moment


def test_the_heading_reads_as_a_sentence_with_one_side_and_with_two(pod: Pod) -> None:
    """Caught by looking at the rendered page, not by a test: the first cut put a comma
    before the list of sides, so a member on one side read "You're in, Mom's side."

    Both arities, because the separator logic is the kind that is right for one case
    and wrong for the other.
    """
    client, member = _join(pod)
    one = client.get(reverse("feed")).content.decode()
    heading = one[one.index('id="orientation-heading"') : one.index("</h2>")]
    flat = " ".join(heading.split())
    assert "in, " not in flat, f"stray comma before a single side: {flat}"
    assert "Mom&#x27;s side" in flat or "Mom's side" in flat

    other = Yard.objects.create(name="Dad's side", slug="dads-side")
    bridge = Pod.objects.create(name="A bridging household")
    bridge.yards.set([other])
    PodMembership.objects.create(member=member, pod=bridge)
    Member.objects.filter(pk=member.pk).update(orientation_dismissed_at=None)

    two = client.get(reverse("feed")).content.decode()
    heading = two[two.index('id="orientation-heading"') : two.index("</h2>")]
    flat = " ".join(heading.split())
    assert "in, " not in flat, f"stray comma before a list of sides: {flat}"
    assert " and " in flat, f"two sides must read as a list: {flat}"
