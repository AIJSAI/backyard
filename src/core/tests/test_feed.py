"""Feed and composer view tests (S-000, S-302, S-303, S-203).

Proves on real requests: the feed shows exactly a member's visible posts and ends;
the composer creates a pod-only post by default; TM-3 confirm-on-widen intercepts a
yard send and names the audience and its member count before it goes; and the view
cannot be tricked into posting to a pod or yard the author is not in (the audience
integrity invariant, enforced at the view boundary and again in the service).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core.models import Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
# Test-only login credential; not a real secret (kept out of the inline
# `password=` literal form so the secret-scan pre-commit hook stays meaningful).
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


@pytest.fixture
def world() -> dict[str, object]:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    m_pod = Pod.objects.create(name="Maternal cousins")
    m_pod.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal cousins")
    p_pod.yards.set([paternal])
    return {
        "maternal": maternal,
        "paternal": paternal,
        "m_pod": m_pod,
        "p_pod": p_pod,
        "author": _member_with_user(m_pod, "Author"),
        "pod_mate": _member_with_user(m_pod, "PodMate"),
        "other": _member_with_user(p_pod, "Other"),
    }


def test_anonymous_is_redirected_from_the_feed(world: dict[str, object]) -> None:
    assert Client().get(reverse("feed")).status_code == 302


def test_feed_shows_only_visible_posts_and_ends(world: dict[str, object]) -> None:
    author = world["author"]
    other = world["other"]
    m_pod = world["m_pod"]
    p_pod = world["p_pod"]
    paternal = world["paternal"]
    assert isinstance(author, Member)
    assert isinstance(other, Member)
    assert isinstance(m_pod, Pod)
    assert isinstance(p_pod, Pod)
    assert isinstance(paternal, Yard)

    mine = Post.objects.create(author=author, pod=m_pod, body="a maternal update")
    theirs = Post.objects.create(author=other, pod=p_pod, body="a paternal secret")
    theirs.audience_yards.set([paternal])

    response = _client_for(author).get(reverse("feed"))
    assert response.status_code == 200
    ids = {p.id for p in response.context["posts"]}
    assert mine.id in ids
    assert theirs.id not in ids  # cross-yard post never appears
    body = response.content.decode()
    assert "a maternal update" in body
    assert "a paternal secret" not in body
    assert "You are all caught up." in body  # the feed ends (S-303)


def test_empty_feed_shows_the_empty_state(world: dict[str, object]) -> None:
    author = world["author"]
    assert isinstance(author, Member)
    response = _client_for(author).get(reverse("feed"))
    assert "Nothing here yet" in response.content.decode()


def test_compose_creates_a_pod_only_post_by_default(world: dict[str, object]) -> None:
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    response = _client_for(author).post(
        reverse("compose"), {"body": "just the pod", "pod_id": m_pod.id}
    )
    assert response.status_code == 302
    post = Post.objects.get(body="just the pod")
    assert post.pod_id == m_pod.id
    assert post.author_id == author.id
    assert list(post.audience_yards.all()) == []  # narrowest default (TM-3)


def test_compose_to_a_yard_asks_to_confirm_first(world: dict[str, object]) -> None:
    """TM-3: widening past the pod stops for an explicit confirmation that names the
    audience and how many people it reaches, and writes nothing yet."""
    author = world["author"]
    m_pod = world["m_pod"]
    maternal = world["maternal"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    assert isinstance(maternal, Yard)
    response = _client_for(author).post(
        reverse("compose"),
        {"body": "hello whole side", "pod_id": m_pod.id, "audience_yards": [maternal.id]},
    )
    assert response.status_code == 200
    assert response.templates[0].name == "core/compose_confirm.html"
    assert response.context["member_count"] == 2  # author + pod mate, both in Maternal
    assert "Maternal" in response.content.decode()
    assert not Post.objects.filter(body="hello whole side").exists()  # nothing written yet


def test_compose_to_a_yard_writes_after_confirmation(world: dict[str, object]) -> None:
    author = world["author"]
    m_pod = world["m_pod"]
    maternal = world["maternal"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    assert isinstance(maternal, Yard)
    response = _client_for(author).post(
        reverse("compose"),
        {
            "body": "confirmed wide",
            "pod_id": m_pod.id,
            "audience_yards": [maternal.id],
            "confirm_wide": "yes",
        },
    )
    assert response.status_code == 302
    post = Post.objects.get(body="confirmed wide")
    assert set(post.audience_yards.values_list("id", flat=True)) == {maternal.id}


def test_compose_drops_a_foreign_yard_id_rather_than_leaking(world: dict[str, object]) -> None:
    """A hand-built POST naming a yard the author is not in must not publish there.
    The view filters to the author's visible yards, so the foreign id falls away and
    the post lands pod-only (safe), never in the foreign yard."""
    author = world["author"]
    m_pod = world["m_pod"]
    paternal = world["paternal"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    assert isinstance(paternal, Yard)
    response = _client_for(author).post(
        reverse("compose"),
        {"body": "sneaky", "pod_id": m_pod.id, "audience_yards": [paternal.id]},
    )
    assert response.status_code == 302  # no confirm needed: nothing widened
    post = Post.objects.get(body="sneaky")
    assert list(post.audience_yards.all()) == []  # foreign yard dropped, no leak


def test_compose_to_a_foreign_pod_404s(world: dict[str, object]) -> None:
    author = world["author"]
    p_pod = world["p_pod"]
    assert isinstance(author, Member)
    assert isinstance(p_pod, Pod)
    response = _client_for(author).post(
        reverse("compose"), {"body": "wrong pod", "pod_id": p_pod.id}
    )
    assert response.status_code == 404  # byte-identical to an unknown pod
    assert not Post.objects.filter(body="wrong pod").exists()


def test_compose_rejects_an_empty_body(world: dict[str, object]) -> None:
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    response = _client_for(author).post(reverse("compose"), {"body": "   ", "pod_id": m_pod.id})
    assert response.status_code == 200  # re-rendered with the error, not a redirect
    assert Post.objects.count() == 0


def test_compose_get_is_404(world: dict[str, object]) -> None:
    author = world["author"]
    assert isinstance(author, Member)
    assert _client_for(author).get(reverse("compose")).status_code == 404
