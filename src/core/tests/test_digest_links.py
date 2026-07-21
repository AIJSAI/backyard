"""The /d/ read surface and its token family (ADR-003, TM-5, T-TOKEN-2).

The isolation matrix grows a new request class: digest deep links. Properties
under test — the token only authenticates and every render re-resolves through
the one audience query live (deleted, narrowed, cross-yard content never ships
through a still-valid link); unknown and revoked tokens are byte-identical 404s
while genuine-but-expired gets the capability-free friendly page; the surface is
read-only and mints no session; the capability ceiling is the issue's own yard
slice; request logs never carry a token (TS-EDGE-LOG); and revocation kills the
class both by generation and by row (TM-1).
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from config.log_redaction import RedactCapabilityPaths
from core import digest_links, revocation
from core.models import DigestIssue, DigestToken, Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db


def _member_in(pod: Pod, name: str) -> Member:
    member = Member.objects.create(display_name=name)
    PodMembership.objects.create(member=member, pod=pod)
    return member


@dataclass
class World:
    maternal: Yard
    paternal: Yard
    bridge_pod: Pod
    m_pod: Pod
    p_pod: Pod
    bridge: Member
    maternal_cousin: Member
    paternal_cousin: Member
    window_start: datetime.datetime
    window_end: datetime.datetime
    issue: DigestIssue  # the bridge member's MATERNAL issue
    raw: str  # its live token


@pytest.fixture
def world() -> World:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    bridge_pod = Pod.objects.create(name="Bridge household")
    bridge_pod.yards.set([maternal, paternal])
    m_pod = Pod.objects.create(name="Maternal cousins")
    m_pod.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal cousins")
    p_pod.yards.set([paternal])
    bridge = _member_in(bridge_pod, "Bridge parent")
    # The window closes an hour from now so posts created during the test sit
    # inside it; the window-bound test moves a post before window_start instead.
    window_end = timezone.now() + datetime.timedelta(hours=1)
    window_start = window_end - datetime.timedelta(days=7)
    issue = DigestIssue.objects.create(
        member=bridge, yard=maternal, window_start=window_start, window_end=window_end
    )
    return World(
        maternal=maternal,
        paternal=paternal,
        bridge_pod=bridge_pod,
        m_pod=m_pod,
        p_pod=p_pod,
        bridge=bridge,
        maternal_cousin=_member_in(m_pod, "Maternal cousin"),
        paternal_cousin=_member_in(p_pod, "Paternal cousin"),
        window_start=window_start,
        window_end=window_end,
        issue=issue,
        raw=digest_links.mint(issue),
    )


def _post(author: Member, pod: Pod, body: str, *, yards: list[Yard] | None = None) -> Post:
    post = Post.objects.create(author=author, pod=pod, body=body)
    if yards:
        post.audience_yards.set(yards)
    return post


# --- the slice: a FILTER over the one query, never a second audience path ---


def test_issue_covers_this_yard_only_and_bridge_pod_content(world: World) -> None:
    in_yard = _post(
        world.maternal_cousin, world.m_pod, "maternal yard news", yards=[world.maternal]
    )
    pod_only_bridge = _post(world.bridge, world.bridge_pod, "household pod-only note")
    far_side = _post(
        world.paternal_cousin, world.p_pod, "paternal yard news", yards=[world.paternal]
    )
    foreign_pod_only = _post(world.maternal_cousin, world.m_pod, "cousins pod-only chat")

    bodies = {post.body for post in digest_links.issue_posts(world.issue)}
    assert in_yard.body in bodies  # this yard's section
    assert pod_only_bridge.body in bodies  # the bridge pod spans; the yard never fuses
    assert far_side.body not in bodies  # the OTHER side of a bridge member's world
    assert foreign_pod_only.body not in bodies  # someone else's pod stays theirs


def test_live_state_wins_over_a_still_valid_link(world: World) -> None:
    """Deleted and narrowed content is absent from a link minted before the change."""
    doomed = _post(world.bridge, world.bridge_pod, "soon deleted", yards=[world.maternal])
    narrowed = _post(world.maternal_cousin, world.m_pod, "soon narrowed", yards=[world.maternal])
    url = reverse("digest_web", args=[world.raw])
    body = Client().get(url).content.decode()
    assert "soon deleted" in body and "soon narrowed" in body  # positive control

    doomed.deleted_at = timezone.now()
    doomed.save(update_fields=["deleted_at"])
    narrowed.audience_yards.clear()  # now pod-only in a pod the bridge is not in

    body = Client().get(url).content.decode()
    assert "soon deleted" not in body and "soon narrowed" not in body
    detail = Client().get(reverse("digest_web_post", args=[world.raw, doomed.id]))
    assert detail.status_code == 404  # deletion beats the artifact


def test_window_bounds_the_slice(world: World) -> None:
    old = _post(world.bridge, world.bridge_pod, "before the window")
    Post.objects.filter(pk=old.pk).update(
        created_at=world.window_start - datetime.timedelta(days=1)
    )
    assert "before the window" not in {p.body for p in digest_links.issue_posts(world.issue)}


# --- failure shapes (T-TOKEN-2) ---


def test_unknown_and_revoked_tokens_are_byte_identical_404s(world: World) -> None:
    revoked_issue = DigestIssue.objects.create(
        member=world.bridge,
        yard=world.paternal,
        window_start=world.window_start,
        window_end=world.window_end,
    )
    revoked_raw = digest_links.mint(revoked_issue)
    Member.objects.filter(pk=world.bridge.pk).update(token_generation=99)

    unknown = Client().get(reverse("digest_web", args=["never-was-a-token"]))
    revoked = Client().get(reverse("digest_web", args=[revoked_raw]))
    assert unknown.status_code == revoked.status_code == 404
    assert unknown.content == revoked.content  # revocation never reveals


def test_expired_gets_the_friendly_page_but_revoked_and_expired_is_404(world: World) -> None:
    DigestToken.objects.all().update(expires_at=timezone.now() - datetime.timedelta(days=1))
    _post(world.bridge, world.bridge_pod, "window content stays private")
    expired = Client().get(reverse("digest_web", args=[world.raw]))
    assert expired.status_code == 410
    body = expired.content.decode()
    assert "Ask your family for a fresh one" in body
    assert "window content stays private" not in body  # capability-free
    # A token both revoked AND expired is a bare 404: the generation check runs first.
    Member.objects.filter(pk=world.bridge.pk).update(token_generation=99)
    assert Client().get(reverse("digest_web", args=[world.raw])).status_code == 404


# --- read-only, no session, capability ceiling ---


def test_the_surface_is_read_only_and_mints_no_session(world: World) -> None:
    client = Client()
    url = reverse("digest_web", args=[world.raw])
    assert client.get(url).status_code == 200
    assert client.post(url).status_code == 405  # GET-only routes, proven not implied
    post = _post(world.bridge, world.bridge_pod, "a post")
    assert client.post(reverse("digest_web_post", args=[world.raw, post.id])).status_code == 405
    # Holding a digest token grants nothing on the session surfaces.
    response = client.get(reverse("feed"))
    assert response.status_code == 302  # still anonymous: bounced to login
    assert client.post(reverse("add_comment", args=[post.id]), {"body": "hi"}).status_code in (
        302,
        404,
    )  # no write path opens


def test_capability_ceiling_is_the_issue_slice(world: World) -> None:
    """A valid maternal-issue token cannot read the bridge member's paternal-yard
    post, even though the MEMBER could see it on the web: the token is scoped to
    the digest it came from, not to the member's whole world."""
    far_side = _post(world.bridge, world.bridge_pod, "paternal-only send", yards=[world.paternal])
    response = Client().get(reverse("digest_web_post", args=[world.raw, far_side.id]))
    assert response.status_code == 404
    unknown = Client().get(reverse("digest_web_post", args=[world.raw, 9_999_999]))
    assert response.content == unknown.content  # outside-ceiling == not-exists


def test_token_hygiene_headers(world: World) -> None:
    response = Client().get(reverse("digest_web", args=[world.raw]))
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert response["Referrer-Policy"] == "no-referrer"
    assert response["Cache-Control"] == "no-store"
    assert Client().get(reverse("robots")).content == b"User-agent: *\nDisallow: /\n"


# --- revocation kills the class twice over (TM-1) ---


def test_revocation_kills_digest_links_by_row_and_by_generation(world: World) -> None:
    url = reverse("digest_web", args=[world.raw])
    assert Client().get(url).status_code == 200
    revocation.revoke_member_credentials(world.bridge)
    assert Client().get(url).status_code == 404  # dead after the one revocation act
    assert not DigestToken.objects.filter(member=world.bridge).exists()  # rows gone too
    # A bare generation bump alone (no row deletion) also kills a pre-minted link.
    issue2 = DigestIssue.objects.create(
        member=world.maternal_cousin,
        yard=world.maternal,
        window_start=world.window_start,
        window_end=world.window_end,
    )
    raw2 = digest_links.mint(issue2)
    Member.objects.filter(pk=world.maternal_cousin.pk).update(token_generation=42)
    assert Client().get(reverse("digest_web", args=[raw2])).status_code == 404


# --- TS-EDGE-LOG: tokens never reach the log stream ---


def test_request_log_redaction_covers_the_404_paths() -> None:
    """The filter rewrites the exact record shape django.request emits for the
    guaranteed cases: an expired/mistyped /d/ link, and every other capability
    route. Exercised on the formatted message so arg-shape variants cannot slip."""
    redactor = RedactCapabilityPaths()
    cases = [
        "Not Found: /d/AbC123secret/",
        "Not Found: /d/AbC123secret/posts/5/",
        "Not Found: /digest/confirm/xyzTOKEN/",
        "Not Found: /digest/unsubscribe/xyzTOKEN/",
        "Not Found: /join/xyzTOKEN/",
        "Not Found: /media/xyzTOKEN/",
        "Not Found: /break-glass/uid64/tokenvalue/",
    ]
    for message in cases:
        record = logging.LogRecord(
            name="django.request",
            level=logging.WARNING,
            pathname=__file__,
            lineno=1,
            msg="Not Found: %s",
            args=(message.removeprefix("Not Found: "),),
            exc_info=None,
        )
        assert redactor.filter(record) is True
        formatted = record.getMessage()
        for secret in ("secret", "TOKEN", "tokenvalue", "uid64"):
            assert secret not in formatted, formatted
        assert "[redacted]" in formatted
    # Non-capability paths pass through untouched (the filter never eats signal).
    record = logging.LogRecord(
        name="django.request",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="Not Found: %s",
        args=("/directory/5/",),
        exc_info=None,
    )
    redactor.filter(record)
    assert record.getMessage() == "Not Found: /directory/5/"


def test_settings_wire_the_redaction_filter() -> None:
    """The LOGGING config attaches the filter to django.request and
    django.security handlers; a future settings edit that drops it fails here."""
    from typing import Any, cast

    from django.conf import settings

    logging_config = cast(dict[str, Any], settings.LOGGING)
    assert "redact_capability_paths" in logging_config["filters"]
    for logger_name in ("django.request", "django.security"):
        handlers = logging_config["loggers"][logger_name]["handlers"]
        for handler_name in handlers:
            assert "redact_capability_paths" in logging_config["handlers"][handler_name]["filters"]
