"""Accessibility modes the browser turns on, and the affordances WCAG 2.2 adds.

These are the parts of the design that only exist for users nobody watches build the
product: someone on Windows High Contrast, someone who asked their OS for more
contrast, and someone who is stuck and needs a way to get help. All three are easy to
ship broken because the developer never sees them.

Every assertion here is on the SIDE EFFECT — the CSS or markup that must exist — not on
a function returning a value, because that is the class of test that passed 553 times
while passkey sign-in was dead.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db

_BASE = pathlib.Path(__file__).resolve().parents[1] / "templates" / "core" / "base.html"


def _style() -> str:
    match = re.search(r"<style[^>]*>(.*?)</style>", _BASE.read_text(), re.S)
    assert match, "no <style> block in base.html"
    return match.group(1)


def _block(name: str) -> str:
    """Return the body of a top-level @media block, brace-matched."""
    css = _style()
    start = css.index(name)
    depth, i = 0, css.index("{", start)
    for j in range(i, len(css)):
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return css[i + 1 : j]
    raise AssertionError(f"unbalanced braces after {name}")


def test_forced_colors_repairs_every_boundary_it_strips() -> None:
    """Forced-colors computes box-shadow and non-url() background-image to `none`.

    This design carries card boundaries in --shadow alone, the select arrow in two
    gradients, and both feed dividers in color-mix() — so in Windows High Contrast a
    member would see feed cards with no edges, a select with no arrow, and no
    "new since your last visit" divider at all. The repair must be present.
    """
    assert "@media (forced-colors: active)" in _style(), "no forced-colors support at all"
    body = _block("@media (forced-colors: active)")
    # The shadow-only surfaces need a real border.
    for hook in ("ul.feed > li", ".composer", ".handover"):
        assert hook in body, f"{hook} loses its only boundary in forced colours"
    assert "ButtonBorder" in body or "CanvasText" in body, "no system colour keywords used"
    # The gradient-drawn select arrow.
    assert "select" in body and "background-image: none" in body
    # The two color-mix()-painted dividers.
    assert "li.boundary::before" in body and ".caught-up::before" in body
    # Tint-only pills collapse into plain text without a border.
    assert ".role" in body


def test_forced_colors_never_redraws_the_focus_ring_with_a_shadow() -> None:
    # outline-color is force-ADJUSTED in forced colours; box-shadow computes to none.
    # Swapping the ring to a shadow — a common "modern" refactor — deletes the focus
    # indicator for exactly the users who most need it.
    css = _style()
    assert "outline: 3px solid var(--ring)" in css, "the outline focus ring is gone"
    ring_rule = css[css.index(":focus-visible") : css.index(":focus-visible") + 200]
    assert "box-shadow" not in ring_rule, "focus ring must not be drawn with box-shadow"


def test_prefers_contrast_is_honoured() -> None:
    assert "@media (prefers-contrast: more)" in _style()
    body = _block("@media (prefers-contrast: more)")
    assert "--line" in body and "--ink-soft" in body, "the ramp is not tightened"


def test_the_help_affordance_is_present_and_is_not_a_broken_link(client: Client) -> None:
    """WCAG 2.2 SC 3.2.6 Consistent Help.

    There is no help route in this app. A link to a page that does not exist is worse
    than no link, so the mechanism is a sentence naming the real person who can act.
    Assert both halves: the help text is there, AND it is not a link.
    """
    # `home` redirects to /setup/ until an admin exists, so use a surface that always
    # renders the shared frame.
    html = client.get(reverse("account_login")).content.decode()
    assert "Ask whoever in the family set this up" in html, "no help affordance"
    footer = html[html.index("<footer") : html.index("</footer>")]
    assert "<a " not in footer.split("help")[-1], "the help affordance must not link anywhere"


def test_the_help_affordance_is_in_the_same_place_on_every_surface(client: Client) -> None:
    # SC 3.2.6 is about CONSISTENT position, so it lives in the shared footer rather
    # than per-template. Prove it reaches surfaces that do not extend one another.
    for name in ("account_login", "account_signup", "account_reset_password"):
        html = client.get(reverse(name)).content.decode()
        assert "Ask whoever in the family set this up" in html, f"missing on {name}"


def test_the_elder_surface_is_excluded_from_all_of_it() -> None:
    """The elder page is standalone and its guard requires EVERY href on it — <link>
    elements included — to be the elder-feed URL. A nav, a skip link, a favicon link or
    a help link there reds the build. It is also the one surface deliberately exempt
    from the shared footer. Pin the exclusion so a future "consistency" pass does not
    helpfully add one."""
    elder = (_BASE.parent / "elder_feed.html").read_text()
    assert "{% extends" not in elder, "the elder page must stay standalone"
    for forbidden in ("<nav", "skip-link", 'rel="icon"', "Ask whoever in the family"):
        assert forbidden not in elder, f"{forbidden!r} must never appear on the elder page"


def test_the_rail_refactor_did_not_hoist_a_gated_link_out_of_its_condition() -> None:
    """The regression a markup refactor causes and a design review never catches.

    The v3.1 layout wrapped each page's wayfinding in a rail element. On members.html
    the "Family sides" link sits inside `{% if can_create_yard %}`; if the wrapper had
    been opened above that conditional and closed below it, or the link nudged outside
    while moving markup, an authorization-gated action would render for everyone. The
    page would look identical either way.

    Assert the gate still bites AND that nothing outside the rail gained a link.
    """
    import re

    from django.template.loader import render_to_string

    on = render_to_string("core/members.html", {"can_create_yard": True, "rows": []})
    off = render_to_string("core/members.html", {"can_create_yard": False, "rows": []})
    assert "Family sides" in on, "the gated link vanished entirely"
    assert "Family sides" not in off, "an authz-gated link now renders for everyone"
    # And it is inside the rail, not hoisted above it.
    nav = on[on.index('<nav class="rail"') : on.index("</nav>")]
    assert "Family sides" in nav
    # Everything after the rail must be identical in both states.
    assert re.findall(r'href="([^"]+)"', on.split("</nav>")[1]) == re.findall(
        r'href="([^"]+)"', off.split("</nav>")[1]
    ), "the gate changed something outside the rail"
