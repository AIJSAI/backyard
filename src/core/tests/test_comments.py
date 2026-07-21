"""Comments: the S-202 isolation suite grows to the new readable type (wave rule 6).

A comment has no audience of its own; it inherits its post's audience through the
one query (scoping.visible_comments over scoping.visible_posts). These tests hold
that line: a comment is visible exactly when its post is visible and the comment is
not deleted, so a reply on a yard the member is not in, on another member's pod, or
on a deleted post never reaches them. Create is any visible-post member; delete is
author-only. The exhaustive property closes the loop over a two-yard bridge.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.http import Http404
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import commenting, scoping
from core.models import Comment, Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
# Test-only login credential; kept out of the inline `password=` literal form.
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


def _post(author: Member, pod: Pod, yards: list[Yard], body: str = "post") -> Post:
    p = Post.objects.create(author=author, pod=pod, body=body)
    if yards:
        p.audience_yards.set(yards)
    return p


def _comment(author: Member, post: Post, body: str = "reply", deleted: bool = False) -> Comment:
    return Comment.objects.create(
        author=author, post=post, body=body, deleted_at=timezone.now() if deleted else None
    )


@dataclass
class World:
    maternal: Yard
    paternal: Yard
    m_pod: Pod
    p_pod: Pod
    bridge: Pod
    author: Member  # in m_pod
    m_mate: Member  # in m_pod
    p_cousin: Member  # in p_pod
    bridger: Member  # in bridge (both yards)


@pytest.fixture
def world() -> World:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    m_pod = Pod.objects.create(name="Maternal cousins")
    m_pod.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal cousins")
    p_pod.yards.set([paternal])
    bridge = Pod.objects.create(name="Bridge household")
    bridge.yards.set([maternal, paternal])
    return World(
        maternal=maternal,
        paternal=paternal,
        m_pod=m_pod,
        p_pod=p_pod,
        bridge=bridge,
        author=_member_with_user(m_pod, "Author"),
        m_mate=_member_with_user(m_pod, "MMate"),
        p_cousin=_member_with_user(p_pod, "PCousin"),
        bridger=_member_with_user(bridge, "Bridger"),
    )


def _visible_comment_ids(member: Member) -> set[int]:
    return set(scoping.visible_comments(member).values_list("id", flat=True))


# --- comment inherits its post's audience ---


def test_comment_on_a_pod_only_post_stays_in_the_pod(world: World) -> None:
    post = _post(world.author, world.m_pod, [])  # pod-only
    reply = _comment(world.m_mate, post)
    assert reply.id in _visible_comment_ids(world.author)  # same pod
    assert reply.id in _visible_comment_ids(world.m_mate)
    assert reply.id not in _visible_comment_ids(world.bridger)  # maternal yard, not this pod
    assert reply.id not in _visible_comment_ids(world.p_cousin)  # other yard entirely


def test_comment_on_a_yard_post_reaches_the_yard_not_the_other(world: World) -> None:
    post = _post(world.author, world.m_pod, [world.maternal])
    reply = _comment(world.author, post)
    assert reply.id in _visible_comment_ids(world.m_mate)  # maternal
    assert reply.id in _visible_comment_ids(world.bridger)  # bridge is in maternal
    assert reply.id not in _visible_comment_ids(world.p_cousin)  # paternal only


def test_deleted_comment_reaches_no_one(world: World) -> None:
    post = _post(world.author, world.m_pod, [world.maternal])
    reply = _comment(world.m_mate, post, deleted=True)
    assert reply.id not in _visible_comment_ids(world.author)
    assert reply.id not in _visible_comment_ids(world.m_mate)


def test_comment_on_a_deleted_post_reaches_no_one(world: World) -> None:
    post = _post(world.author, world.m_pod, [world.maternal])
    reply = _comment(world.m_mate, post)
    post.deleted_at = timezone.now()
    post.save(update_fields=["deleted_at"])
    assert reply.id not in _visible_comment_ids(world.author)  # post gone -> comment gone


def test_cross_yard_comment_fetch_404s(world: World) -> None:
    paternal_post = _post(world.p_cousin, world.p_pod, [world.paternal])
    reply = _comment(world.p_cousin, paternal_post)
    with pytest.raises(Http404):
        scoping.require_visible_comment(world.author, reply.id)


# --- create/delete services ---


def test_member_can_comment_on_a_visible_post(world: World) -> None:
    post = _post(world.author, world.m_pod, [world.maternal])
    reply = commenting.create_comment(author=world.bridger, post=post, body="hi from the bridge")
    assert reply.id in _visible_comment_ids(world.author)


def test_cannot_comment_on_an_invisible_post(world: World) -> None:
    paternal_post = _post(world.p_cousin, world.p_pod, [world.paternal])
    with pytest.raises(commenting.CommentNotAllowed):
        commenting.create_comment(author=world.author, post=paternal_post, body="sneaky")
    assert Comment.objects.filter(post=paternal_post).count() == 0


def test_only_the_author_may_delete_a_comment(world: World) -> None:
    post = _post(world.author, world.m_pod, [world.maternal])
    reply = _comment(world.m_mate, post)
    with pytest.raises(commenting.NotYourComment):
        commenting.delete_comment(actor=world.author, comment=reply)
    reply.refresh_from_db()
    assert reply.deleted_at is None


def test_comment_delete_is_soft_and_idempotent(world: World) -> None:
    post = _post(world.author, world.m_pod, [world.maternal])
    reply = _comment(world.m_mate, post)
    commenting.delete_comment(actor=world.m_mate, comment=reply)
    reply.refresh_from_db()
    first = reply.deleted_at
    assert first is not None
    commenting.delete_comment(actor=world.m_mate, comment=reply)
    reply.refresh_from_db()
    assert reply.deleted_at == first


# --- views ---


def test_post_detail_shows_the_thread(world: World) -> None:
    post = _post(world.author, world.m_pod, [world.maternal], body="the post")
    _comment(world.bridger, post, body="a visible reply")
    response = _client_for(world.m_mate).get(reverse("post_detail", args=[post.id]))
    assert response.status_code == 200
    body = response.content.decode()
    assert "the post" in body
    assert "a visible reply" in body


def test_cross_yard_post_detail_404s(world: World) -> None:
    paternal_post = _post(world.p_cousin, world.p_pod, [world.paternal])
    assert (
        _client_for(world.author).get(reverse("post_detail", args=[paternal_post.id])).status_code
        == 404
    )


def test_add_comment_creates_it(world: World) -> None:
    post = _post(world.author, world.m_pod, [world.maternal])
    response = _client_for(world.bridger).post(
        reverse("add_comment", args=[post.id]), {"body": "posted via http"}
    )
    assert response.status_code == 302
    assert Comment.objects.filter(post=post, body="posted via http").exists()


def test_add_comment_to_a_cross_yard_post_404s(world: World) -> None:
    paternal_post = _post(world.p_cousin, world.p_pod, [world.paternal])
    response = _client_for(world.author).post(
        reverse("add_comment", args=[paternal_post.id]), {"body": "sneaky"}
    )
    assert response.status_code == 404
    assert Comment.objects.filter(post=paternal_post).count() == 0


def test_add_comment_rejects_empty_body(world: World) -> None:
    post = _post(world.author, world.m_pod, [world.maternal])
    response = _client_for(world.author).post(reverse("add_comment", args=[post.id]), {"body": " "})
    assert response.status_code == 200
    assert Comment.objects.filter(post=post).count() == 0


def test_delete_own_comment_removes_it(world: World) -> None:
    post = _post(world.author, world.m_pod, [world.maternal])
    reply = _comment(world.bridger, post, body="regret this")
    client = _client_for(world.bridger)
    assert client.post(reverse("delete_comment", args=[reply.id])).status_code == 302
    reply.refresh_from_db()
    assert reply.deleted_at is not None
    assert "regret this" not in client.get(reverse("post_detail", args=[post.id])).content.decode()


def test_delete_someone_elses_visible_comment_is_403(world: World) -> None:
    post = _post(world.author, world.m_pod, [world.maternal])
    reply = _comment(world.bridger, post)
    assert (
        _client_for(world.m_mate).post(reverse("delete_comment", args=[reply.id])).status_code
        == 403
    )
    reply.refresh_from_db()
    assert reply.deleted_at is None


def test_delete_a_cross_yard_comment_is_404(world: World) -> None:
    paternal_post = _post(world.p_cousin, world.p_pod, [world.paternal])
    reply = _comment(world.p_cousin, paternal_post)
    assert (
        _client_for(world.author).post(reverse("delete_comment", args=[reply.id])).status_code
        == 404
    )


def test_add_comment_get_is_404(world: World) -> None:
    post = _post(world.author, world.m_pod, [world.maternal])
    assert _client_for(world.author).get(reverse("add_comment", args=[post.id])).status_code == 404


# --- exhaustive: visible_comments matches the audience rule over a bridge ---


def test_visible_comments_exactly_matches_the_rule(world: World) -> None:
    """For every member and comment, visible_comments returns it iff the comment is
    not deleted and its post is visible under an independent audience oracle. Any
    cross-yard or cross-pod comment leak, or a dropped legitimate reply, fails here."""
    members = [world.author, world.m_mate, world.p_cousin, world.bridger]
    posts = [
        _post(world.author, world.m_pod, []),  # pod-only maternal
        _post(world.author, world.m_pod, [world.maternal]),  # maternal yard
        _post(world.p_cousin, world.p_pod, [world.paternal]),  # paternal yard
        _post(world.bridger, world.bridge, [world.maternal, world.paternal]),  # bridging
        _post(world.bridger, world.bridge, []),  # pod-only in the multi-yard bridge pod
    ]
    comments = [_comment(world.bridger, posts[0], deleted=True)] + [
        _comment(world.author if i % 2 else world.p_cousin, p) for i, p in enumerate(posts)
    ]

    member_yards = {m.id: scoping.member_yard_ids(m) for m in members}
    pod_members = {
        pod.id: set(PodMembership.objects.filter(pod=pod).values_list("member_id", flat=True))
        for pod in [world.m_pod, world.p_pod, world.bridge]
    }

    def post_visible(member: Member, post: Post) -> bool:
        if post.deleted_at is not None:
            return False
        yard_ids = set(post.audience_yards.values_list("id", flat=True))
        if not yard_ids:  # pod-only: pod membership, not yard
            return member.id in pod_members[post.pod_id]
        return bool(yard_ids & member_yards[member.id])

    for member in members:
        expected = {c.id for c in comments if c.deleted_at is None and post_visible(member, c.post)}
        assert _visible_comment_ids(member) == expected, f"{member.display_name}: comment leak"
