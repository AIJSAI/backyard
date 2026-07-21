"""Post lifecycle (S-302) and the unread boundary (S-303).

Edit and delete are author-only and resolved through the guard, so a post the
member cannot see is a 404 and a post they can see but did not write is a 403.
Edit is time-boxed to the window; delete is a soft delete always available. The
feed draws one unread boundary between what is new since the last visit and what
was already seen, and opening the feed advances that marker.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import posting
from core.models import Member, Pod, PodMembership, Post, Yard

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


def _post(author: Member, pod: Pod, *, body: str = "hello", minutes_ago: int = 0) -> Post:
    post = Post.objects.create(author=author, pod=pod, body=body)
    if minutes_ago:
        aged = timezone.now() - timedelta(minutes=minutes_ago)
        Post.objects.filter(id=post.id).update(created_at=aged)
        post.refresh_from_db()
    return post


@pytest.fixture
def world() -> dict[str, object]:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    m_pod = Pod.objects.create(name="Maternal cousins")
    m_pod.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal cousins")
    p_pod.yards.set([paternal])
    return {
        "m_pod": m_pod,
        "p_pod": p_pod,
        "author": _member_with_user(m_pod, "Author"),
        "pod_mate": _member_with_user(m_pod, "PodMate"),
        "other": _member_with_user(p_pod, "Other"),
    }


# --- service: edit/delete authorization and the window ---


def test_author_edits_within_the_window(world: dict[str, object]) -> None:
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    post = _post(author, m_pod, body="typo hre")
    posting.edit_post(actor=author, post=post, body="typo here")
    post.refresh_from_db()
    assert post.body == "typo here"
    assert post.edited_at is not None


def test_edit_is_refused_after_the_window(world: dict[str, object]) -> None:
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    post = _post(author, m_pod, minutes_ago=16)
    with pytest.raises(posting.EditWindowClosed):
        posting.edit_post(actor=author, post=post, body="too late")


def test_only_the_author_may_edit(world: dict[str, object]) -> None:
    author = world["author"]
    pod_mate = world["pod_mate"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(pod_mate, Member)
    assert isinstance(m_pod, Pod)
    post = _post(author, m_pod, body="mine")
    with pytest.raises(posting.NotYourPost):
        posting.edit_post(actor=pod_mate, post=post, body="hijacked")


def test_only_the_author_may_delete(world: dict[str, object]) -> None:
    author = world["author"]
    pod_mate = world["pod_mate"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(pod_mate, Member)
    assert isinstance(m_pod, Pod)
    post = _post(author, m_pod)
    with pytest.raises(posting.NotYourPost):
        posting.delete_post(actor=pod_mate, post=post)


def test_editing_a_deleted_post_is_refused(world: dict[str, object]) -> None:
    """Defense in depth (security review LOW-2): the service refuses to edit a
    deleted post even though the view already 404s one through the guard."""
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    post = _post(author, m_pod)
    posting.delete_post(actor=author, post=post)
    post.refresh_from_db()
    with pytest.raises(PermissionDenied):
        posting.edit_post(actor=author, post=post, body="back from the dead")


def test_delete_is_soft_and_idempotent(world: dict[str, object]) -> None:
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    post = _post(author, m_pod)
    posting.delete_post(actor=author, post=post)
    post.refresh_from_db()
    first = post.deleted_at
    assert first is not None
    posting.delete_post(actor=author, post=post)  # second call is a no-op, not an error
    post.refresh_from_db()
    assert post.deleted_at == first


# --- views: edit/delete over real requests ---


def test_edit_own_post_updates_it(world: dict[str, object]) -> None:
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    post = _post(author, m_pod, body="before")
    response = _client_for(author).post(reverse("edit_post", args=[post.id]), {"body": "after"})
    assert response.status_code == 302
    post.refresh_from_db()
    assert post.body == "after"
    assert post.edited_at is not None


def test_edit_after_window_is_403(world: dict[str, object]) -> None:
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    post = _post(author, m_pod, minutes_ago=16)
    assert _client_for(author).get(reverse("edit_post", args=[post.id])).status_code == 403


def test_edit_someone_elses_visible_post_is_403(world: dict[str, object]) -> None:
    author = world["author"]
    pod_mate = world["pod_mate"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(pod_mate, Member)
    assert isinstance(m_pod, Pod)
    post = _post(author, m_pod, body="mine")
    response = _client_for(pod_mate).post(
        reverse("edit_post", args=[post.id]), {"body": "hijacked"}
    )
    assert response.status_code == 403
    post.refresh_from_db()
    assert post.body == "mine"


def test_edit_a_cross_yard_post_is_404(world: dict[str, object]) -> None:
    author = world["author"]
    other = world["other"]
    p_pod = world["p_pod"]
    assert isinstance(author, Member)
    assert isinstance(other, Member)
    assert isinstance(p_pod, Pod)
    post = _post(other, p_pod, body="paternal")
    assert _client_for(author).get(reverse("edit_post", args=[post.id])).status_code == 404


def test_delete_own_post_removes_it_from_the_feed(world: dict[str, object]) -> None:
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    post = _post(author, m_pod, body="regrettable")
    client = _client_for(author)
    assert client.post(reverse("delete_post", args=[post.id])).status_code == 302
    post.refresh_from_db()
    assert post.deleted_at is not None
    assert "regrettable" not in client.get(reverse("feed")).content.decode()


def test_delete_confirm_states_digests_cannot_be_recalled(world: dict[str, object]) -> None:
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    post = _post(author, m_pod)
    response = _client_for(author).get(reverse("delete_post", args=[post.id]))
    assert response.status_code == 200
    assert "cannot be recalled" in response.content.decode()


def test_delete_someone_elses_visible_post_is_403(world: dict[str, object]) -> None:
    author = world["author"]
    pod_mate = world["pod_mate"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(pod_mate, Member)
    assert isinstance(m_pod, Pod)
    post = _post(author, m_pod)
    assert _client_for(pod_mate).post(reverse("delete_post", args=[post.id])).status_code == 403
    post.refresh_from_db()
    assert post.deleted_at is None


def test_delete_a_cross_yard_post_is_404(world: dict[str, object]) -> None:
    author = world["author"]
    other = world["other"]
    p_pod = world["p_pod"]
    assert isinstance(author, Member)
    assert isinstance(other, Member)
    assert isinstance(p_pod, Pod)
    post = _post(other, p_pod)
    assert _client_for(author).post(reverse("delete_post", args=[post.id])).status_code == 404
    post.refresh_from_db()
    assert post.deleted_at is None


# --- the unread boundary ---


def test_first_visit_sets_the_last_seen_marker(world: dict[str, object]) -> None:
    author = world["author"]
    assert isinstance(author, Member)
    assert author.feed_last_seen_at is None
    assert _client_for(author).get(reverse("feed")).status_code == 200
    author.refresh_from_db()
    assert author.feed_last_seen_at is not None


def test_boundary_falls_between_new_and_already_seen(world: dict[str, object]) -> None:
    author = world["author"]
    pod_mate = world["pod_mate"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(pod_mate, Member)
    assert isinstance(m_pod, Pod)
    _post(pod_mate, m_pod, body="an older update", minutes_ago=5)

    client = _client_for(author)
    first = client.get(reverse("feed")).content.decode()
    assert "New since your last visit" not in first  # nothing was new on the first visit

    author.refresh_from_db()
    assert author.feed_last_seen_at is not None
    fresh = Post.objects.create(author=pod_mate, pod=m_pod, body="a brand new update")
    Post.objects.filter(id=fresh.id).update(
        created_at=author.feed_last_seen_at + timedelta(seconds=1)
    )

    body = client.get(reverse("feed")).content.decode()
    assert "New since your last visit" in body
    # Newest first: the new post, then the boundary, then the already-seen post.
    assert body.index("a brand new update") < body.index("New since your last visit")
    assert body.index("New since your last visit") < body.index("an older update")
