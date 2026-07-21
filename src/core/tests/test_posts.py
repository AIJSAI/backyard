"""Post-audience isolation: the S-202 suite grows into the feed (wave rule 6).

The feed query (scoping.visible_posts) is the single audience-resolution path the
feed, digest, and search consume (TM-2). These tests hold it to the rule: a
member sees a post exactly when it is not deleted and either it is pod-only in a
pod they belong to, or its audience includes a yard they belong to. Cross-yard
and other-pod posts never appear; a deleted post appears to no one.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.http import Http404
from django.utils import timezone

from core import scoping
from core.models import Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db


def _member_in(pod: Pod, name: str) -> Member:
    m = Member.objects.create(display_name=name)
    PodMembership.objects.create(member=m, pod=pod)
    return m


def _post(
    author: Member, pod: Pod, yards: list[Yard], body: str = "hi", deleted: bool = False
) -> Post:
    p = Post.objects.create(
        author=author, pod=pod, body=body, deleted_at=timezone.now() if deleted else None
    )
    if yards:
        p.audience_yards.set(yards)
    return p


@dataclass
class Scene:
    maternal: Yard
    paternal: Yard
    bridge: Pod
    m_pod: Pod
    p_pod: Pod
    bridger: Member
    m_cousin: Member
    m_cousin2: Member
    p_cousin: Member


@pytest.fixture
def scene() -> Scene:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    bridge = Pod.objects.create(name="Bridge household")
    bridge.yards.set([maternal, paternal])
    m_pod = Pod.objects.create(name="Maternal cousins")
    m_pod.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal cousins")
    p_pod.yards.set([paternal])
    return Scene(
        maternal=maternal,
        paternal=paternal,
        bridge=bridge,
        m_pod=m_pod,
        p_pod=p_pod,
        bridger=_member_in(bridge, "Bridger"),
        m_cousin=_member_in(m_pod, "Maternal cousin"),
        m_cousin2=_member_in(m_pod, "Maternal cousin 2"),
        p_cousin=_member_in(p_pod, "Paternal cousin"),
    )


def _visible_ids(member: Member) -> set[int]:
    return set(scoping.visible_posts(member).values_list("id", flat=True))


def test_pod_only_post_stays_in_the_pod(scene: Scene) -> None:
    """S-204: a pod-only post reaches pod members, not a yard-mate outside the pod."""
    post = _post(scene.m_cousin, scene.m_pod, [])
    assert post.id in _visible_ids(scene.m_cousin)  # author, in the pod
    assert post.id in _visible_ids(scene.m_cousin2)  # same pod
    assert post.id not in _visible_ids(scene.bridger)  # maternal yard-mate, not in this pod


def test_yard_post_reaches_the_yard_not_the_other(scene: Scene) -> None:
    post = _post(scene.bridger, scene.bridge, [scene.maternal])
    assert post.id in _visible_ids(scene.m_cousin)  # in maternal
    assert post.id in _visible_ids(scene.bridger)  # author, in maternal
    assert post.id not in _visible_ids(scene.p_cousin)  # paternal only, never sees a maternal post


def test_bridging_post_reaches_both_yards(scene: Scene) -> None:
    post = _post(scene.bridger, scene.bridge, [scene.maternal, scene.paternal])
    assert post.id in _visible_ids(scene.m_cousin)
    assert post.id in _visible_ids(scene.p_cousin)


def test_deleted_post_reaches_no_one(scene: Scene) -> None:
    post = _post(scene.bridger, scene.bridge, [scene.maternal, scene.paternal], deleted=True)
    assert post.id not in _visible_ids(scene.m_cousin)
    assert post.id not in _visible_ids(scene.p_cousin)
    assert post.id not in _visible_ids(scene.bridger)  # not even the author


def test_cross_yard_post_fetch_404s(scene: Scene) -> None:
    paternal_post = _post(scene.p_cousin, scene.p_pod, [scene.paternal])
    with pytest.raises(Http404):
        scoping.require_visible_post(scene.m_cousin, paternal_post.id)


@dataclass
class FeedWorld:
    members: dict[str, Member]
    posts: list[Post]
    member_yards: dict[int, set[int]]
    post_pod_members: dict[int, set[int]]
    post_yards: dict[int, set[int]]
    post_deleted: dict[int, bool]


@pytest.fixture
def rich_feed(scene: Scene) -> FeedWorld:
    members = {
        "bridger": scene.bridger,
        "m_cousin": scene.m_cousin,
        "m_cousin2": scene.m_cousin2,
        "p_cousin": scene.p_cousin,
    }
    posts = [
        _post(scene.m_cousin, scene.m_pod, []),  # pod-only maternal
        _post(scene.p_cousin, scene.p_pod, []),  # pod-only paternal
        _post(scene.bridger, scene.bridge, [scene.maternal]),
        _post(scene.bridger, scene.bridge, [scene.paternal]),
        _post(scene.bridger, scene.bridge, [scene.maternal, scene.paternal]),
        _post(scene.m_cousin, scene.m_pod, [scene.maternal], deleted=True),
    ]
    return FeedWorld(
        members=members,
        posts=posts,
        member_yards={m.id: scoping.member_yard_ids(m) for m in members.values()},
        post_pod_members={
            p.id: set(PodMembership.objects.filter(pod=p.pod).values_list("member_id", flat=True))
            for p in posts
        },
        post_yards={p.id: set(p.audience_yards.values_list("id", flat=True)) for p in posts},
        post_deleted={p.id: p.deleted_at is not None for p in posts},
    )


def test_visible_posts_exactly_matches_the_audience_rule(rich_feed: FeedWorld) -> None:
    """Exhaustive: for every member and post, visible_posts returns the post iff
    the independent audience rule says so. Any cross-yard or cross-pod leak, or a
    dropped legitimate post, fails here."""
    for name, member in rich_feed.members.items():
        my_yards = rich_feed.member_yards[member.id]
        expected = set()
        for p in rich_feed.posts:
            if rich_feed.post_deleted[p.id]:
                continue
            pod_only = not rich_feed.post_yards[p.id]
            visible = (pod_only and member.id in rich_feed.post_pod_members[p.id]) or bool(
                rich_feed.post_yards[p.id] & my_yards
            )
            if visible:
                expected.add(p.id)
        actual = set(scoping.visible_posts(member).values_list("id", flat=True))
        assert actual == expected, f"{name}: feed audience mismatch"
