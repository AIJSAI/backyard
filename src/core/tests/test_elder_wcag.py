"""WCAG contrast and structure checks on the elder view (wave-5 exit, S-601).

The elder surface is the product's core bet for its least-technical users, so
its accessibility is a gate, not an aspiration. These are the three criteria the
unit suite can compute: body-text contrast meets AA (1.4.3) at the rendered
size, interactive controls declare tap targets past the WCAG 2.2 AA 24px minimum
(2.5.8), and the page has the single-column, one-way-back shape S-601 requires.
The contrast ratio is computed from the actual rendered colors, so a future theme
change that dropped below AA fails here. Full AA (keyboard operability, focus
visibility, labels, the rest) needs the browser audit (Playwright + axe, the
ADR-002 E2E path), which stays post-close.
"""

from __future__ import annotations

import io
import re

import pytest
from django.test import Client
from django.urls import reverse
from PIL import Image

from core import elder_tokens, media
from core.models import Comment, MediaAsset, Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db

# AA thresholds (WCAG 2.1): 4.5:1 for normal text, 3:1 for large text (>=18.66px
# bold or >=24px). The elder body is >=21px, so it clears the large-text bar and
# we hold it to the stricter normal-text bar anyway.
_AA_NORMAL = 4.5
_MIN_TAP_PX = 44  # the AAA 2.5.5 target size; the elder view aims higher (48)


def _relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(fg: str, bg: str) -> float:
    a, b = _relative_luminance(fg), _relative_luminance(bg)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def _jpeg() -> bytes:
    """A tiny real JPEG: media.ingest_photo re-encodes, so it must actually decode."""
    buf = io.BytesIO()
    Image.new("RGB", (80, 60), (30, 92, 70)).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def elder_page() -> str:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Cousins")
    pod.yards.set([yard])
    nana = Member.objects.create(display_name="Nana", kinship_name="Nana")
    PodMembership.objects.create(member=nana, pod=pod)
    post = Post.objects.create(author=nana, pod=pod, body="a warm hello")
    # The post carries a photo, a finished video, a still-transcoding video and a reply.
    # Without them every guard below inspected a page whose photo, video and reply markup
    # had NEVER been rendered: the S-601 no-dead-ends assertion scans hrefs in the
    # rendered string, and an empty {% for %} emits none, so the branch that the
    # template's own comment claims is pinned by this suite was invisible to it.
    media.ingest_photo(post=post, raw=_jpeg())
    done = media.ingest_photo(post=post, raw=_jpeg())
    MediaAsset.objects.filter(pk=done.pk).update(
        media_kind=MediaAsset.VIDEO, transcode_status=MediaAsset.DONE
    )
    pending = media.ingest_photo(post=post, raw=_jpeg())
    MediaAsset.objects.filter(pk=pending.pk).update(
        media_kind=MediaAsset.VIDEO, transcode_status=MediaAsset.PENDING
    )
    Comment.objects.create(post=post, author=nana, body="She caught the biggest fish.")
    raw = elder_tokens.mint(nana)
    client = Client()
    client.get(reverse("elder_enter", args=[raw]))
    return client.get(reverse("elder_feed")).content.decode()


def test_the_fixture_actually_renders_the_media_and_reply_markup() -> None:
    """Non-vacuity guard for every other test in this file.

    The S-601 dead-end assertion and the tap-target scan only constrain markup that is
    actually on the page. If the fixture ever stops producing a photo, a video or a
    reply, those guards silently narrow to the empty case and keep passing — which is
    exactly what they did until this fixture grew media. Asserting the page's shape here
    means that regression fails loudly instead.
    """
    # Rebuilt inline rather than taking the fixture, so this test cannot be satisfied by
    # the same accident it exists to detect.
    yard = Yard.objects.create(name="Probe", slug="probe-yard")
    pod = Pod.objects.create(name="Probe pod")
    pod.yards.set([yard])
    nana = Member.objects.create(display_name="Nana", kinship_name="Nana")
    PodMembership.objects.create(member=nana, pod=pod)
    post = Post.objects.create(author=nana, pod=pod, body="a warm hello")
    asset = media.ingest_photo(post=post, raw=_jpeg())
    Comment.objects.create(post=post, author=nana, body="She caught the biggest fish.")
    client = Client()
    client.get(reverse("elder_enter", args=[elder_tokens.mint(nana)]))
    page = client.get(reverse("elder_feed")).content.decode()

    assert reverse("serve_media", args=[asset.token]) in page  # a real photo URL
    assert '<img class="photo"' in page
    assert "She caught the biggest fish." in page  # the reply reached her


def test_body_text_meets_aa_contrast(elder_page: str) -> None:
    # Parse the body rule's actual foreground/background roles (#45 review LOW-4),
    # not mere substring presence, so a theme that dropped body text below AA
    # while keeping #1a1a1a on a border still fails here.
    body_rule = re.search(r"body\s*\{([^}]*)\}", elder_page)
    assert body_rule, "no body CSS rule on the elder page"
    fg = re.search(r"color:\s*(#[0-9a-fA-F]{6})", body_rule.group(1))
    bg = re.search(r"background:\s*(#[0-9a-fA-F]{6})", body_rule.group(1))
    assert fg and bg, "body rule missing explicit color/background"
    ratio = _contrast(fg.group(1), bg.group(1))
    assert ratio >= _AA_NORMAL, f"body contrast {ratio:.1f}:1 below AA {_AA_NORMAL}:1"
    assert ratio >= 17.0  # the intended high-contrast elder palette, pinned
    # The muted byline must still clear AA against the same background.
    assert _contrast("#444444", bg.group(1)) >= _AA_NORMAL


def test_tap_targets_declare_an_aa_size(elder_page: str) -> None:
    heights = [int(px) for px in re.findall(r"min-height:\s*(\d+)px", elder_page)]
    widths = [int(px) for px in re.findall(r"min-width:\s*(\d+)px", elder_page)]
    assert heights and widths, "no min tap-target dimensions declared"
    assert min(heights) >= _MIN_TAP_PX and min(widths) >= _MIN_TAP_PX


def test_the_view_has_no_dead_end_shape(elder_page: str) -> None:
    # A single readable column: one <main>, and every screen has one obvious way
    # back to the feed (S-601, no navigation dead ends).
    assert elder_page.count("<main") == 1
    assert reverse("elder_feed") in elder_page  # the back-to-the-top link
    # No links off the surface: the only hrefs are the elder feed itself. Match BOTH
    # quoting styles — a single-quoted href slipped this guard entirely, so the
    # invariant was being enforced by quoting style rather than by content.
    # Match each quoting style as its own alternative rather than one class of both:
    # `[^"\']+` stops at EITHER quote, so `href="/e/…'…"` would capture only the prefix
    # before the apostrophe — and since the elder feed URL is just `/e/`, a truncated
    # capture can equal it and pass. Alternation captures the whole value.
    hrefs = [
        m.group(1) if m.group(1) is not None else m.group(2)
        for m in re.finditer(r'href=(?:"([^"]*)"|\'([^\']*)\')', elder_page)
    ]
    assert hrefs, "the page should carry its back link"
    assert all(href == reverse("elder_feed") for href in hrefs), hrefs
    # An href is not the only way off a page: `formaction` navigates exactly like one,
    # and a meta refresh leaves without either. Neither is ever legitimate here, and
    # this is the surface where a stray outbound link would carry an elder's session.
    assert "formaction" not in elder_page
    assert "http-equiv" not in elder_page


def test_the_bigger_text_control_is_present(elder_page: str) -> None:
    # S-601's bigger-text toggle: a real control on the surface.
    assert reverse("elder_text_size") in elder_page
    assert "Bigger text" in elder_page or "Regular text" in elder_page
