"""New-elder onboarding (S-213): a delegate stands up a net-new grandparent on the
no-login elder path in one flow, without a shell.

Properties under test: naming a net-new elder and picking a side creates their household
pod, a token-only member (no User, non-supervised), and their elder token together, and
shows the hand-over link + inline printable QR once; the surface is delegate-usable and
scoped exactly like a household invite (a yard admin only within their own yards, the
instance admin onto any side including one they are not a member of, a cross-yard pick a
byte-identical 404 that mints nothing); the elder's whole visibility is that household's
side; the flow is refresh-safe and carries the TM-5 no-store headers; a plain member
cannot reach it; and the new elder then appears on the roster and can be re-provisioned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import Client
from django.urls import reverse

from core import elder_tokens, scoping
from core.models import ElderToken, Member, Pod, PodMembership, Yard

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


def _intent(client: Client) -> str:
    body = client.get(reverse("new_elder")).content.decode()
    match = re.search(r'name="intent" value="([^"]+)"', body)
    assert match, "no intent nonce on the new-elder page"
    return match.group(1)


def _create_elder(
    client: Client,
    *,
    yard_id: int,
    elder_name: str = "Rose Davis",
    kinship: str = "Nana",
    household: str = "Nana's house",
) -> HttpResponse:
    intent = _intent(client)
    resp = client.post(
        reverse("new_elder"),
        {
            "elder_name": elder_name,
            "kinship_name": kinship,
            "household_name": household,
            "yard_id": str(yard_id),
            "intent": intent,
        },
    )
    assert isinstance(resp, HttpResponse)
    return resp


def _elder_link_from(body: str) -> str:
    match = re.search(r'value="(http[^"]*/t/[^"]+)"', body)
    assert match, "no elder /t/ link in the page"
    return match.group(1)


def _raw(link: str) -> str:
    return link.split("/t/")[1].rstrip("/")


@dataclass
class World:
    maternal: Yard
    paternal: Yard
    m_pod: Pod
    p_pod: Pod
    instance_admin: Member  # in maternal only
    m_admin: Member  # yard admin, maternal
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
        plain=_member(m_pod, "Cousin", role=Member.MEMBER),
    )


def test_creates_household_member_and_token_in_one_flow(world: World) -> None:
    resp = _create_elder(_client_for(world.instance_admin), yard_id=world.maternal.id)
    assert resp.status_code == 200
    body = resp.content.decode()

    elder = Member.objects.get(display_name="Rose Davis")
    assert elder.user is None  # token-only, no login
    assert elder.is_supervised is False
    assert elder.role == Member.MEMBER
    assert elder.kinship_name == "Nana"

    # A brand-new household pod on the picked side holds the elder.
    pod = Pod.objects.get(name="Nana's house")
    assert pod.kind == Pod.HOUSEHOLD
    assert set(pod.yards.values_list("id", flat=True)) == {world.maternal.id}
    assert PodMembership.objects.filter(member=elder, pod=pod).exists()

    # Their elder token is minted and the hand-over link + inline QR are shown once.
    assert ElderToken.objects.filter(member=elder).count() == 1
    assert "<svg" in body and "</svg>" in body
    svg = body[body.index("<svg") : body.index("</svg>") + 6]
    assert "<script" not in svg.lower() and "onload" not in svg.lower()
    raw = _raw(_elder_link_from(body))
    assert elder_tokens.resolve(raw).member_id == elder.id  # the shown link is the elder's


def test_the_new_elder_sees_their_own_side(world: World) -> None:
    """The elder's whole visibility is the household's side, nothing wider."""
    _create_elder(_client_for(world.instance_admin), yard_id=world.maternal.id)
    elder = Member.objects.get(display_name="Rose Davis")
    assert scoping.member_yard_ids(elder) == {world.maternal.id}


def test_delegate_usable_a_yard_admin_onboards_in_their_own_yard(world: World) -> None:
    """S-213's point: a per-side delegate does this themselves, no shell, no founder."""
    resp = _create_elder(
        _client_for(world.m_admin),
        yard_id=world.maternal.id,
        elder_name="Grandma Fox",
        household="Fox house",
    )
    assert resp.status_code == 200
    elder = Member.objects.get(display_name="Grandma Fox")
    raw = _raw(_elder_link_from(resp.content.decode()))
    assert elder_tokens.resolve(raw).member_id == elder.id
    assert scoping.member_yard_ids(elder) == {world.maternal.id}


def test_a_yard_admin_cannot_onboard_onto_another_side(world: World) -> None:
    """A maternal admin picking the paternal side gets the same 404 as a nonexistent
    yard, and mints nothing (require_visible_yard parity, S-202)."""
    before_pods = Pod.objects.count()
    before_members = Member.objects.count()
    resp = _create_elder(_client_for(world.m_admin), yard_id=world.paternal.id)
    assert resp.status_code == 404
    assert Pod.objects.count() == before_pods
    assert Member.objects.count() == before_members
    assert not ElderToken.objects.exists()


def test_the_instance_admin_can_onboard_onto_a_side_they_are_not_in(world: World) -> None:
    """The seed-ally case: the founder stands up a grandparent on the other side even
    though they are not a member of it."""
    # The instance admin is in the maternal side only; the paternal side is not theirs.
    assert world.paternal.id not in scoping.member_yard_ids(world.instance_admin)
    resp = _create_elder(
        _client_for(world.instance_admin),
        yard_id=world.paternal.id,
        elder_name="Paternal Nana",
        household="Their house",
    )
    assert resp.status_code == 200
    elder = Member.objects.get(display_name="Paternal Nana")
    assert scoping.member_yard_ids(elder) == {world.paternal.id}


def test_the_yard_picker_is_scoped_for_a_delegate(world: World) -> None:
    form = _client_for(world.m_admin).get(reverse("new_elder")).content.decode()
    assert "Maternal" in form
    assert "Paternal" not in form  # a delegate never sees the other side as a target


def test_names_are_required(world: World) -> None:
    client = _client_for(world.instance_admin)
    before = Member.objects.count()
    resp = _create_elder(client, yard_id=world.maternal.id, elder_name="   ")
    assert resp.status_code == 200
    assert "Give the grandparent a name." in resp.content.decode()
    resp2 = _create_elder(client, yard_id=world.maternal.id, household="   ")
    assert "Name their household." in resp2.content.decode()
    assert Member.objects.count() == before  # nothing created either time
    assert not ElderToken.objects.exists()


def test_refresh_does_not_create_a_duplicate_elder(world: World) -> None:
    client = _client_for(world.instance_admin)
    intent = _intent(client)
    payload = {
        "elder_name": "Rose Davis",
        "kinship_name": "Nana",
        "household_name": "Nana's house",
        "yard_id": str(world.maternal.id),
        "intent": intent,
    }
    first = client.post(reverse("new_elder"), payload)
    assert first.status_code == 200
    assert Member.objects.filter(display_name="Rose Davis").count() == 1

    replay = client.post(reverse("new_elder"), payload)  # the refresh
    assert replay.status_code == 200
    assert Member.objects.filter(display_name="Rose Davis").count() == 1  # still one
    assert Pod.objects.filter(name="Nana's house").count() == 1
    assert ElderToken.objects.count() == 1
    assert not re.search(r'value="http[^"]*/t/', replay.content.decode())  # nothing re-minted


def test_a_plain_member_cannot_reach_the_surface(world: World) -> None:
    client = _client_for(world.plain)
    assert client.get(reverse("new_elder")).status_code == 403
    assert client.post(reverse("new_elder")).status_code == 403


def test_the_minted_page_carries_the_tm5_headers(world: World) -> None:
    resp = _create_elder(_client_for(world.instance_admin), yard_id=world.maternal.id)
    assert resp["Cache-Control"] == "no-store"
    # same-origin, NOT no-referrer: the token is in the body (not the URL) and the page
    # hosts the create form, whose browser POST is CSRF-rejected under no-referrer (the
    # Origin goes null). same-origin still leaks nothing cross-origin. See handover.py.
    assert resp["Referrer-Policy"] == "same-origin"
    assert resp["X-Robots-Tag"] == "noindex, nofollow"
    # The empty form GET carries them too, harmlessly.
    assert (
        _client_for(world.instance_admin).get(reverse("new_elder"))["Cache-Control"] == "no-store"
    )


def test_the_new_elder_appears_on_the_roster_and_can_be_re_provisioned(world: World) -> None:
    """After creation the elder is an ordinary (non-supervised) roster member, so the
    existing provision_elder surface can re-mint their link if it goes astray."""
    admin = _client_for(world.instance_admin)
    _create_elder(admin, yard_id=world.maternal.id)
    elder = Member.objects.get(display_name="Rose Davis")

    roster = admin.get(reverse("members")).content.decode()
    assert "Rose Davis" in roster
    assert reverse("provision_elder", args=[elder.id]) in roster  # offered the elder link

    regen = admin.get(reverse("provision_elder", args=[elder.id]))
    assert regen.status_code == 200  # the existing per-member surface reaches the new elder
