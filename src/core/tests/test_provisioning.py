"""Elder-token provisioning (S-104): generate, hand over, regenerate.

Properties under test: the page shows the exact pod and yard the token will
grant before generation (T-TOKEN-G1) and names the surface as the elder path;
generating displays the link plus an inline printable QR (no script, no
network); regenerating invalidates the prior token and shows fresh artifacts in
the same flow; the surface is authorization-gated like the roster (a yard admin
provisions only within their yards); and it can never issue a token to a
supervised member (TM-10).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core import elder_tokens
from core.models import ElderToken, Member, Pod, PodMembership, Yard

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


@dataclass
class World:
    maternal: Yard
    paternal: Yard
    m_pod: Pod
    p_pod: Pod
    instance_admin: Member
    yard_admin: Member
    nana: Member  # maternal, ordinary
    far: Member  # paternal
    child: Member  # supervised


@pytest.fixture
def world() -> World:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    m_pod = Pod.objects.create(name="Maternal cousins")
    m_pod.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal cousins")
    p_pod.yards.set([paternal])
    nana = _member(m_pod, "Nana", kinship_name="Nana")
    child = _member(m_pod, "Kiddo", role=Member.SUPERVISED, is_supervised=True)
    return World(
        maternal=maternal,
        paternal=paternal,
        m_pod=m_pod,
        p_pod=p_pod,
        instance_admin=_member(m_pod, "Boss", role=Member.INSTANCE_ADMIN),
        yard_admin=_member(m_pod, "Yadmin", role=Member.YARD_ADMIN),
        nana=nana,
        far=_member(p_pod, "Far", role=Member.MEMBER),
        child=child,
    )


def test_page_shows_the_grant_before_generation(world: World) -> None:
    body = (
        _client_for(world.instance_admin)
        .get(reverse("provision_elder", args=[world.nana.id]))
        .content.decode()
    )
    assert "elder path" in body  # names the surface
    assert "Maternal" in body  # the exact yard the token will grant
    assert "Maternal cousins" in body  # and pod
    assert "cannot edit profiles" in body  # the ceiling stated to the helper
    assert not ElderToken.objects.exists()  # loading the page never mints


def test_generate_shows_link_and_inline_qr(world: World) -> None:
    response = _client_for(world.instance_admin).post(
        reverse("provision_elder", args=[world.nana.id])
    )
    body = response.content.decode()
    assert ElderToken.objects.filter(member=world.nana).count() == 1
    assert "/t/" in body  # the handover link
    assert "<svg" in body and "</svg>" in body  # the QR, inline, no network
    assert "script" not in body.lower()  # printable, script-free


def test_regenerate_invalidates_the_prior_token_and_shows_fresh_artifacts(world: World) -> None:
    client = _client_for(world.instance_admin)
    first = client.post(reverse("provision_elder", args=[world.nana.id])).content.decode()
    first_link = _link_from(first)
    second = client.post(reverse("provision_elder", args=[world.nana.id])).content.decode()
    second_link = _link_from(second)

    assert second_link != first_link  # a fresh link in the same flow
    assert "<svg" in second  # and a fresh QR
    old_raw = first_link.split("/t/")[1].rstrip("/")
    with pytest.raises(elder_tokens.ElderTokenInvalid):
        elder_tokens.resolve(old_raw)  # the prior token is dead
    new_raw = second_link.split("/t/")[1].rstrip("/")
    assert elder_tokens.resolve(new_raw)  # the new one works


def test_yard_admin_provisions_only_within_their_yards(world: World) -> None:
    client = _client_for(world.yard_admin)
    assert client.get(reverse("provision_elder", args=[world.nana.id])).status_code == 200
    # A paternal member is outside a maternal yard admin's reach: a 404, the same
    # as a member who does not exist (require_visible_member parity).
    assert client.get(reverse("provision_elder", args=[world.far.id])).status_code == 404


def test_a_plain_member_cannot_reach_provisioning(world: World) -> None:
    assert (
        _client_for(world.nana).get(reverse("provision_elder", args=[world.nana.id])).status_code
        == 403
    )


def test_supervised_members_can_never_be_provisioned(world: World) -> None:
    client = _client_for(world.instance_admin)
    assert client.get(reverse("provision_elder", args=[world.child.id])).status_code == 404
    assert client.post(reverse("provision_elder", args=[world.child.id])).status_code == 404
    assert not ElderToken.objects.filter(member=world.child).exists()


def test_the_roster_offers_the_link_for_ordinary_members_only(world: World) -> None:
    body = _client_for(world.instance_admin).get(reverse("members")).content.decode()
    assert reverse("provision_elder", args=[world.nana.id]) in body
    assert reverse("provision_elder", args=[world.child.id]) not in body  # not for a child


def _link_from(body: str) -> str:
    import re

    match = re.search(r'value="(http[^"]*/t/[^"]+)"', body)
    assert match, "no elder link in the page"
    return match.group(1)
