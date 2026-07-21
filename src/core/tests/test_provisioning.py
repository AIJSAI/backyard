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


def _intent(client: Client, member_id: int) -> str:
    """Read a fresh intent nonce off the provisioning page (the hidden field)."""
    import re

    body = client.get(reverse("provision_elder", args=[member_id])).content.decode()
    match = re.search(r'name="intent" value="([^"]+)"', body)
    assert match, "no intent nonce on the page"
    return match.group(1)


def _mint(client: Client, member_id: int) -> str:
    """Generate via the real form (grant page -> intent -> POST) and return the body."""
    intent = _intent(client, member_id)
    return client.post(
        reverse("provision_elder", args=[member_id]), {"intent": intent}
    ).content.decode()


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
    body = _mint(_client_for(world.instance_admin), world.nana.id)
    assert ElderToken.objects.filter(member=world.nana).count() == 1
    assert "/t/" in body  # the handover link
    assert "<svg" in body and "</svg>" in body  # the QR, inline, no network
    assert "script" not in body.lower()  # printable, script-free


def test_regenerate_invalidates_the_prior_token_and_shows_fresh_artifacts(world: World) -> None:
    client = _client_for(world.instance_admin)
    first = _mint(client, world.nana.id)
    first_link = _link_from(first)
    second = _mint(client, world.nana.id)  # a fresh intent = a deliberate regenerate
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


# --- folds from the #43 security review ---


def test_the_minted_token_page_carries_the_tm5_headers(world: World) -> None:
    """#43 review HIGH-1: the one page that displays the master token gets the
    no-store/no-referrer/noindex set, defending a bfcache restore of a
    walked-away-from admin screen — even though /members/ is not a token route."""
    client = _client_for(world.instance_admin)
    intent = _intent(client, world.nana.id)
    response = client.post(reverse("provision_elder", args=[world.nana.id]), {"intent": intent})
    assert response["Cache-Control"] == "no-store"
    assert response["Referrer-Policy"] == "no-referrer"
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    # The grant page (no token in the body) carries them too, harmlessly.
    assert (
        client.get(reverse("provision_elder", args=[world.nana.id]))["Cache-Control"] == "no-store"
    )


def test_refresh_does_not_silently_regenerate(world: World) -> None:
    """#43 review MEDIUM-2: a replayed POST (browser refresh) with a spent intent
    nonce re-renders WITHOUT minting, so the link the admin just handed over
    stays alive."""
    client = _client_for(world.instance_admin)
    intent = _intent(client, world.nana.id)
    minted = client.post(
        reverse("provision_elder", args=[world.nana.id]), {"intent": intent}
    ).content.decode()
    handed_over = _link_from(minted)
    raw = handed_over.split("/t/")[1].rstrip("/")

    # The refresh: the SAME POST body, replaying the now-spent nonce.
    replay = client.post(reverse("provision_elder", args=[world.nana.id]), {"intent": intent})
    assert b"/t/" not in replay.content  # nothing new minted or shown
    assert elder_tokens.resolve(raw)  # the handed-over link is still alive
    assert ElderToken.objects.filter(member=world.nana).count() == 1  # exactly one


def test_a_bridge_target_needs_the_instance_admin(world: World) -> None:
    """#43 review LOW-4 / T-AUTH-G2: a bridge member is visible to a yard admin
    but has yards spilling outside their scope, so a yard admin cannot provision
    them; only the instance admin can, and it mints nothing on refusal."""
    bridge_pod = Pod.objects.create(name="Bridge household")
    bridge_pod.yards.set([world.maternal, world.paternal])
    bridge = Member.objects.create(display_name="Bridge parent")
    PodMembership.objects.create(member=bridge, pod=bridge_pod)

    yard_admin = _client_for(world.yard_admin)
    assert yard_admin.get(reverse("provision_elder", args=[bridge.id])).status_code == 403
    assert yard_admin.post(reverse("provision_elder", args=[bridge.id])).status_code == 403
    assert not ElderToken.objects.filter(member=bridge).exists()
    # The instance admin, in both yards, can — and the page shows BOTH yards as
    # the grant (the token's true blast radius, T-TOKEN-G1).
    body = (
        _client_for(world.instance_admin)
        .get(reverse("provision_elder", args=[bridge.id]))
        .content.decode()
    )
    assert "Maternal" in body and "Paternal" in body
