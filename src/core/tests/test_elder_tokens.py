"""The elder token surface (S-102, S-601, S-602): the isolation matrix grows.

Properties under test: the handed-over URL exchanges for a session and never
rides in use (TM-5); unknown, revoked, and expired tokens are byte-identical
404s (T-TOKEN-4 parity); one revocation act kills the link AND a live session
mid-use; the capability ceiling is structural (an elder session reaches read
and react and nothing else); the surface never crosses a yard; supervised
members can never hold a token (TM-10); minting refuses an insecure production
base URL (T-EDGE-1); one-tap reactions are named and feed reciprocity; and the
token route joins the log-redaction set.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass

import pytest
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from config.log_redaction import RedactCapabilityPaths
from core import elder_tokens, metrics, revocation
from core.models import ElderToken, Member, Pod, PodMembership, Post, Reaction, Yard

pytestmark = pytest.mark.django_db
_TEST_PW = "a-Strong-passphrase-9"


def _member_in(pod: Pod, name: str, **kwargs: object) -> Member:
    member = Member.objects.create(display_name=name, **kwargs)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _member_with_login(pod: Pod, name: str) -> Member:
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(username=name.lower(), password=_TEST_PW)
    member = Member.objects.create(display_name=name, user=user)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _login(client: Client, member: Member) -> None:
    assert member.user is not None
    client.force_login(member.user, backend="django.contrib.auth.backends.ModelBackend")


@dataclass
class World:
    maternal: Yard
    paternal: Yard
    m_pod: Pod
    p_pod: Pod
    nana: Member  # token-only elder, NO Django user
    poster: Member
    far: Member
    raw: str


@pytest.fixture
def world() -> World:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    m_pod = Pod.objects.create(name="Maternal cousins")
    m_pod.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal cousins")
    p_pod.yards.set([paternal])
    nana = _member_in(m_pod, "Nana Ann", kinship_name="Nana")
    poster = _member_in(m_pod, "Poster")
    far = _member_in(p_pod, "Far cousin")
    post = Post.objects.create(author=poster, pod=m_pod, body="MATERNAL-BODY hi Nana")
    post.audience_yards.set([maternal])
    far_post = Post.objects.create(author=far, pod=p_pod, body="PATERNAL-BODY far away")
    far_post.audience_yards.set([paternal])
    return World(
        maternal=maternal,
        paternal=paternal,
        m_pod=m_pod,
        p_pod=p_pod,
        nana=nana,
        poster=poster,
        far=far,
        raw=elder_tokens.mint(nana),
    )


def _entered(world: World) -> Client:
    client = Client()
    response = client.get(reverse("elder_enter", args=[world.raw]))
    assert response.status_code == 302 and response["Location"] == reverse("elder_feed")
    return client


# --- the exchange (TM-5) ---


def test_url_exchanges_for_a_session_and_the_clean_url_carries_no_token(world: World) -> None:
    client = _entered(world)
    response = client.get(reverse("elder_feed"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "MATERNAL-BODY" in body
    assert world.raw not in body  # the token never appears on the surface
    assert "Nana" in body  # greeted by the family name
    # Reopening the same link later still works: the elder's old text IS the link.
    assert Client().get(reverse("elder_enter", args=[world.raw])).status_code == 302


def test_session_key_cycles_at_exchange(world: World) -> None:
    client = Client()
    client.get(reverse("home"))  # provoke an initial session-capable request
    client.session.save()
    before = client.session.session_key
    client.get(reverse("elder_enter", args=[world.raw]))
    assert client.session.session_key != before  # fixation closed


# --- failure parity (T-TOKEN-4) ---


def test_unknown_revoked_and_expired_are_byte_identical_404s(world: World) -> None:
    unknown = Client().get(reverse("elder_enter", args=["never-was-a-token"]))
    Member.objects.filter(pk=world.nana.pk).update(token_generation=99)
    revoked = Client().get(reverse("elder_enter", args=[world.raw]))
    Member.objects.filter(pk=world.nana.pk).update(token_generation=1)
    ElderToken.objects.update(expires_at=timezone.now() - datetime.timedelta(days=1))
    expired = Client().get(reverse("elder_enter", args=[world.raw]))
    assert unknown.status_code == revoked.status_code == expired.status_code == 404
    assert unknown.content == revoked.content == expired.content


# --- revocation kills the link and the LIVE session (TM-1) ---


def test_revocation_ends_a_session_mid_use(world: World) -> None:
    client = _entered(world)
    assert client.get(reverse("elder_feed")).status_code == 200
    revocation.revoke_member_credentials(world.nana)
    assert client.get(reverse("elder_feed")).status_code == 404  # next click, dead
    assert client.session.get("elder_member_id") is None  # session flushed
    assert Client().get(reverse("elder_enter", args=[world.raw])).status_code == 404
    assert not ElderToken.objects.filter(member=world.nana).exists()  # row belt


def test_regenerate_is_the_total_regenerate(world: World) -> None:
    live = _entered(world)
    new_raw = elder_tokens.regenerate(world.nana)
    assert Client().get(reverse("elder_enter", args=[world.raw])).status_code == 404
    assert Client().get(reverse("elder_enter", args=[new_raw])).status_code == 302
    assert live.get(reverse("elder_feed")).status_code == 404  # old session died too


# --- the capability ceiling, structural (TM-5, T-TOKEN-1) ---


def test_elder_session_reaches_read_and_react_and_nothing_else(world: World) -> None:
    client = _entered(world)
    post = Post.objects.get(body__startswith="MATERNAL")
    gated = [
        ("get", reverse("directory")),
        ("get", reverse("export_data")),
        ("get", reverse("profile_edit")),
        ("get", reverse("members")),
        ("get", reverse("pod_list")),
        ("post", reverse("compose")),
        ("post", reverse("add_comment", args=[post.id])),
        ("post", reverse("edit_post", args=[post.id])),
    ]
    for method, url in gated:
        response = getattr(client, method)(url)
        assert response.status_code == 302, url  # bounced to the real login wall
        assert reverse("account_login") in response["Location"], url


def test_the_surface_never_crosses_a_yard(world: World) -> None:
    body = _entered(world).get(reverse("elder_feed")).content.decode()
    assert "MATERNAL-BODY" in body  # positive control
    assert "PATERNAL-BODY" not in body and "Far cousin" not in body


def test_entering_the_link_drops_a_co_located_login(world: World) -> None:
    """#42 review HIGH: opening the elder link in a browser that already holds a
    real login must NOT carry that login through the exchange, or the ceiling is
    defeated on exactly the shared family tablet this path targets."""
    mom = _member_with_login(world.m_pod, "Mom")
    client = Client()
    _login(client, mom)
    assert client.get(reverse("feed")).status_code == 200  # logged in as Mom
    client.get(reverse("elder_enter", args=[world.raw]))  # then opens Nana's link
    # The exchange flushed the login: the authenticated surfaces are gone.
    assert client.get(reverse("feed")).status_code == 302
    assert client.get(reverse("export_data")).status_code == 302
    assert "_auth_user_id" not in client.session
    assert client.get(reverse("elder_feed")).status_code == 200  # only the elder surface


def test_login_clears_lingering_elder_keys(world: World) -> None:
    """#42 review HIGH, reverse direction: a real login after an elder session
    leaves no elder capability keys in the authenticated session."""
    mom = _member_with_login(world.m_pod, "Mom")
    client = _entered(world)  # an elder session first
    assert "elder_member_id" in client.session
    _login(client, mom)
    assert "elder_member_id" not in client.session
    assert "elder_generation" not in client.session


# --- one-tap named reactions (S-602) ---


def test_one_tap_react_is_named_and_feeds_reciprocity(world: World) -> None:
    client = _entered(world)
    post = Post.objects.get(body__startswith="MATERNAL")
    assert client.post(reverse("elder_react", args=[post.id])).status_code == 302
    reaction = Reaction.objects.get()
    assert reaction.member_id == world.nana.id and reaction.post_id == post.id
    body = client.get(reverse("elder_feed")).content.decode()
    assert "Nana Ann" in body  # attributed by name on the surface
    week_start = timezone.localdate() - datetime.timedelta(days=6)
    row = metrics.rollup_week(world.maternal, week_start)
    assert row.posts_responded == 1  # counts like any other reaction
    # And the cross-yard post 404s even with a valid session.
    far_post = Post.objects.get(body__startswith="PATERNAL")
    assert client.post(reverse("elder_react", args=[far_post.id])).status_code == 404


def test_bigger_text_toggle(world: World) -> None:
    client = _entered(world)
    assert "26px" not in client.get(reverse("elder_feed")).content.decode()
    client.post(reverse("elder_text_size"))
    assert "26px" in client.get(reverse("elder_feed")).content.decode()


# --- minting discipline (TM-10, T-EDGE-1) ---


def test_mint_refuses_supervised_members(world: World) -> None:
    child = Member.objects.create(display_name="Kid", is_supervised=True, role=Member.SUPERVISED)
    with pytest.raises(elder_tokens.ElderTokenRefused, match="supervised"):
        elder_tokens.mint(child)


def test_mint_refuses_an_insecure_production_base_url(world: World) -> None:
    with override_settings(BASE_URL="http://backyard.example.com"):
        with pytest.raises(elder_tokens.ElderTokenRefused, match="https"):
            elder_tokens.mint(world.poster)
    with override_settings(BASE_URL="https://backyard.example.com"):
        assert elder_tokens.mint(world.poster)  # https mints fine


# --- hygiene: headers and logs ---


def test_token_surface_headers_and_log_redaction(world: World) -> None:
    ok = Client().get(reverse("elder_enter", args=[world.raw]))
    missing = Client().get(reverse("elder_enter", args=["never-was"]))
    for response in (ok, missing):
        assert response["Cache-Control"] == "no-store"
        assert response["Referrer-Policy"] == "no-referrer"
        assert response["X-Robots-Tag"] == "noindex, nofollow"
    record = logging.LogRecord(
        name="django.request",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="Not Found: %s",
        args=("/t/secret-token-value/",),
        exc_info=None,
    )
    RedactCapabilityPaths().filter(record)
    assert "secret-token-value" not in record.getMessage()
    assert "/t/[redacted]" in record.getMessage()
