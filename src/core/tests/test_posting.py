"""The composer write path (core/posting): audience integrity on create.

These hold the service to the AUDIENCE-INTEGRITY INVARIANT (Post model docstring,
PR #21 review MEDIUM #4): a post's pod must be one the author belongs to, and every
audience yard must be one the author belongs to. The read query honors whatever is
stored, so this is the only place the write is constrained; without it an author
could publish into a yard they are not in. This runs independent of the composer
view, which pre-filters to visible yards, so the service guarantee is proven on
its own (defense in depth).
"""

from __future__ import annotations

import pytest

from core import posting
from core.models import Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db


def _member_in(pod: Pod, name: str) -> Member:
    m = Member.objects.create(display_name=name)
    PodMembership.objects.create(member=m, pod=pod)
    return m


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
        "author": _member_in(m_pod, "Author"),
    }


def test_pod_only_post_is_created(world: dict[str, object]) -> None:
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    post = posting.create_post(author=author, pod=m_pod, audience_yards=[], body="hello")
    assert post.pod_id == m_pod.id
    assert post.author_id == author.id
    assert list(post.audience_yards.all()) == []  # pod-only


def test_yard_post_records_its_audience(world: dict[str, object]) -> None:
    author = world["author"]
    m_pod = world["m_pod"]
    maternal = world["maternal"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    assert isinstance(maternal, Yard)
    post = posting.create_post(author=author, pod=m_pod, audience_yards=[maternal], body="hi")
    assert set(post.audience_yards.values_list("id", flat=True)) == {maternal.id}


def test_posting_to_a_foreign_pod_is_refused(world: dict[str, object]) -> None:
    author = world["author"]
    p_pod = world["p_pod"]
    assert isinstance(author, Member)
    assert isinstance(p_pod, Pod)
    before = Post.objects.count()
    with pytest.raises(posting.AudienceNotAllowed):
        posting.create_post(author=author, pod=p_pod, audience_yards=[], body="leak")
    assert Post.objects.count() == before  # nothing written


def test_posting_to_a_foreign_yard_is_refused(world: dict[str, object]) -> None:
    """The core invariant: an author cannot publish into a yard they are not in,
    even when posting from a pod that is legitimately theirs."""
    author = world["author"]
    m_pod = world["m_pod"]
    paternal = world["paternal"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    assert isinstance(paternal, Yard)
    before = Post.objects.count()
    with pytest.raises(posting.AudienceNotAllowed):
        posting.create_post(author=author, pod=m_pod, audience_yards=[paternal], body="leak")
    assert Post.objects.count() == before  # refused before any row is created
