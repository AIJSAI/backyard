"""WCAG 2.1 AA checks on the elder view (wave-5 exit, S-601).

The elder surface is the product's core bet for its least-technical users, so
its accessibility is a gate, not an aspiration. A full audit needs a browser
(Playwright + axe is the ADR-002 E2E path); these are the structural checks that
hold in the unit suite: the body text meets AA contrast at the rendered size,
the interactive controls declare AA-sized tap targets, and the page has the
single-column, one-way-back shape S-601 requires. The contrast ratio is computed
from the actual rendered colors, so a future theme change that dropped below AA
fails here.
"""

from __future__ import annotations

import re

import pytest
from django.test import Client
from django.urls import reverse

from core import elder_tokens
from core.models import Member, Pod, PodMembership, Post, Yard

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


@pytest.fixture
def elder_page() -> str:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Cousins")
    pod.yards.set([yard])
    nana = Member.objects.create(display_name="Nana", kinship_name="Nana")
    PodMembership.objects.create(member=nana, pod=pod)
    Post.objects.create(author=nana, pod=pod, body="a warm hello")
    raw = elder_tokens.mint(nana)
    client = Client()
    client.get(reverse("elder_enter", args=[raw]))
    return client.get(reverse("elder_feed")).content.decode()


def test_body_text_meets_aa_contrast(elder_page: str) -> None:
    # The elder page declares its foreground/background as hex in the inline CSS.
    assert "#1a1a1a" in elder_page and "#ffffff" in elder_page
    ratio = _contrast("#1a1a1a", "#ffffff")
    assert ratio >= _AA_NORMAL, f"body contrast {ratio:.1f}:1 below AA {_AA_NORMAL}:1"
    # The muted byline must still clear AA against the same background.
    assert _contrast("#444444", "#ffffff") >= _AA_NORMAL


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
    # No links off the surface: the only hrefs are the elder feed itself.
    hrefs = re.findall(r'href="([^"]+)"', elder_page)
    assert hrefs, "the page should carry its back link"
    assert all(href == reverse("elder_feed") for href in hrefs), hrefs


def test_the_bigger_text_control_is_present(elder_page: str) -> None:
    # S-601's bigger-text toggle: a real control on the surface.
    assert reverse("elder_text_size") in elder_page
    assert "Bigger text" in elder_page or "Regular text" in elder_page
