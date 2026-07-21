"""Ad-hoc pods and quiet exits (S-204, S-205).

An ad-hoc pod is a private group inside a yard; its posts stay in the pod and never
reach the wider yard feed (S-204). Muting a pod hides it from the muter's feed only,
silently, and the posts stay reachable by direct link; leaving deletes the membership
with no broadcast (S-205).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core import pods, posting, scoping
from core.models import Member, Pod, PodMembership, Yard

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


@pytest.fixture
def world() -> dict[str, object]:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    m_pod = Pod.objects.create(name="Maternal household")
    m_pod.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal household")
    p_pod.yards.set([paternal])
    return {
        "maternal": maternal,
        "paternal": paternal,
        "m_pod": m_pod,
        "p_pod": p_pod,
        "author": _member_with_user(m_pod, "Author"),
        "mate": _member_with_user(m_pod, "Mate"),
        "other": _member_with_user(p_pod, "Other"),
    }


def _get(world: dict[str, object], key: str) -> object:
    return world[key]


# --- create ad-hoc pod (S-204) ---


def test_create_adhoc_pod_in_own_yard(world: dict[str, object]) -> None:
    author = world["author"]
    maternal = world["maternal"]
    assert isinstance(author, Member)
    assert isinstance(maternal, Yard)
    pod = pods.create_adhoc_pod(
        owner=author, yard=maternal, name="The Cousins", house_rule="Be kind"
    )
    assert pod.kind == Pod.ADHOC
    assert pod.owner_id == author.id
    assert pod.house_rule == "Be kind"
    assert PodMembership.objects.filter(member=author, pod=pod).exists()
    assert list(pod.yards.all()) == [maternal]


def test_cannot_create_a_pod_in_a_yard_you_are_not_in(world: dict[str, object]) -> None:
    author = world["author"]
    paternal = world["paternal"]
    assert isinstance(author, Member)
    assert isinstance(paternal, Yard)
    with pytest.raises(pods.PodActionNotAllowed):
        pods.create_adhoc_pod(owner=author, yard=paternal, name="Sneaky")


def test_adhoc_pod_posts_never_reach_the_yard_feed(world: dict[str, object]) -> None:
    """S-204: even when the author tries to widen an ad-hoc post to the yard, it stays
    pod-only, so a yard-mate outside the pod never sees it."""
    author = world["author"]
    mate = world["mate"]
    maternal = world["maternal"]
    assert isinstance(author, Member)
    assert isinstance(mate, Member)
    assert isinstance(maternal, Yard)
    adhoc = pods.create_adhoc_pod(owner=author, yard=maternal, name="Just Us")
    post = posting.create_post(author=author, pod=adhoc, audience_yards=[maternal], body="secret")
    assert list(post.audience_yards.all()) == []  # the yard widen was dropped
    author_ids = set(scoping.visible_posts(author).values_list("id", flat=True))
    mate_ids = set(scoping.visible_posts(mate).values_list("id", flat=True))
    assert post.id in author_ids  # the author is in the ad-hoc pod
    assert post.id not in mate_ids  # a maternal yard-mate outside the pod never sees it


# --- add member / house rule ---


def test_owner_adds_a_yard_sharing_member(world: dict[str, object]) -> None:
    author = world["author"]
    mate = world["mate"]
    maternal = world["maternal"]
    assert isinstance(author, Member)
    assert isinstance(mate, Member)
    assert isinstance(maternal, Yard)
    adhoc = pods.create_adhoc_pod(owner=author, yard=maternal, name="Us")
    pods.add_member_to_pod(actor=author, pod=adhoc, new_member=mate)
    assert PodMembership.objects.filter(member=mate, pod=adhoc).exists()


def test_non_owner_cannot_add_a_member(world: dict[str, object]) -> None:
    author = world["author"]
    mate = world["mate"]
    other = world["other"]
    maternal = world["maternal"]
    assert isinstance(author, Member)
    assert isinstance(mate, Member)
    assert isinstance(other, Member)
    assert isinstance(maternal, Yard)
    adhoc = pods.create_adhoc_pod(owner=author, yard=maternal, name="Us")
    pods.add_member_to_pod(actor=author, pod=adhoc, new_member=mate)
    with pytest.raises(pods.PodActionNotAllowed):
        pods.add_member_to_pod(actor=mate, pod=adhoc, new_member=other)


def test_cannot_add_someone_outside_the_pods_yard(world: dict[str, object]) -> None:
    author = world["author"]
    other = world["other"]
    maternal = world["maternal"]
    assert isinstance(author, Member)
    assert isinstance(other, Member)
    assert isinstance(maternal, Yard)
    adhoc = pods.create_adhoc_pod(owner=author, yard=maternal, name="Us")
    with pytest.raises(pods.PodActionNotAllowed):
        pods.add_member_to_pod(actor=author, pod=adhoc, new_member=other)  # paternal


def test_only_owner_sets_house_rule(world: dict[str, object]) -> None:
    author = world["author"]
    mate = world["mate"]
    maternal = world["maternal"]
    assert isinstance(author, Member)
    assert isinstance(mate, Member)
    assert isinstance(maternal, Yard)
    adhoc = pods.create_adhoc_pod(owner=author, yard=maternal, name="Us")
    pods.add_member_to_pod(actor=author, pod=adhoc, new_member=mate)
    pods.set_house_rule(actor=author, pod=adhoc, house_rule="No politics")
    adhoc.refresh_from_db()
    assert adhoc.house_rule == "No politics"
    with pytest.raises(pods.PodActionNotAllowed):
        pods.set_house_rule(actor=mate, pod=adhoc, house_rule="hijack")


# --- quiet exits (S-205) ---


def test_mute_hides_from_feed_but_keeps_direct_access(world: dict[str, object]) -> None:
    author = world["author"]
    maternal = world["maternal"]
    assert isinstance(author, Member)
    assert isinstance(maternal, Yard)
    adhoc = pods.create_adhoc_pod(owner=author, yard=maternal, name="Us")
    post = posting.create_post(author=author, pod=adhoc, audience_yards=[], body="in the pod")
    client = _client_for(author)
    assert "in the pod" in client.get(reverse("feed")).content.decode()  # visible before mute

    pods.set_muted(member=author, pod=adhoc, muted=True)
    assert "in the pod" not in client.get(reverse("feed")).content.decode()  # hidden from feed
    # still reachable by direct link (mute is display-only, not authorization)
    assert client.get(reverse("post_detail", args=[post.id])).status_code == 200

    pods.set_muted(member=author, pod=adhoc, muted=False)
    assert "in the pod" in client.get(reverse("feed")).content.decode()  # back after unmute


def test_cannot_leave_a_household_pod(world: dict[str, object]) -> None:
    """Security review LOW-1: leaving is restricted to ad-hoc pods, so a member cannot
    self-lock out of their household (which strips their yards)."""
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    with pytest.raises(pods.PodActionNotAllowed):
        pods.leave_pod(member=author, pod=m_pod)
    assert PodMembership.objects.filter(member=author, pod=m_pod).exists()


def test_cannot_set_house_rule_on_a_household_pod(world: dict[str, object]) -> None:
    """Security review INFO-1: a house rule is an ad-hoc concept; household pods refuse
    it on kind, not only on the (null) owner."""
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    with pytest.raises(pods.PodActionNotAllowed):
        pods.set_house_rule(actor=author, pod=m_pod, house_rule="no")


def test_leaving_a_pod_is_silent_and_drops_visibility(world: dict[str, object]) -> None:
    author = world["author"]
    mate = world["mate"]
    maternal = world["maternal"]
    assert isinstance(author, Member)
    assert isinstance(mate, Member)
    assert isinstance(maternal, Yard)
    adhoc = pods.create_adhoc_pod(owner=author, yard=maternal, name="Us")
    pods.add_member_to_pod(actor=author, pod=adhoc, new_member=mate)
    post = posting.create_post(author=author, pod=adhoc, audience_yards=[], body="pod post")
    assert post.id in set(scoping.visible_posts(mate).values_list("id", flat=True))

    pods.leave_pod(member=mate, pod=adhoc)
    assert not PodMembership.objects.filter(member=mate, pod=adhoc).exists()
    assert post.id not in set(scoping.visible_posts(mate).values_list("id", flat=True))


# --- views ---


def test_pod_create_view(world: dict[str, object]) -> None:
    author = world["author"]
    maternal = world["maternal"]
    assert isinstance(author, Member)
    assert isinstance(maternal, Yard)
    response = _client_for(author).post(
        reverse("pod_create"), {"name": "View Pod", "yard_id": maternal.id, "house_rule": "Hi"}
    )
    assert response.status_code == 302
    pod = Pod.objects.get(name="View Pod")
    assert pod.kind == Pod.ADHOC
    assert pod.owner_id == author.id


def test_pod_mute_view_toggles_feed(world: dict[str, object]) -> None:
    author = world["author"]
    maternal = world["maternal"]
    assert isinstance(author, Member)
    assert isinstance(maternal, Yard)
    adhoc = pods.create_adhoc_pod(owner=author, yard=maternal, name="Us")
    posting.create_post(author=author, pod=adhoc, audience_yards=[], body="mutable post")
    client = _client_for(author)
    assert client.post(reverse("pod_mute", args=[adhoc.id])).status_code == 302
    assert "mutable post" not in client.get(reverse("feed")).content.decode()


def test_pod_leave_view(world: dict[str, object]) -> None:
    author = world["author"]
    mate = world["mate"]
    maternal = world["maternal"]
    assert isinstance(author, Member)
    assert isinstance(mate, Member)
    assert isinstance(maternal, Yard)
    adhoc = pods.create_adhoc_pod(owner=author, yard=maternal, name="Us")
    pods.add_member_to_pod(actor=author, pod=adhoc, new_member=mate)
    assert _client_for(mate).post(reverse("pod_leave", args=[adhoc.id])).status_code == 302
    assert not PodMembership.objects.filter(member=mate, pod=adhoc).exists()


def test_non_member_cannot_reach_pod_actions(world: dict[str, object]) -> None:
    """A member not in the pod cannot mute, leave, or manage it: the guard 404s."""
    author = world["author"]
    other = world["other"]
    maternal = world["maternal"]
    assert isinstance(author, Member)
    assert isinstance(other, Member)
    assert isinstance(maternal, Yard)
    adhoc = pods.create_adhoc_pod(owner=author, yard=maternal, name="Us")
    assert _client_for(other).post(reverse("pod_mute", args=[adhoc.id])).status_code == 404
    assert _client_for(other).post(reverse("pod_add_member", args=[adhoc.id])).status_code == 404
