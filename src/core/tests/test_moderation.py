"""Single-item moderation takedown (S-713).

Properties under test: a yard/instance admin can take down one post or comment they can
SEE (soft-deleted so the one audience query treats it as gone everywhere, recorded with
moderated_by, media purged for a post); the takedown is scoped to the moderator's own
visibility, so a post or comment the admin cannot see is a byte-identical 404 — even for
the instance admin, whose content visibility is membership-scoped like everyone's (the
reach-vs-visibility rule); a plain member cannot take down anyone's content (403, distinct
from the author-only self-delete); it is POST-only; it is idempotent and never overwrites
the record of an author self-delete; and the affordance renders only for admins.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core import scoping
from core.models import Comment, Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_PW = "a-Strong-passphrase-9"
_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _member(pod: Pod, name: str, role: str = Member.MEMBER) -> Member:
    user = User.objects.create_user(username=name.lower(), password=_PW)
    member = Member.objects.create(display_name=name, user=user, role=role)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _client_for(member: Member) -> Client:
    assert member.user is not None
    c = Client()
    c.force_login(member.user, backend=_BACKEND)
    return c


def _yard_post(author: Member, pod: Pod, yard: Yard, body: str) -> Post:
    post = Post.objects.create(author=author, pod=pod, body=body)
    post.audience_yards.set([yard])
    return post


@dataclass
class World:
    maternal: Yard
    paternal: Yard
    m_pod: Pod
    p_pod: Pod
    instance_admin: Member  # maternal only
    m_admin: Member  # yard admin, maternal
    author: Member  # ordinary member, maternal
    plain: Member  # ordinary member, maternal
    p_author: Member  # ordinary member, paternal
    m_post: Post  # a maternal-yard post
    p_post: Post  # a paternal-yard post
    m_comment: Comment  # a comment on the maternal post


@pytest.fixture
def world() -> World:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    m_pod = Pod.objects.create(name="Maternal cousins")
    m_pod.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal cousins")
    p_pod.yards.set([paternal])
    author = _member(m_pod, "Author")
    p_author = _member(p_pod, "PaternalAuthor")
    m_post = _yard_post(author, m_pod, maternal, "MATERNAL post body")
    p_post = _yard_post(p_author, p_pod, paternal, "PATERNAL post body")
    m_comment = Comment.objects.create(author=author, post=m_post, body="a maternal reply")
    return World(
        maternal=maternal,
        paternal=paternal,
        m_pod=m_pod,
        p_pod=p_pod,
        instance_admin=_member(m_pod, "Boss", role=Member.INSTANCE_ADMIN),
        m_admin=_member(m_pod, "MaternalMod", role=Member.YARD_ADMIN),
        author=author,
        plain=_member(m_pod, "Cousin"),
        p_author=p_author,
        m_post=m_post,
        p_post=p_post,
        m_comment=m_comment,
    )


def test_admin_takes_down_a_visible_post(world: World) -> None:
    resp = _client_for(world.m_admin).post(reverse("take_down_post", args=[world.m_post.id]))
    assert resp.status_code == 302  # back to the feed
    world.m_post.refresh_from_db()
    assert world.m_post.deleted_at is not None  # soft-deleted, gone from the one query
    assert world.m_post.moderated_by_id == world.m_admin.id  # accountability recorded
    # It is gone for everyone, through the single audience query.
    assert not scoping.visible_posts(world.plain).filter(id=world.m_post.id).exists()


def test_admin_takes_down_a_visible_comment(world: World) -> None:
    resp = _client_for(world.m_admin).post(reverse("take_down_comment", args=[world.m_comment.id]))
    assert resp.status_code == 302
    world.m_comment.refresh_from_db()
    assert world.m_comment.deleted_at is not None
    assert world.m_comment.moderated_by_id == world.m_admin.id
    assert not scoping.visible_comments(world.author).filter(id=world.m_comment.id).exists()


def test_takedown_of_a_post_the_admin_cannot_see_404s(world: World) -> None:
    """The reach-vs-visibility rule: a maternal admin cannot take down a paternal-yard
    post they do not belong to — it is a byte-identical 404, the same as a post that does
    not exist, and nothing is removed."""
    resp = _client_for(world.m_admin).post(reverse("take_down_post", args=[world.p_post.id]))
    assert resp.status_code == 404
    world.p_post.refresh_from_db()
    assert world.p_post.deleted_at is None  # untouched


def test_the_instance_admin_is_also_visibility_scoped(world: World) -> None:
    """Even the instance admin's CONTENT visibility is membership-scoped (unlike their
    instance-wide power over members): the founder, a member of maternal only, cannot take
    down a paternal post they cannot see."""
    resp = _client_for(world.instance_admin).post(reverse("take_down_post", args=[world.p_post.id]))
    assert resp.status_code == 404
    world.p_post.refresh_from_db()
    assert world.p_post.deleted_at is None


def test_a_plain_member_cannot_take_down(world: World) -> None:
    """A plain member gets 403 even on content they can see: takedown is an admin lever,
    distinct from the author-only self-delete."""
    client = _client_for(world.plain)
    assert client.post(reverse("take_down_post", args=[world.m_post.id])).status_code == 403
    assert client.post(reverse("take_down_comment", args=[world.m_comment.id])).status_code == 403
    world.m_post.refresh_from_db()
    assert world.m_post.deleted_at is None


def test_takedown_is_post_only(world: World) -> None:
    client = _client_for(world.m_admin)
    assert client.get(reverse("take_down_post", args=[world.m_post.id])).status_code == 404
    assert client.get(reverse("take_down_comment", args=[world.m_comment.id])).status_code == 404
    world.m_post.refresh_from_db()
    assert world.m_post.deleted_at is None  # a GET never removes


def test_takedown_is_idempotent_and_preserves_an_author_self_delete(world: World) -> None:
    """An author self-delete leaves moderated_by null; a later takedown of the already-
    deleted post is a no-op and does NOT stamp a moderator over it, so the two remain
    distinguishable. A double takedown keeps the first moderator's record."""
    from core import posting

    posting.delete_post(actor=world.author, post=world.m_post)  # author self-delete
    _client_for(world.m_admin).post(reverse("take_down_post", args=[world.m_post.id]))
    world.m_post.refresh_from_db()
    assert world.m_post.moderated_by_id is None  # author-delete record intact

    # A fresh post, taken down twice: the first moderator stands.
    other = _yard_post(world.author, world.m_pod, world.maternal, "second post")
    _client_for(world.m_admin).post(reverse("take_down_post", args=[other.id]))
    _client_for(world.instance_admin).post(reverse("take_down_post", args=[other.id]))
    other.refresh_from_db()
    assert other.moderated_by_id == world.m_admin.id  # not overwritten by the second


def test_the_feed_offers_takedown_to_admins_only(world: World) -> None:
    admin_feed = _client_for(world.m_admin).get(reverse("feed")).content.decode()
    assert reverse("take_down_post", args=[world.m_post.id]) in admin_feed
    plain_feed = _client_for(world.plain).get(reverse("feed")).content.decode()
    assert reverse("take_down_post", args=[world.m_post.id]) not in plain_feed


def test_the_thread_offers_takedown_to_admins_only(world: World) -> None:
    admin_thread = (
        _client_for(world.m_admin).get(reverse("post_detail", args=[world.m_post.id]))
    ).content.decode()
    assert reverse("take_down_post", args=[world.m_post.id]) in admin_thread
    assert reverse("take_down_comment", args=[world.m_comment.id]) in admin_thread
    plain_thread = (
        _client_for(world.plain).get(reverse("post_detail", args=[world.m_post.id]))
    ).content.decode()
    assert reverse("take_down_comment", args=[world.m_comment.id]) not in plain_thread
