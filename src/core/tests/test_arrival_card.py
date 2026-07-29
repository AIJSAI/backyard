"""S-905: a quiet intro card when someone joins.

The gap was found by walking a delegate's onboarding end to end rather than by a
test: a household is invited, relatives join over a week, and nothing anywhere says
any of them arrived — the people already in the pod never learn a cousin is now
reachable.

Every assertion here is on the acceptance text, not on the implementation:
"joining generates a POD-SCOPED profile card post; NO notification, NO yard-wide
broadcast". The two negatives are the ones worth testing, because a card that
quietly went yard-wide would look identical on the joiner's own feed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse

from core import scoping
from core.invites import mint_invite
from core.models import Member, Pod, PodMembership, Post, Yard
from core.posting import ARRIVAL_BODY

pytestmark = pytest.mark.django_db

_PW = "aX9!mnpq2ffz"


@dataclass
class World:
    pod: Pod  # the household being joined
    sitting: Member  # already in that pod
    neighbour: Member  # same side of the family, DIFFERENT household
    elsewhere: Member  # the other side entirely


@pytest.fixture
def world() -> World:
    """Two sides of the family. `sitting` is already in the pod being joined;
    `neighbour` is on the same side but a different household; `elsewhere` is on the
    other side entirely. The middle one is the interesting case."""
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    pod = Pod.objects.create(name="The Reeds")
    pod.yards.set([maternal])
    other_pod = Pod.objects.create(name="The Ferraras")
    other_pod.yards.set([paternal])
    # A second household on the SAME side: in the yard, but not in the joined pod.
    same_yard_pod = Pod.objects.create(name="Nana's house")
    same_yard_pod.yards.set([maternal])

    sitting = Member.objects.create(display_name="Already Here")
    PodMembership.objects.create(member=sitting, pod=pod)
    neighbour = Member.objects.create(display_name="Same Side, Other House")
    PodMembership.objects.create(member=neighbour, pod=same_yard_pod)
    elsewhere = Member.objects.create(display_name="Other Side")
    PodMembership.objects.create(member=elsewhere, pod=other_pod)
    return World(pod=pod, sitting=sitting, neighbour=neighbour, elsewhere=elsewhere)


def _join(pod: Pod, *, username: str = "cousinreed", name: str = "Cousin Reed") -> Member:
    _, raw = mint_invite(pod, None)
    response = Client().post(
        reverse("join", args=[raw]),
        {"display_name": name, "username": username, "password": _PW},
    )
    assert response.status_code == 302, response.status_code
    return Member.objects.get(display_name=name)


def test_joining_posts_an_arrival_card_into_the_pod(world: World) -> None:
    joiner = _join(world.pod)
    card = Post.objects.get(author=joiner)
    assert card.pod_id == world.pod.id
    assert card.body == ARRIVAL_BODY
    # The byline already carries the name, so the body must not repeat it.
    assert joiner.display_name not in card.body


def test_the_card_is_pod_scoped_and_never_a_yard_wide_broadcast(
    world: World,
) -> None:
    """The half that would look correct on the joiner's own feed either way.

    A card that quietly carried a yard audience would render identically to the
    person who just joined, and would put "someone joined" in front of every
    household on that side of the family — a broadcast this product does not have.
    """
    joiner = _join(world.pod)
    card = Post.objects.get(author=joiner)
    assert list(card.audience_yards.all()) == [], "the arrival card went yard-wide"

    # Read it the way the app reads it, through the one audience query.
    assert card in scoping.visible_posts(world.sitting)
    assert card not in scoping.visible_posts(world.neighbour), (
        "a household on the same side, not in the pod, can see the arrival card"
    )
    assert card not in scoping.visible_posts(world.elsewhere)


def test_joining_pushes_nothing_at_anybody(world: World) -> None:
    """ "Without a fanfare" is the story's actual requirement. S-305's reply opt-in
    only fires on comments, so a post cannot notify — pin that it stays true, since
    a future "someone joined your pod" email is exactly the sort of helpful addition
    that would violate the story while looking like an improvement."""
    mail.outbox.clear()
    _join(world.pod)
    assert mail.outbox == [], [m.subject for m in mail.outbox]


def test_the_card_is_the_only_post_the_join_creates(world: World) -> None:
    # Guard against a duplicate card if the join path is ever refactored to call
    # the service twice (once in the view, once in the service layer).
    joiner = _join(world.pod)
    assert Post.objects.filter(author=joiner).count() == 1


def test_a_failed_join_leaves_no_orphan_card(world: World) -> None:
    """The card lives inside the account-creation transaction, so a join that fails
    on a taken username must leave neither a member nor a card behind."""
    _join(world.pod, username="taken", name="First Cousin")
    before = Post.objects.count()

    _, raw = mint_invite(world.pod, None)
    response = Client().post(
        reverse("join", args=[raw]),
        {"display_name": "Second Cousin", "username": "taken", "password": _PW},
    )
    assert response.status_code == 200  # re-rendered with an error, not a redirect
    assert "already taken" in response.content.decode()
    assert Post.objects.count() == before, "a card survived a rolled-back join"
    assert not Member.objects.filter(display_name="Second Cousin").exists()
