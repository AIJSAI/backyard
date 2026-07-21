"""Instance-admin member-management view tests (S-701 enforced, S-703, S-702 UI).

Proves the surface enforces the write-authorization model on real requests: only
admins reach the roster, cross-yard targets 404, an out-of-scope actor is denied,
and removal actually runs the revocation-and-teardown flow.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _member_with_user(pod: Pod, name: str, role: str = Member.MEMBER) -> Member:
    user = User.objects.create_user(username=name.lower(), password="a-Strong-passphrase-9")
    member = Member.objects.create(display_name=name, role=role, user=user)
    PodMembership.objects.create(member=member, pod=pod)
    return member


@pytest.fixture
def world() -> dict[str, object]:
    a = Yard.objects.create(name="A", slug="a")
    b = Yard.objects.create(name="B", slug="b")
    pod_a = Pod.objects.create(name="A household")
    pod_a.yards.set([a])
    pod_b = Pod.objects.create(name="B household")
    pod_b.yards.set([b])
    return {
        "pod_a": pod_a,
        "pod_b": pod_b,
        "admin": _member_with_user(pod_a, "Admin", Member.INSTANCE_ADMIN),
        "yard_a_admin": _member_with_user(pod_a, "AAdmin", Member.YARD_ADMIN),
        "member_a": _member_with_user(pod_a, "MemberA"),
        "member_b": _member_with_user(pod_b, "MemberB"),
    }


def _client_for(member: Member) -> Client:
    assert member.user is not None
    c = Client()
    c.force_login(member.user, backend=_BACKEND)
    return c


def test_anonymous_is_redirected_from_the_roster(world: dict[str, object]) -> None:
    assert Client().get(reverse("members")).status_code == 302


def test_plain_member_is_forbidden_from_the_roster(world: dict[str, object]) -> None:
    member = world["member_a"]
    assert isinstance(member, Member)
    assert _client_for(member).get(reverse("members")).status_code == 403


def test_admin_sees_only_their_yards_members(world: dict[str, object]) -> None:
    ya = world["yard_a_admin"]
    member_b = world["member_b"]
    assert isinstance(ya, Member)
    assert isinstance(member_b, Member)
    response = _client_for(ya).get(reverse("members"))
    assert response.status_code == 200
    names = {m.display_name for m in response.context["members"]}
    assert "MemberA" in names
    assert "MemberB" not in names  # the other yard never appears


def test_remove_runs_the_revocation_flow(world: dict[str, object]) -> None:
    admin = world["admin"]
    target = world["member_a"]
    assert isinstance(admin, Member)
    assert isinstance(target, Member)
    response = _client_for(admin).post(reverse("member_remove", args=[target.id]))
    assert response.status_code == 302
    assert not PodMembership.objects.filter(member=target).exists()  # detached
    assert target.user is not None
    target.user.refresh_from_db()
    assert target.user.is_active is False  # deactivated by remove_member


def test_yard_admin_cannot_remove_across_the_yard_boundary(world: dict[str, object]) -> None:
    ya = world["yard_a_admin"]
    member_b = world["member_b"]
    assert isinstance(ya, Member)
    assert isinstance(member_b, Member)
    # A yard-A admin cannot even see member B, so removal 404s (not 403): no existence leak.
    response = _client_for(ya).post(reverse("member_remove", args=[member_b.id]))
    assert response.status_code == 404
    assert PodMembership.objects.filter(member=member_b).exists()  # untouched


def test_yard_admin_cannot_remove_an_instance_admin_in_scope(world: dict[str, object]) -> None:
    """Visible but not manageable: the yard admin shares a yard with the instance
    admin, so require_visible_member passes, but the permission model forbids it."""
    ya = world["yard_a_admin"]
    admin = world["admin"]
    assert isinstance(ya, Member)
    assert isinstance(admin, Member)
    response = _client_for(ya).post(reverse("member_remove", args=[admin.id]))
    assert response.status_code == 403
    assert PodMembership.objects.filter(member=admin).exists()


def test_create_supervised_flags_and_parents_the_child(world: dict[str, object]) -> None:
    admin = world["admin"]
    parent = world["member_a"]
    pod_a = world["pod_a"]
    assert isinstance(admin, Member)
    assert isinstance(parent, Member)
    assert isinstance(pod_a, Pod)
    response = _client_for(admin).post(
        reverse("create_supervised"),
        {"parent_id": parent.id, "pod_id": pod_a.id, "display_name": "Kid"},
    )
    assert response.status_code == 302
    child = Member.objects.get(display_name="Kid")
    assert child.is_supervised is True
    assert child.managing_parent_id == parent.id
    assert child.user is None  # no independent login
    assert PodMembership.objects.filter(member=child, pod=pod_a).exists()
