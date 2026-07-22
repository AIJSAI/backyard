"""Rollout enablers: appoint a delegate (S-707) and create the other family side (S-708).

These are the two moves the seed-ally rollout begins with, and until now both were
shell-only. Properties under test: an instance admin can create a new family side and
stand up its first household even though they are not yet a member of it, then promote
the new member to a per-side yard-admin scoped to that side; a yard admin can re-role an
in-scope member to a non-admin role but can NEVER grant an admin role or reach another
yard's member (T-AUTH-G2, S-202 parity); role strings are whitelisted and supervised
members are never re-roled here; and creating a family side is instance-admin only and
refresh-safe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import Client
from django.urls import reverse

from core import invites, permissions
from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_PW = "a-Strong-passphrase-9"
_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _member(pod: Pod, name: str, role: str = Member.MEMBER, **kwargs: object) -> Member:
    user = User.objects.create_user(username=name.lower(), password=_PW)
    member = Member.objects.create(display_name=name, user=user, role=role, **kwargs)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _client_for(member: Member) -> Client:
    assert member.user is not None
    c = Client()
    c.force_login(member.user, backend=_BACKEND)
    return c


def _create_yard(client: Client, name: str) -> HttpResponse:
    page = client.get(reverse("family_sides")).content.decode()
    match = re.search(r'name="intent" value="([^"]+)"', page)
    assert match, "no intent nonce on the family-sides page"
    resp = client.post(reverse("family_sides"), {"yard_name": name, "intent": match.group(1)})
    assert isinstance(resp, HttpResponse)
    return resp


@dataclass
class World:
    maternal: Yard
    paternal: Yard
    m_pod: Pod
    p_pod: Pod
    instance_admin: Member  # in maternal only
    m_admin: Member  # yard admin, maternal
    p_member: Member  # ordinary member, paternal
    plain: Member  # ordinary member, maternal


@pytest.fixture
def world() -> World:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    m_pod = Pod.objects.create(name="Maternal seed", kind=Pod.HOUSEHOLD)
    m_pod.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal seed", kind=Pod.HOUSEHOLD)
    p_pod.yards.set([paternal])
    return World(
        maternal=maternal,
        paternal=paternal,
        m_pod=m_pod,
        p_pod=p_pod,
        instance_admin=_member(m_pod, "Boss", role=Member.INSTANCE_ADMIN),
        m_admin=_member(m_pod, "MaternalMod", role=Member.YARD_ADMIN),
        p_member=_member(p_pod, "PaternalCousin", role=Member.MEMBER),
        plain=_member(m_pod, "Cousin", role=Member.MEMBER),
    )


# --- S-708 create a family side ---


def test_instance_admin_creates_a_family_side(world: World) -> None:
    client = _client_for(world.instance_admin)
    before = set(Yard.objects.values_list("id", flat=True))
    resp = _create_yard(client, "Grandpa's side")
    assert resp.status_code == 302
    new = list(Yard.objects.exclude(id__in=before))
    assert len(new) == 1
    assert new[0].name == "Grandpa's side"


def test_creating_a_family_side_is_refresh_safe(world: World) -> None:
    client = _client_for(world.instance_admin)
    page = client.get(reverse("family_sides")).content.decode()
    intent = re.search(r'name="intent" value="([^"]+)"', page).group(1)  # type: ignore[union-attr]
    payload = {"yard_name": "West coast", "intent": intent}
    client.post(reverse("family_sides"), payload)
    client.post(reverse("family_sides"), payload)  # the refresh
    assert Yard.objects.filter(name="West coast").count() == 1  # not duplicated


def test_family_side_requires_a_name(world: World) -> None:
    client = _client_for(world.instance_admin)
    before = Yard.objects.count()
    resp = _create_yard(client, "   ")
    assert resp.status_code == 200
    assert "Give the family side a name." in resp.content.decode()
    assert Yard.objects.count() == before


def test_a_yard_admin_cannot_create_a_family_side(world: World) -> None:
    assert _client_for(world.m_admin).get(reverse("family_sides")).status_code == 403
    assert _client_for(world.plain).get(reverse("family_sides")).status_code == 403


# --- S-707 appoint a delegate / change a role ---


def _post_role(client: Client, member: Member, role: str) -> HttpResponse:
    resp = client.post(reverse("assign_role", args=[member.id]), {"role": role})
    assert isinstance(resp, HttpResponse)
    return resp


def test_instance_admin_appoints_a_yard_admin_delegate(world: World) -> None:
    resp = _post_role(_client_for(world.instance_admin), world.plain, Member.YARD_ADMIN)
    assert resp.status_code == 302
    world.plain.refresh_from_db()
    assert world.plain.role == Member.YARD_ADMIN
    # And the new delegate is scoped to their own yard: they can now issue invites into
    # maternal (where their pod is) but nothing depends on another yard.
    assert permissions.can_issue_invite(world.plain, world.m_pod)


def test_instance_admin_grants_a_second_instance_admin(world: World) -> None:
    _post_role(_client_for(world.instance_admin), world.plain, Member.INSTANCE_ADMIN)
    world.plain.refresh_from_db()
    assert world.plain.role == Member.INSTANCE_ADMIN


def test_yard_admin_can_re_role_in_scope_but_not_to_admin(world: World) -> None:
    client = _client_for(world.m_admin)
    # In-scope, to a non-admin role: allowed.
    assert _post_role(client, world.plain, Member.POD_OWNER).status_code == 302
    world.plain.refresh_from_db()
    assert world.plain.role == Member.POD_OWNER
    # To an admin role: refused (only the instance admin grants admin roles).
    assert _post_role(client, world.plain, Member.YARD_ADMIN).status_code == 403
    world.plain.refresh_from_db()
    assert world.plain.role == Member.POD_OWNER  # unchanged


def test_yard_admin_cannot_reach_another_yards_member(world: World) -> None:
    # A maternal admin acting on a paternal member gets the same 404 as a nonexistent one.
    resp = _client_for(world.m_admin).post(
        reverse("assign_role", args=[world.p_member.id]), {"role": Member.POD_OWNER}
    )
    assert resp.status_code == 404
    world.p_member.refresh_from_db()
    assert world.p_member.role == Member.MEMBER


def test_assign_role_rejects_an_unknown_role_and_supervised(world: World) -> None:
    from core import supervised as supervised_svc

    client = _client_for(world.instance_admin)
    assert _post_role(client, world.plain, "wizard").status_code == 404  # not in the whitelist
    assert _post_role(client, world.plain, Member.SUPERVISED).status_code == 404  # never via here
    child = supervised_svc.create_supervised_member(
        parent=world.plain, display_name="Kiddo", pod=world.m_pod
    )
    assert _post_role(client, child, Member.MEMBER).status_code == 404  # supervised not re-roled


def test_assign_role_is_post_only_and_admin_only(world: World) -> None:
    assert (
        _client_for(world.instance_admin)
        .get(reverse("assign_role", args=[world.plain.id]))
        .status_code
        == 404
    )
    assert _post_role(_client_for(world.plain), world.m_admin, Member.MEMBER).status_code == 403


def test_no_self_role_change(world: World) -> None:
    # An instance admin cannot re-role themselves (no self-administration).
    assert (
        _post_role(
            _client_for(world.instance_admin), world.instance_admin, Member.MEMBER
        ).status_code
        == 403
    )


# --- the seed-ally rollout, end to end ---


def test_seed_ally_rollout_create_side_invite_household_appoint_delegate(world: World) -> None:
    """The whole point: an instance admin stands up the OTHER family side, invites its
    first household even though they are not a member of that side, the invitee joins,
    and the admin promotes them to the per-side delegate who can then onboard the rest —
    all without a shell."""
    admin = _client_for(world.instance_admin)

    # 1. Create the new family side.
    _create_yard(admin, "Dad side")
    dads = Yard.objects.get(name="Dad side")

    # 2. Invite the first household into it — instance admin can pick a yard they are not
    #    yet a member of (the S-708 -> invite_household extension).
    form = admin.get(reverse("invite_household")).content.decode()
    assert f'value="{dads.id}"' in form  # the new empty side is a pickable option
    intent = re.search(r'name="intent" value="([^"]+)"', form).group(1)  # type: ignore[union-attr]
    minted = admin.post(
        reverse("invite_household"),
        {"household_name": "The Fox family", "yard_id": str(dads.id), "intent": intent},
    ).content.decode()
    raw = re.search(r"/join/([A-Za-z0-9_-]+)/", minted).group(1)  # type: ignore[union-attr]

    # 3. A fresh person redeems -> lands in the new household on Dad's side.
    chris = invites.redeem_invite(raw, display_name="Uncle Chris", user_id=None)
    chris_user = User.objects.create_user(username="chris", password=_PW)
    chris.user = chris_user
    chris.save(update_fields=["user"])
    assert dads.id in {y.id for pod in chris.pods.all() for y in pod.yards.all()}

    # 4. The admin promotes Chris to the per-side delegate.
    assert _post_role(admin, chris, Member.YARD_ADMIN).status_code == 302
    chris.refresh_from_db()
    assert chris.role == Member.YARD_ADMIN

    # 5. Chris is now a self-sufficient delegate: he can issue invites into Dad's side...
    fox_pod = Pod.objects.get(name="The Fox family")
    assert permissions.can_issue_invite(chris, fox_pod)
    # ...and only into Dad's side (T-AUTH-G2): the maternal seed pod is out of his reach.
    assert not permissions.can_issue_invite(chris, world.m_pod)
