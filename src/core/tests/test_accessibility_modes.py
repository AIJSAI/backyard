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
    # Anchor BOTH assertions on the rule body. Reading the whole stylesheet was a
    # false green: `_style()` includes comments, and the comment beside the
    # forced-colors block quotes this exact declaration, so the test passed on prose
    # while the only focus indicator in the app could be deleted outright.
    css = _style()
    ring_rule = css[css.index(":focus-visible") : css.index(":focus-visible") + 200]
    assert "outline: 3px solid var(--ring)" in ring_rule, "the outline focus ring is gone"
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
    assert "<a " not in footer, "the footer carries no links; the help affordance must not add one"


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


def test_error_blocks_are_distinguishable_from_notices_without_colour() -> None:
    """`.errors` and `.notice` share a shape and differ only by tint — and forced colours
    erase the tint, which made a failure block pixel-identical to a neutral one on the
    break-glass, first-run-setup and invite-redemption surfaces. Severity must survive
    without colour, so `.errors` carries a glyph in EVERY mode plus a heavier border in
    forced colours."""
    css = _style()
    assert ".errors::before" in css, "an error block must carry a non-colour severity cue"
    body = _block("@media (forced-colors: active)")
    assert ".errors { border: 2px solid CanvasText; }" in body, "errors must outweigh a notice"


def test_the_handover_qr_opts_out_of_forced_colours() -> None:
    """The QR encodes an access token and the operator is told to print the page. Chromium
    forces the plate to Canvas but does NOT force the SVG fill, so in a dark forced-colours
    theme the code went black-on-black and unscannable. A QR is data, not decoration."""
    css = _style()
    assert "forced-color-adjust: none" in css, "the QR must opt out of forced colours"
    assert ".qr svg path { fill: #000000; }" in css, "the QR modules need an explicit fill"


def test_the_select_keeps_an_arrow_in_forced_colours() -> None:
    # The gradient-drawn arrow is erased in forced colours; suppressing `appearance` as
    # well would leave the control with no dropdown indicator at all. Hand it back.
    body = _block("@media (forced-colors: active)")
    assert "appearance: auto" in body, "the select loses its arrow entirely in forced colours"


def test_prefers_contrast_beats_a_manual_theme_choice() -> None:
    """A media query adds NO specificity. `:root` is (0,0,1); the `:root[data-theme=…]`
    blocks are (0,1,1) and redefine the same two tokens — so the tightening died the
    moment someone picked a theme by hand. Latent today (nothing sets data-theme yet),
    which is exactly why it needed pinning before the toggle ships."""
    body = _block("@media (prefers-contrast: more)")
    for selector in (':root[data-theme="light"]', ':root[data-theme="dark"]'):
        assert selector in body, f"{selector} outranks :root here and would win"


def test_no_page_gives_two_controls_the_same_accessible_name() -> None:
    """A class of defect axe does not report and a sighted review cannot see.

    The profile form carries five visibility selects. They began life with
    field-specific aria-labels ("Who can see my phone"); the v3.2 visual pass replaced
    those with a VISIBLE label, which was the right call for sighted users and, in its
    first cut, gave all five the identical name "Who can see it". A screen-reader user
    pulling up the form-controls list then sees five indistinguishable selects. axe
    reports nothing — duplicate names are not a violation of any single success
    criterion — so only a human reading the markup, or this test, catches it.

    Asserted on the RENDERED page rather than the template, because the names are built
    from a loop and a template read would not prove what a browser receives.
    """
    import re

    from django.template.loader import render_to_string

    from core.models import Member

    html = render_to_string(
        "core/profile_edit.html",
        {"member": Member(display_name="Priya"), "visibility_choices": [("no_one", "No one")]},
    )
    # Every <label for="..."> is the accessible name of the control it points at.
    labels = re.findall(r'<label for="([^"]+)"[^>]*>(.*?)</label>', html, re.S)
    names: dict[str, str] = {}
    duplicates: list[str] = []
    for control_id, text in labels:
        name = " ".join(re.sub(r"<[^>]+>", "", text).split())
        if name in names.values():
            duplicates.append(f"{name!r} labels both {control_id} and another control")
        names[control_id] = name
    assert not duplicates, "two controls share an accessible name:\n" + "\n".join(duplicates)
    # Non-vacuity: the page really does render the five visibility selects this guards.
    assert sum(1 for n in names.values() if n.startswith("Who can see")) == 5, names
