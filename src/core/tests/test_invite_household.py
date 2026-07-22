"""Delegated household onboarding (S-201): an admin stands up a household and mints
its invite in one flow, sees the outstanding-invite ledger scoped to what they may
issue, and revokes a link.

Properties under test: creating a household in one flow makes the pod in the picked
yard and mints a one-time /join link + printable QR shown once; a browser refresh
(replayed intent nonce) does not duplicate the household or invite; a yard admin is
confined to their own yards for both creating and seeing invites, with a cross-yard
target 404ing exactly like a nonexistent one (S-202 parity); a plain member cannot
reach the surface; the invitee redeems and lands already inside the pod with no
community-setup step; and revoking kills the link immediately. The minted page
carries the TM-5 no-store header set, defending a walked-away-from admin screen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import Client
from django.urls import reverse

from core import invites
from core.models import Invite, Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_TEST_PW = "a-Strong-passphrase-9"
_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _member(pod: Pod, name: str, role: str = Member.MEMBER, **kwargs: object) -> Member:
    user = User.objects.create_user(username=name.lower(), password=_TEST_PW)
    member = Member.objects.create(display_name=name, user=user, role=role, **kwargs)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _client_for(member: Member) -> Client:
    assert member.user is not None
    c = Client()
    c.force_login(member.user, backend=_BACKEND)
    return c


def _intent(client: Client) -> str:
    """Read a fresh intent nonce off the invite-household page (the hidden field)."""
    body = client.get(reverse("invite_household")).content.decode()
    match = re.search(r'name="intent" value="([^"]+)"', body)
    assert match, "no intent nonce on the page"
    return match.group(1)


def _create_household(client: Client, *, yard_id: int, name: str) -> HttpResponse:
    """POST the create form with a freshly read intent nonce; returns the response."""
    intent = _intent(client)
    response = client.post(
        reverse("invite_household"),
        {"household_name": name, "yard_id": str(yard_id), "intent": intent},
    )
    assert isinstance(response, HttpResponse)
    return response


def _join_link_from(body: str) -> str:
    match = re.search(r'value="(http[^"]*/join/[^"]+)"', body)
    assert match, "no /join link in the page"
    return match.group(1)


def _raw_token(join_link: str) -> str:
    return join_link.split("/join/")[1].rstrip("/")


@dataclass
class World:
    maternal: Yard
    paternal: Yard
    m_pod: Pod
    p_pod: Pod
    instance_admin: Member  # in maternal only
    m_admin: Member  # yard admin, maternal side
    p_admin: Member  # yard admin, paternal side
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
        p_admin=_member(p_pod, "PaternalMod", role=Member.YARD_ADMIN),
        plain=_member(m_pod, "Cousin", role=Member.MEMBER),
    )


def test_admin_creates_household_and_mints_invite(world: World) -> None:
    client = _client_for(world.instance_admin)
    before = set(Pod.objects.values_list("id", flat=True))
    response = _create_household(client, yard_id=world.maternal.id, name="The Davis family")
    assert response.status_code == 200
    body = response.content.decode()

    # Exactly one new household pod, in the picked yard, of the household kind.
    new_ids = set(Pod.objects.values_list("id", flat=True)) - before
    assert len(new_ids) == 1
    pod = Pod.objects.get(id=new_ids.pop())
    assert pod.name == "The Davis family"
    assert pod.kind == Pod.HOUSEHOLD
    assert set(pod.yards.values_list("id", flat=True)) == {world.maternal.id}

    # One invite for that pod, and its one-time link + inline printable QR are shown.
    invite = Invite.objects.get(pod=pod)
    assert "/join/" in body
    assert "<svg" in body and "</svg>" in body
    svg = body[body.index("<svg") : body.index("</svg>") + 6]
    assert "<script" not in svg.lower() and "onload" not in svg.lower()
    # The link on the page redeems to THIS invite.
    raw = _raw_token(_join_link_from(body))
    assert invites.peek_invite(raw).pk == invite.pk


def test_invitee_redeems_and_lands_inside_the_pod(world: World) -> None:
    """S-201's core promise: no community-setup screen. The invitee redeems at /join
    and is already a member of the household pod."""
    client = _client_for(world.m_admin)
    response = _create_household(client, yard_id=world.maternal.id, name="The Novak family")
    raw = _raw_token(_join_link_from(response.content.decode()))
    pod = Pod.objects.get(name="The Novak family")

    member = invites.redeem_invite(raw, display_name="Aunt Rose", user_id=None)
    assert PodMembership.objects.filter(member=member, pod=pod).exists()
    # And the admin's ledger now shows who joined, and when.
    ledger = client.get(reverse("member_invites")).content.decode()
    assert "Aunt Rose" in ledger


def test_refresh_does_not_duplicate_the_household(world: World) -> None:
    """A replayed POST (browser refresh) with a spent intent nonce re-renders without
    creating a second household or invite."""
    client = _client_for(world.instance_admin)
    intent = _intent(client)
    payload = {
        "household_name": "The Reyes family",
        "yard_id": str(world.maternal.id),
        "intent": intent,
    }
    first = client.post(reverse("invite_household"), payload)
    assert first.status_code == 200
    assert Pod.objects.filter(name="The Reyes family").count() == 1
    assert Invite.objects.count() == 1

    replay = client.post(reverse("invite_household"), payload)  # the refresh
    assert replay.status_code == 200
    assert Pod.objects.filter(name="The Reyes family").count() == 1  # still one
    assert Invite.objects.count() == 1  # nothing re-minted
    # The replay minted nothing, so no fresh /join link is rendered.
    assert not re.search(r'value="http[^"]*/join/', replay.content.decode())


def test_household_name_is_required(world: World) -> None:
    client = _client_for(world.instance_admin)
    before = Pod.objects.count()
    response = _create_household(client, yard_id=world.maternal.id, name="   ")
    assert response.status_code == 200
    assert "Give the household a name." in response.content.decode()
    assert Pod.objects.count() == before  # nothing created
    assert Invite.objects.count() == 0


def test_yard_admin_is_confined_to_their_own_yard(world: World) -> None:
    client = _client_for(world.p_admin)
    # Their form offers only the paternal side.
    form = client.get(reverse("invite_household")).content.decode()
    assert "Paternal" in form
    assert "Maternal" not in form

    # Creating in their own yard works.
    ok = _create_household(client, yard_id=world.paternal.id, name="The Fox family")
    assert ok.status_code == 200
    assert Pod.objects.filter(name="The Fox family").exists()

    # Trying to stand up a household in the maternal yard 404s exactly like a yard
    # that does not exist (require_visible_yard parity), and mints nothing.
    before = Pod.objects.count()
    blocked = _create_household(client, yard_id=world.maternal.id, name="The Cross family")
    assert blocked.status_code == 404
    assert Pod.objects.count() == before


def test_plain_member_cannot_reach_the_surface(world: World) -> None:
    client = _client_for(world.plain)
    assert client.get(reverse("invite_household")).status_code == 403
    assert client.post(reverse("invite_household")).status_code == 403
    assert client.get(reverse("member_invites")).status_code == 403


def test_invite_list_scopes_to_what_the_actor_may_issue(world: World) -> None:
    # A maternal invite and a paternal invite exist.
    _create_household(
        _client_for(world.m_admin), yard_id=world.maternal.id, name="Maternal household"
    )
    _create_household(
        _client_for(world.p_admin), yard_id=world.paternal.id, name="Paternal household"
    )

    # The maternal moderator sees only the maternal invite.
    m_view = _client_for(world.m_admin).get(reverse("member_invites")).content.decode()
    assert "Maternal household" in m_view
    assert "Paternal household" not in m_view

    # The paternal moderator sees only the paternal invite.
    p_view = _client_for(world.p_admin).get(reverse("member_invites")).content.decode()
    assert "Paternal household" in p_view
    assert "Maternal household" not in p_view

    # The instance admin sees every invite across both sides.
    all_view = _client_for(world.instance_admin).get(reverse("member_invites")).content.decode()
    assert "Maternal household" in all_view and "Paternal household" in all_view


def test_invite_list_excludes_bridge_pod_invites_from_a_yard_admin(world: World) -> None:
    """Security-review LOW: a bridge pod spanning maternal+paternal touches the
    maternal admin's yard, but its invite must never appear in (or occupy a window
    slot of) that admin's ledger, since the admin cannot issue for it. Only the
    instance admin, who may issue anywhere, sees it."""
    bridge = Pod.objects.create(name="Bridge household", kind=Pod.HOUSEHOLD)
    bridge.yards.set([world.maternal, world.paternal])
    invites.mint_invite(bridge, created_by=world.instance_admin)
    _create_household(_client_for(world.m_admin), yard_id=world.maternal.id, name="Wholly maternal")

    m_view = _client_for(world.m_admin).get(reverse("member_invites")).content.decode()
    assert "Wholly maternal" in m_view  # the in-scope invite shows
    assert "Bridge household" not in m_view  # the spanning one never does

    all_view = _client_for(world.instance_admin).get(reverse("member_invites")).content.decode()
    assert "Bridge household" in all_view  # the instance admin, who may issue it, sees it


def test_revoke_kills_the_link_immediately(world: World) -> None:
    client = _client_for(world.m_admin)
    created = _create_household(client, yard_id=world.maternal.id, name="The Lane family")
    raw = _raw_token(_join_link_from(created.content.decode()))
    invite = Invite.objects.get(pod__name="The Lane family")
    assert invites.peek_invite(raw)  # live before revoke

    response = client.post(reverse("revoke_invite", args=[invite.id]))
    assert response.status_code == 302  # redirects back to the ledger
    invite.refresh_from_db()
    assert invite.revoked_at is not None
    with pytest.raises(invites.InviteInvalid):
        invites.peek_invite(raw)  # dead immediately
    with pytest.raises(invites.InviteInvalid):
        invites.redeem_invite(raw, display_name="Too late", user_id=None)


def test_revoke_is_post_only(world: World) -> None:
    client = _client_for(world.m_admin)
    created = _create_household(client, yard_id=world.maternal.id, name="The Kerr family")
    assert created.status_code == 200  # created
    invite = Invite.objects.get(pod__name="The Kerr family")
    assert client.get(reverse("revoke_invite", args=[invite.id])).status_code == 404
    invite.refresh_from_db()
    assert invite.revoked_at is None  # a GET never revokes


def test_revoke_across_scope_404s_like_a_nonexistent_invite(world: World) -> None:
    """A yard admin revoking another yard's invite gets the same 404 as an unknown id:
    the existence of another side's invite is never revealed (S-202 parity)."""
    _create_household(_client_for(world.m_admin), yard_id=world.maternal.id, name="The Ito family")
    maternal_invite = Invite.objects.get(pod__name="The Ito family")

    p_client = _client_for(world.p_admin)
    cross = p_client.post(reverse("revoke_invite", args=[maternal_invite.id]))
    assert cross.status_code == 404
    maternal_invite.refresh_from_db()
    assert maternal_invite.revoked_at is None  # untouched

    # A wholly unknown invite id 404s identically.
    unknown = p_client.post(reverse("revoke_invite", args=[maternal_invite.id + 9999]))
    assert unknown.status_code == 404


def test_minted_page_carries_the_tm5_headers(world: World) -> None:
    """The page displays the raw invite token in its body once, so it gets the
    no-store/no-referrer/noindex set, defending a bfcache restore of a walked-away
    admin screen even though /members/ is not a token-prefix route."""
    response = _create_household(
        _client_for(world.instance_admin), yard_id=world.maternal.id, name="The Vance family"
    )
    assert response["Cache-Control"] == "no-store"
    assert response["Referrer-Policy"] == "no-referrer"
    assert response["X-Robots-Tag"] == "noindex, nofollow"
