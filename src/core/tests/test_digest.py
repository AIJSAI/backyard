"""The per-recipient digest builder (S-501): the digest is provably the feed.

The properties under test are wave 4's heart: every content byte resolves
through the one audience query at build time (TM-2); one email per (member,
yard) with the bridge member's two emails string-level clean of each other
(T-YARD-9, the unrecallable fusion); the closed block union and BASE_URL-only
links are the 100%-family gate, proven non-vacuous by an injected foreign
block; deleted and narrowed content never ships through a build after the
change; the upcoming-dates section honors per-field visibility AND the yard
boundary; user content renders inert (T-EMAIL-8); and the TM-2 confinement
guard on digest.py trips from both sides.
"""

from __future__ import annotations

import datetime
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from django.utils import timezone

from core import digest, media
from core.models import DigestIssue, Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db

_REPO = Path(__file__).resolve().parents[3]
_CHECKER = _REPO / "scripts" / "check_digest_confinement.py"


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
    window_end = timezone.now() + datetime.timedelta(hours=1)
    return World(
        maternal=maternal,
        paternal=paternal,
        bridge_pod=bridge_pod,
        m_pod=m_pod,
        p_pod=p_pod,
        bridge=_member_in(bridge_pod, "Bridge parent"),
        maternal_cousin=_member_in(m_pod, "Maternal cousin"),
        paternal_cousin=_member_in(p_pod, "Paternal cousin"),
        window_start=window_end - datetime.timedelta(days=7),
        window_end=window_end,
    )


def _issue(world: World, member: Member, yard: Yard) -> DigestIssue:
    issue, _created = DigestIssue.objects.get_or_create(
        member=member,
        yard=yard,
        window_start=world.window_start,
        defaults={"window_end": world.window_end},
    )
    return issue


def _build(world: World, member: Member, yard: Yard) -> digest.DigestEmail:
    return digest.build_digest(
        _issue(world, member, yard), digest_token="digest-raw", unsubscribe_token="unsub-raw"
    )


def _post(author: Member, pod: Pod, body: str, *, yards: list[Yard] | None = None) -> Post:
    post = Post.objects.create(author=author, pod=pod, body=body)
    if yards:
        post.audience_yards.set(yards)
    return post


# --- one email per (member, yard); the bridge member's two never fuse ---


def test_every_member_of_the_founding_shape_gets_a_clean_yard_digest(world: World) -> None:
    """String-level cross-yard ABSENCE for every (member, yard) pair, never just
    a route check: no paternal body, name, or pod name in any maternal digest."""
    _post(world.maternal_cousin, world.m_pod, "MAT-BODY yard news", yards=[world.maternal])
    _post(world.paternal_cousin, world.p_pod, "PAT-BODY yard news", yards=[world.paternal])
    paternal_markers = ("PAT-BODY", "Paternal cousin", "Paternal cousins", "Paternal:")
    maternal_markers = ("MAT-BODY", "Maternal cousin", "Maternal cousins", "Maternal:")

    for member in (world.bridge, world.maternal_cousin):
        built = _build(world, member, world.maternal)
        for rendering in (built.text, built.html, built.subject):
            for marker in paternal_markers:
                assert marker not in rendering, (member.display_name, marker)
    for member in (world.bridge, world.paternal_cousin):
        built = _build(world, member, world.paternal)
        for rendering in (built.text, built.html, built.subject):
            for marker in maternal_markers:
                assert marker not in rendering, (member.display_name, marker)


def test_bridge_pod_content_appears_on_both_sides_without_fusion(world: World) -> None:
    """The household pod spans both yards; each side's email carries it, and
    neither carries the other yard's own content (the sanctioned builder rule)."""
    _post(world.bridge, world.bridge_pod, "HOUSEHOLD-NOTE for both sides")
    maternal_built = _build(world, world.bridge, world.maternal)
    paternal_built = _build(world, world.bridge, world.paternal)
    assert "HOUSEHOLD-NOTE" in maternal_built.text
    assert "HOUSEHOLD-NOTE" in paternal_built.text  # the pod spans...
    assert "Paternal" not in maternal_built.text  # ...the yard never fuses
    assert "Maternal" not in paternal_built.text


# --- the 100%-family gate, proven from both sides ---


def test_all_blocks_are_of_the_closed_union_and_links_stay_home(world: World) -> None:
    _post(world.maternal_cousin, world.m_pod, "a post", yards=[world.maternal])
    built = _build(world, world.maternal_cousin, world.maternal)
    for block in built.blocks:
        assert isinstance(block, digest._BLOCK_UNION)
    assert 'href="http://localhost:8000/' in built.html
    # Every href and src in the rendered HTML is on the instance's own origin.
    import re

    for url in re.findall(r'(?:href|src)="([^"]+)"', built.html):
        assert url.startswith("http://localhost:8000/"), url


def test_the_gate_trips_on_an_injected_foreign_block(world: World) -> None:
    """Non-vacuity: the gate FAILS a block outside the union and an off-origin
    link, so 'no promo ever' is a property, not a habit."""

    @dataclass(frozen=True)
    class PromoBlock:
        pitch: str

    good = digest.HeaderBlock(yard_name="Y", window_text="w")
    with pytest.raises(digest.NonFamilyContent, match="closed union"):
        digest.validate_blocks((good, PromoBlock(pitch="buy things")))  # type: ignore[arg-type]
    with pytest.raises(digest.NonFamilyContent, match="off-origin"):
        digest.validate_blocks(
            (
                digest.FooterBlock(
                    digest_url="https://tracker.example/e?u=1",
                    unsubscribe_url="http://localhost:8000/digest/unsubscribe/x/",
                    standing_text="s",
                ),
            )
        )


# --- live state at build time (TM-2) ---


def test_deleted_and_narrowed_content_never_ships(world: World) -> None:
    doomed = _post(world.bridge, world.bridge_pod, "DOOMED-BODY", yards=[world.maternal])
    narrowed = _post(world.maternal_cousin, world.m_pod, "NARROWED-BODY", yards=[world.maternal])
    before = _build(world, world.bridge, world.maternal)
    assert "DOOMED-BODY" in before.text and "NARROWED-BODY" in before.text  # positive control

    doomed.deleted_at = timezone.now()
    doomed.save(update_fields=["deleted_at"])
    narrowed.audience_yards.clear()  # pod-only in a pod the bridge is not in

    after = _build(world, world.bridge, world.maternal)
    assert "DOOMED-BODY" not in after.text and "DOOMED-BODY" not in after.html
    assert "NARROWED-BODY" not in after.text and "NARROWED-BODY" not in after.html


# --- the upcoming-dates section: per-field visibility AND the yard boundary ---


def test_dates_section_honors_visibility_and_the_yard_boundary(world: World) -> None:
    soon = timezone.localdate() + datetime.timedelta(days=2)
    for member, visibility in (
        (world.maternal_cousin, Member.YARD),  # visible to the maternal digest
        (world.paternal_cousin, Member.YARD),  # other yard: never in a maternal digest
    ):
        member.birthday_month, member.birthday_day = soon.month, soon.day
        member.birthday_year = 1950
        member.birthday_visibility = visibility
        member.save()
    world.bridge.birthday_month, world.bridge.birthday_day = soon.month, soon.day
    world.bridge.birthday_visibility = Member.POD  # POD-scoped: only pod-mates see it
    world.bridge.save()

    built = _build(world, world.maternal_cousin, world.maternal)
    assert "Maternal cousin" in built.text  # own-yard, YARD-visible date shows
    assert "Paternal cousin" not in built.text  # cross-yard date never crosses
    assert "Bridge parent" not in built.text  # POD-scoped date hidden from a non-pod-mate
    assert "1950" not in built.text and "1950" not in built.html  # never a year

    # The bridge's pod-mate WOULD see the POD-scoped date (positive control) —
    # through the same builder, in the household's own yard digest.
    housemate = _member_in(world.bridge_pod, "Housemate")
    housemate_built = _build(world, housemate, world.maternal)
    assert "Bridge parent" in housemate_built.text


# --- injection and photo degradation ---


def test_user_content_renders_inert(world: World) -> None:
    _post(
        world.maternal_cousin,
        world.m_pod,
        '<script>alert("hi")</script> & <img src="https://evil.example/x">',
        yards=[world.maternal],
    )
    crafted = world.maternal_cousin
    crafted.kinship_name = "Nana\r\nBcc: x"
    crafted.save(update_fields=["kinship_name"])
    built = _build(world, world.maternal_cousin, world.maternal)
    assert "<script>" not in built.html  # autoescaped
    assert "https://evil.example" not in [
        url for url in built.html.split('"') if url.startswith("http")
    ]  # a crafted img URL is inert text, never an attribute
    assert "\r" not in built.subject and "\n" not in built.subject


def test_photos_degrade_to_the_deep_link_never_a_media_url(world: World) -> None:
    """The sanctioned wave-3<->4 coupling: media renders as a photo count on the
    /d/ deep link; the digest mints no media-signing path of its own."""
    import io

    from PIL import Image

    post = _post(world.maternal_cousin, world.m_pod, "with a photo", yards=[world.maternal])
    buf = io.BytesIO()
    Image.new("RGB", (30, 30), (1, 2, 3)).save(buf, format="JPEG")
    media.ingest_photo(post=post, raw=buf.getvalue())

    built = _build(world, world.maternal_cousin, world.maternal)
    assert "1 photo" in built.text
    assert "/media/" not in built.html and "/media/" not in built.text
    assert f"/d/digest-raw/posts/{post.id}/" in built.text


# --- the TM-2 confinement guard trips from both sides ---


def test_digest_confinement_guard_is_green_and_non_vacuous(tmp_path: Path) -> None:
    clean = subprocess.run(  # noqa: S603  # fixed args: our own checker script
        [sys.executable, str(_CHECKER)], capture_output=True, text=True, check=False
    )
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "self-tested" in clean.stdout

    poisoned = tmp_path / "digest.py"
    poisoned.write_text("posts = Post.objects.all()\n")
    tripped = subprocess.run(  # noqa: S603  # fixed args: our own checker script
        [sys.executable, str(_CHECKER), str(poisoned)], capture_output=True, text=True, check=False
    )
    assert tripped.returncode == 1
    assert "CONFINEMENT VIOLATION" in tripped.stdout


def test_plain_text_part_is_not_entity_escaped(world: World) -> None:
    """Security review of #37 MEDIUM-1: text/plain is never HTML-interpreted, so
    Ann O'Hara and Tom & Jerry must arrive as written, while the HTML part keeps
    autoescape on."""
    _post(
        world.maternal_cousin,
        world.m_pod,
        'Tom & Jerry\'s "party" <3',
        yards=[world.maternal],
    )
    built = _build(world, world.maternal_cousin, world.maternal)
    for entity in ("&amp;", "&#x27;", "&quot;"):
        assert entity not in built.text
    assert 'Tom & Jerry\'s "party" <3' in built.text
    assert "&amp;" in built.html  # the HTML part stays escaped


def test_confinement_guard_catches_traversal_and_multi_name_import(tmp_path: Path) -> None:
    """Security review of #37 MEDIUM-2 + LOW-3: the guard trips on the repo's own
    HIGH-1 leak class (raw related-manager walks) and on the natural drift of
    appending a model to the existing import line."""
    for poison_line in (
        "count = post.media_assets.count()\n",
        "walked = issue.member.pods.all()\n",
        "from .models import DigestIssue, Post\n",
    ):
        poisoned = tmp_path / "digest.py"
        poisoned.write_text(poison_line)
        tripped = subprocess.run(  # noqa: S603  # fixed args: our own checker script
            [sys.executable, str(_CHECKER), str(poisoned)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert tripped.returncode == 1, poison_line
