"""#208: an arrival is ONE LINE in Email Updates, never an entry of its own.

The first real Email Update a family received had five entries and three of them were
arrival cards; in a week when a side of the family is being invited the message would be
almost nothing else. The decision: the feed keeps showing the cards exactly as it does
today, and the message names that window's joiners in one line after the posts.

What these tests hold, and why each one is here:

* The acceptance, verbatim from the issue: a week with five joins and one real post
  produces a mail whose first entry is the real post.
* A window with joins and nothing written sends NOTHING. "If nobody posted, nothing is
  sent" is what How It Works promises a family, and somebody joining is not somebody
  posting — so the days stay uncovered and those joiners are named in the next message
  that has news in it.
* The names obey the audience rule the message's posts already obey, proven on the
  bridging household: a one-side reader never learns a name from the other side.
* The line matches the reader's own cadence, reads the way a person writes a list, and
  arrives inert in the HTML part when a joiner's display name is hostile.
* An arrival is recognised by a MARK, never by its body text: a member who writes those
  words themselves is still an entry, and the card stays in the feed.
* The web copy of an issue carries the same line, from the same function.
* The 0034 backfill marks the cards a join actually wrote, and nothing else.
"""

from __future__ import annotations

import datetime
import importlib
from dataclasses import dataclass
from typing import cast

import pytest
from django.apps import apps as django_apps
from django.core import mail
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import digest, digest_links, digesting, posting, scoping
from core.digest_send import send_due_digests
from core.invites import mint_invite
from core.models import (
    DigestIssue,
    DigestSubscription,
    Member,
    Pod,
    PodMembership,
    Post,
    Yard,
)

pytestmark = pytest.mark.django_db

_PW = "aX9!mnpq2ffz"
# The five who join in the acceptance week, in the order they arrive. Fixture names this
# repository already uses; the privacy line forbids a real relative's name anywhere.
_JOINERS = ("Rose Reed", "Sam Reed", "Ada Reed", "Robin Reed", "Priya Reed")


@dataclass
class World:
    maternal: Yard
    paternal: Yard
    bridge_pod: Pod  # the household that belongs to BOTH sides
    m_pod: Pod
    p_pod: Pod
    bridge: Member
    maternal_cousin: Member
    paternal_cousin: Member
    window_start: datetime.datetime
    window_end: datetime.datetime


def _member_in(pod: Pod, name: str) -> Member:
    member = Member.objects.create(display_name=name)
    PodMembership.objects.create(member=member, pod=pod)
    return member


@pytest.fixture
def world() -> World:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    bridge_pod = Pod.objects.create(name="Bridge household")
    bridge_pod.yards.set([maternal, paternal])
    m_pod = Pod.objects.create(name="Maternal cousins")
    m_pod.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal cousins")
    p_pod.yards.set([paternal])
    window_end = timezone.now() + datetime.timedelta(hours=1)
    return World(
        maternal=maternal,
        paternal=paternal,
        bridge_pod=bridge_pod,
        m_pod=m_pod,
        p_pod=p_pod,
        bridge=_member_in(bridge_pod, "Bridge parent"),
        maternal_cousin=_member_in(m_pod, "Maternal cousin"),
        paternal_cousin=_member_in(p_pod, "Paternal cousin"),
        window_start=window_end - datetime.timedelta(days=7),
        window_end=window_end,
    )


def _issue(world: World, member: Member, yard: Yard) -> DigestIssue:
    issue, _created = DigestIssue.objects.get_or_create(
        member=member,
        yard=yard,
        window_start=world.window_start,
        defaults={"window_end": world.window_end},
    )
    return issue


def _build(world: World, member: Member, yard: Yard) -> digest.DigestEmail:
    return digest.build_digest(
        _issue(world, member, yard), digest_token="digest-raw", unsubscribe_token="unsub-raw"
    )


def _post(author: Member, pod: Pod, body: str, *, yards: list[Yard] | None = None) -> Post:
    post = Post.objects.create(author=author, pod=pod, body=body)
    if yards:
        post.audience_yards.set(yards)
    return post


def _joins(pod: Pod, name: str) -> Member:
    """Somebody arrives in a household, through the service the join transaction calls."""
    member = _member_in(pod, name)
    posting.announce_arrival(member, pod)
    return member


def _confirmed(member: Member, address: str, *, cadence: str = "weekly") -> DigestSubscription:
    digesting.subscribe(member, address=address, cadence=cadence)
    subscription = DigestSubscription.objects.get(member=member)
    subscription.confirmed_at = timezone.now() - datetime.timedelta(days=8)
    subscription.save(update_fields=["confirmed_at"])
    mail.outbox.clear()  # drop the confirmation; these tests read Email Updates only
    return subscription


# --- the acceptance ------------------------------------------------------------------


def test_five_joins_and_one_real_post_lead_with_the_real_post(world: World) -> None:
    """The issue's acceptance, word for word, on the message that would actually be sent.

    Before this, the same week produced six entries in arrival order and the one thing a
    relative would want to read was the last of them.
    """
    real = _post(world.maternal_cousin, world.m_pod, "REAL-BODY: the fence is finished.")
    for name in _JOINERS:
        _joins(world.m_pod, name)

    built = _build(world, world.maternal_cousin, world.maternal)

    entries = [block for block in built.blocks if isinstance(block, digest.PostBlock)]
    assert len(entries) == 1, [block.body for block in entries]
    assert entries[0].body == real.body
    for part, name in ((built.text, "text part"), (built.html, "HTML part")):
        assert posting.ARRIVAL_BODY not in part, f"{name} still lists the arrival cards"
        assert "REAL-BODY" in part, name
        flat = " ".join(part.split())
        assert "Joined this week: Rose, Sam, Ada, Robin and Priya." in flat, name
        assert flat.index("REAL-BODY") < flat.index("Joined this week"), (
            f"{name} puts the joined line before the post it is meant to follow"
        )


def test_no_line_at_all_when_nobody_joined(world: World) -> None:
    _post(world.maternal_cousin, world.m_pod, "A quiet week.")
    built = _build(world, world.maternal_cousin, world.maternal)
    assert not [block for block in built.blocks if isinstance(block, digest.ArrivalsBlock)]
    assert "Joined" not in built.text
    assert "Joined" not in built.html


# --- an arrival is not a post, so a window of arrivals is an empty window -------------


def test_a_window_of_nothing_but_joins_sends_nothing_and_records_nothing(world: World) -> None:
    """The rule that must keep holding on all three surfaces at once: no mail leaves, no
    issue row claims the window, and the delivery panel gains no line."""
    _confirmed(world.maternal_cousin, "cousin@example.com")
    for name in _JOINERS:
        _joins(world.m_pod, name)

    report = send_due_digests(timezone.now())

    assert report.sent == 0 and report.failed == 0 and report.crashed == 0
    assert mail.outbox == []
    assert not DigestIssue.objects.filter(member=world.maternal_cousin).exists(), (
        "a week of arrivals recorded an issue, so the next period would start after it"
    )


def test_the_joiners_of_a_silent_week_are_named_by_the_next_real_message(world: World) -> None:
    """The half that makes the skip honest rather than lossy: skipping is only correct if
    the days it skipped are still covered, and the people who arrived in them still get
    said out loud."""
    _confirmed(world.maternal_cousin, "cousin@example.com")
    _joins(world.m_pod, "Rose Reed")
    silent_run = timezone.now()
    assert send_due_digests(silent_run).sent == 0

    later = silent_run + datetime.timedelta(days=1)
    post = _post(world.maternal_cousin, world.m_pod, "LATE-BODY")
    Post.objects.filter(pk=post.pk).update(created_at=later)

    second = send_due_digests(silent_run + datetime.timedelta(days=8))

    assert second.sent == 1
    body = mail.outbox[0].body
    assert "LATE-BODY" in body
    assert "Joined this week: Rose." in " ".join(body.split()), body


# --- the audience rule, on the bridging household ------------------------------------


def test_the_joined_line_never_carries_a_name_across_the_bridge(world: World) -> None:
    """A member on one side must never learn a name from the other side through this line.

    Both sides receive somebody in the same window. The bridging parent's MATERNAL message
    may name only the arrival it can see in that yard; the other side's joiner is not in
    that slice and must not appear in any part of it, nor in the one-side reader's message.
    """
    _post(world.bridge, world.bridge_pod, "HOUSEHOLD-NOTE")
    _post(world.paternal_cousin, world.p_pod, "PATERNAL-NOTE", yards=[world.paternal])
    _joins(world.bridge_pod, "Rose Reed")  # arrives in the household that spans both sides
    _joins(world.p_pod, "Priya Reed")  # arrives on the paternal side only

    maternal = _build(world, world.bridge, world.maternal)
    for part in (maternal.text, maternal.html, maternal.subject):
        assert "Priya" not in part, "the other side's joiner crossed the bridge"
    assert "Joined this week: Rose." in " ".join(maternal.text.split())

    # The one-side reader hears about neither: they are in neither household, and an
    # arrival card is pod-scoped, so the line inherits exactly that audience.
    _post(world.maternal_cousin, world.m_pod, "COUSIN-NOTE", yards=[world.maternal])
    cousin = _build(world, world.maternal_cousin, world.maternal)
    assert "Joined" not in cousin.text
    for name in ("Rose", "Priya"):
        assert name not in cousin.text and name not in cousin.html, name

    # Non-vacuity: the paternal side's own reader DOES hear about its own arrival, so the
    # absences above are the audience rule and not a line that never renders.
    paternal = _build(world, world.paternal_cousin, world.paternal)
    assert "Joined this week: Priya." in " ".join(paternal.text.split())
    assert "Rose" not in paternal.text


def test_the_names_come_through_the_one_audience_query(world: World) -> None:
    """Belt to the braces above: the cards behind the line are the ones
    `scoping.visible_posts` returns for this member, never a second lookup of who joined."""
    joiner = _joins(world.p_pod, "Priya Reed")
    card = Post.objects.get(author=joiner)
    assert card in scoping.visible_posts(world.paternal_cousin)
    assert card not in scoping.visible_posts(world.bridge)
    assert digest_links.issue_arrival_names(_issue(world, world.bridge, world.paternal)) == ()


# --- the words ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cadence", "expected"),
    [("weekly", "Joined this week:"), ("monthly", "Joined this month:")],
)
def test_the_period_word_is_the_readers_own_cadence(
    world: World, cadence: str, expected: str
) -> None:
    _confirmed(world.maternal_cousin, "cousin@example.com", cadence=cadence)
    _joins(world.m_pod, "Rose Reed")
    _post(world.maternal_cousin, world.m_pod, "SOMETHING-HAPPENED")

    built = _build(world, world.maternal_cousin, world.maternal)

    assert expected in built.text
    assert expected in built.html


def test_a_member_with_no_subscription_reads_as_weekly(world: World) -> None:
    """The builder is also called by tests, previews and a resend before a subscription
    exists; weekly is the product's default and the fall-back `subscribe` already uses."""
    assert digesting.cadence_period_text(world.maternal_cousin) == "this week"


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (("Rose Reed",), "Joined this week: Rose."),
        (("Rose Reed", "Sam Reed"), "Joined this week: Rose and Sam."),
        (("Rose Reed", "Sam Reed", "Ada Reed"), "Joined this week: Rose, Sam and Ada."),
    ],
)
def test_the_names_read_the_way_a_person_writes_a_list(
    world: World, names: tuple[str, ...], expected: str
) -> None:
    _post(world.maternal_cousin, world.m_pod, "SOMETHING-HAPPENED")
    for name in names:
        _joins(world.m_pod, name)

    built = _build(world, world.maternal_cousin, world.maternal)

    assert expected in " ".join(built.text.split())
    assert expected in " ".join(built.html.split())


def test_one_person_who_joined_twice_is_named_once(world: World) -> None:
    """A member can hold two cards inside one window — a household and a group from two
    links — and a line naming somebody twice reads as a bug."""
    _post(world.bridge, world.bridge_pod, "SOMETHING-HAPPENED")
    joiner = _joins(world.bridge_pod, "Rose Reed")
    group = Pod.objects.create(name="The cousins", kind=Pod.ADHOC)
    group.yards.set([world.maternal])
    PodMembership.objects.create(member=joiner, pod=group)
    posting.announce_arrival(joiner, group)

    built = _build(world, world.bridge, world.maternal)

    assert "Joined this week: Rose." in " ".join(built.text.split())


def test_a_hostile_display_name_arrives_inert_in_the_html_part(world: World) -> None:
    """The line is the one place a joiner's own name reaches a reader without a byline
    around it. The text part carries it as typed (text/plain is never interpreted); the
    HTML part escapes it, like every other member-controlled string in this message."""
    _post(world.maternal_cousin, world.m_pod, "SOMETHING-HAPPENED")
    _joins(world.m_pod, '<script>alert("x")</script>')

    built = _build(world, world.maternal_cousin, world.maternal)

    assert "<script>" not in built.html
    assert "&lt;script&gt;" in built.html
    assert '<script>alert("x")</script>' in built.text


# --- the mark, not the words ----------------------------------------------------------


def test_a_member_who_writes_the_arrival_words_is_still_an_entry(world: World) -> None:
    """Proof that nothing matches on body text. A relative typing the same two words is a
    post like any other, and an arrival card edited into an introduction — which the
    fifteen-minute edit window invites — stays out of the entries."""
    typed = _post(world.maternal_cousin, world.m_pod, posting.ARRIVAL_BODY)
    joiner = _joins(world.m_pod, "Rose Reed")
    card = Post.objects.get(author=joiner)
    posting.edit_post(actor=joiner, post=card, body="Just joined. Rose's cousin from Denver.")

    built = _build(world, world.maternal_cousin, world.maternal)

    bodies = [block.body for block in built.blocks if isinstance(block, digest.PostBlock)]
    assert bodies == [typed.body]
    assert "Denver" not in built.text and "Denver" not in built.html
    assert "Joined this week: Rose." in " ".join(built.text.split())


def test_the_feed_still_shows_the_card_the_message_leaves_out(world: World) -> None:
    """End to end through the real join, which is the only writer of the mark: the card is
    in the joiner's feed exactly as before, and out of the message."""
    _post(world.maternal_cousin, world.m_pod, "SOMETHING-HAPPENED")
    _, raw = mint_invite(world.m_pod, None)
    client = Client()
    response = client.post(
        reverse("join", args=[raw]),
        {"display_name": "Cousin Reed", "username": "cousinreed", "password": _PW},
    )
    assert response.status_code == 302, response.status_code
    joiner = Member.objects.get(display_name="Cousin Reed")
    assert Post.objects.get(author=joiner).is_arrival is True

    feed = client.get(reverse("feed"))
    assert feed.status_code == 200
    assert posting.ARRIVAL_BODY in feed.content.decode(), "the feed stopped showing arrivals"

    built = _build(world, joiner, world.maternal)
    assert posting.ARRIVAL_BODY not in built.text
    assert "Joined this week: Cousin." in " ".join(built.text.split())


# --- the web copy of an issue ---------------------------------------------------------


def test_the_web_copy_carries_the_same_line(world: World) -> None:
    """The signed-out copy of one message at /d/ says what the message said. It is also
    where the mark's second effect shows: an arrival card is not an entry on the page and
    its deep link is not part of the issue, so nothing there links to one."""
    _post(world.maternal_cousin, world.m_pod, "REAL-BODY")
    joiner = _joins(world.m_pod, "Rose Reed")
    card = Post.objects.get(author=joiner)
    issue = _issue(world, world.maternal_cousin, world.maternal)
    token = digest_links.mint(issue)

    page = Client().get(f"/d/{token}/")

    assert page.status_code == 200
    html = page.content.decode()
    assert "Joined this week: Rose." in " ".join(html.split())
    assert "REAL-BODY" in html
    assert posting.ARRIVAL_BODY not in html
    assert Client().get(f"/d/{token}/posts/{card.id}/").status_code == 404


# --- the 0034 backfill ----------------------------------------------------------------


def test_the_backfill_marks_the_cards_a_join_wrote_and_nothing_else(world: World) -> None:
    """The migration identifies a historical card by PROVENANCE — the redemption row the
    same transaction wrote — never by its body.

    Driven on rows the real join path produced, with the mark cleared to stand them back
    up as they were before 0034: that is the only honest fixture for a backfill, because
    anything hand-built is a guess about what the old code wrote.
    """
    backfill = importlib.import_module("core.migrations.0034_an_arrival_card_says_so")
    _, raw = mint_invite(world.m_pod, None)
    Client().post(
        reverse("join", args=[raw]),
        {"display_name": "Cousin Reed", "username": "cousinreed", "password": _PW},
    )
    joiner = Member.objects.get(display_name="Cousin Reed")
    card = Post.objects.get(author=joiner)
    # What they wrote themselves, minutes later, with the same body: the row the backfill
    # must leave alone however closely it resembles a card.
    later = _post(joiner, world.m_pod, posting.ARRIVAL_BODY)
    Post.objects.filter(pk=later.pk).update(
        created_at=timezone.now() + datetime.timedelta(minutes=5)
    )
    Post.objects.all().update(is_arrival=False)  # the state on disk before the migration

    # schema_editor is unused by the backfill; a data migration gets the live one in CI.
    backfill._mark_the_cards_a_join_wrote(django_apps, cast(BaseDatabaseSchemaEditor, None))

    assert Post.objects.get(pk=card.pk).is_arrival is True
    assert Post.objects.get(pk=later.pk).is_arrival is False
