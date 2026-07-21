"""Reactions (S-304): who reacted, never a count; the isolation suite grows again.

A reaction inherits its post's audience through the one query (scoping.visible_
reactions over scoping.visible_posts), so the reactor list never leaks across a
yard (S-202: reactor lists are in the matrix). A member holds at most one reaction
per post; the same kind toggles off, a different kind replaces. The UI lists
reactor names and shows no tally anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core import reacting, scoping
from core.models import Member, Pod, PodMembership, Post, Reaction, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_TEST_PW = "a-Strong-passphrase-9"


def _member_with_user(pod: Pod, name: str) -> Member:
    user = User.objects.create_user(username=name.lower(), password=_TEST_PW)
    member = Member.objects.create(display_name=name, user=user)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _client_for(member: Member) -> Client:
    assert member.user is not None
    c = Client()
    c.force_login(member.user, backend=_BACKEND)
    return c


@dataclass
class World:
    maternal: Yard
    paternal: Yard
    m_pod: Pod
    p_pod: Pod
    author: Member
    m_mate: Member
    p_cousin: Member


@pytest.fixture
def world() -> World:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    m_pod = Pod.objects.create(name="Maternal cousins")
    m_pod.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal cousins")
    p_pod.yards.set([paternal])
    return World(
        maternal=maternal,
        paternal=paternal,
        m_pod=m_pod,
        p_pod=p_pod,
        author=_member_with_user(m_pod, "Author"),
        m_mate=_member_with_user(m_pod, "MMate"),
        p_cousin=_member_with_user(p_pod, "PCousin"),
    )


def _mpost(world: World) -> Post:
    post = Post.objects.create(author=world.author, pod=world.m_pod, body="a maternal post")
    post.audience_yards.set([world.maternal])
    return post


# --- isolation ---


def test_reaction_inherits_post_audience(world: World) -> None:
    post = _mpost(world)
    Reaction.objects.create(member=world.m_mate, post=post, kind=Reaction.HEART)
    m_ids = set(scoping.visible_reactions(world.author).values_list("id", flat=True))
    p_ids = set(scoping.visible_reactions(world.p_cousin).values_list("id", flat=True))
    assert m_ids  # a maternal member sees the reaction
    assert not p_ids  # a paternal member never sees who reacted on a maternal post


# --- toggle service ---


def test_toggle_creates_then_changes_then_removes(world: World) -> None:
    post = _mpost(world)
    reacting.toggle_reaction(member=world.author, post=post, kind=Reaction.HEART)
    assert Reaction.objects.get(member=world.author, post=post).kind == Reaction.HEART
    # a different kind replaces (still one row)
    reacting.toggle_reaction(member=world.author, post=post, kind=Reaction.LAUGH)
    assert Reaction.objects.get(member=world.author, post=post).kind == Reaction.LAUGH
    assert Reaction.objects.filter(member=world.author, post=post).count() == 1
    # the same kind again toggles it off
    assert reacting.toggle_reaction(member=world.author, post=post, kind=Reaction.LAUGH) is None
    assert not Reaction.objects.filter(member=world.author, post=post).exists()


def test_cannot_react_to_an_invisible_post(world: World) -> None:
    paternal_post = Post.objects.create(author=world.p_cousin, pod=world.p_pod, body="p")
    paternal_post.audience_yards.set([world.paternal])
    with pytest.raises(reacting.ReactionNotAllowed):
        reacting.toggle_reaction(member=world.author, post=paternal_post, kind=Reaction.HEART)


def test_unknown_kind_is_refused(world: World) -> None:
    post = _mpost(world)
    with pytest.raises(reacting.ReactionNotAllowed):
        reacting.toggle_reaction(member=world.author, post=post, kind="thumbsup")


# --- views ---


def test_react_view_toggles(world: World) -> None:
    post = _mpost(world)
    client = _client_for(world.m_mate)
    assert client.post(reverse("react", args=[post.id]), {"kind": "heart"}).status_code == 302
    assert Reaction.objects.filter(member=world.m_mate, post=post, kind="heart").exists()


def test_react_to_cross_yard_post_404s(world: World) -> None:
    paternal_post = Post.objects.create(author=world.p_cousin, pod=world.p_pod, body="p")
    paternal_post.audience_yards.set([world.paternal])
    assert (
        _client_for(world.author)
        .post(reverse("react", args=[paternal_post.id]), {"kind": "heart"})
        .status_code
        == 404
    )


def test_react_with_unknown_kind_404s(world: World) -> None:
    post = _mpost(world)
    assert (
        _client_for(world.author)
        .post(reverse("react", args=[post.id]), {"kind": "nope"})
        .status_code
        == 404
    )


def test_post_detail_lists_reactors_by_name_and_shows_no_count(world: World) -> None:
    post = _mpost(world)
    Reaction.objects.create(member=world.m_mate, post=post, kind=Reaction.HEART)
    body = _client_for(world.author).get(reverse("post_detail", args=[post.id])).content.decode()
    assert "MMate" in body  # who reacted, by name
    # never a tally: no "1 reaction"/"1 like"/count-style phrasing
    for banned in ("reaction", "like", "likes"):
        assert f"1 {banned}" not in body.lower()
