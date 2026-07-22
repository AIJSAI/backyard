"""WCAG 2.1 contrast guard on the shared design system (PATH-TO-100 item 3).

The member-app palette lives as CSS custom properties in `core/base.html` (a
warm light theme plus a dark override). This test parses those tokens from the
template and computes the real WCAG contrast ratio for every foreground/background
pairing the stylesheet actually renders, in BOTH themes. A future theme change
that dropped any text pair below AA fails here — the same non-vacuous posture as
the elder view's `test_elder_wcag`, extended to the whole system.

Scope: this proves criterion 1.4.3 (contrast) for the token palette. The rest of
AA (keyboard operability, focus visibility, labels, target size in a real
viewport) is asserted structurally elsewhere and, end to end, by the browser
audit (Playwright + axe) on the ADR-002 e2e path.
"""

from __future__ import annotations

import pathlib
import re

_BASE = pathlib.Path(__file__).resolve().parents[1] / "templates" / "core" / "base.html"

# WCAG 2.1 AA: 4.5:1 for normal text, 3:1 for large text (>=24px, or >=18.66px
# bold). Everything below carries body-size or smaller text, so we hold every
# pair to the stricter normal-text bar.
_AA = 4.5


def _relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(fg: str, bg: str) -> float:
    a, b = _relative_luminance(fg), _relative_luminance(bg)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def _resolve(block: str) -> dict[str, str]:
    """Parse `--name: #hex;` and `--name: var(--other);` tokens from one rule body,
    resolving var() references to their hex (one pass suffices: refs point at hex)."""
    raw: dict[str, str] = {}
    for name, value in re.findall(
        r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6}|var\(--[a-z0-9-]+\))", block
    ):
        raw[name] = value
    resolved: dict[str, str] = {}
    for name, value in raw.items():
        ref = re.fullmatch(r"var\(--([a-z0-9-]+)\)", value)
        resolved[name] = raw.get(ref.group(1), value) if ref else value
    return {k: v for k, v in resolved.items() if v.startswith("#")}


def _themes() -> dict[str, dict[str, str]]:
    src = _BASE.read_text()
    root = re.search(r":root\s*\{(.*?)\}", src, re.S)
    assert root, "no :root token block found in base.html"
    light = _resolve(root.group(1))
    dark_block = re.search(r"prefers-color-scheme:\s*dark\s*\)\s*\{\s*:root\s*\{(.*?)\}", src, re.S)
    assert dark_block, "no dark-theme :root override found in base.html"
    dark = {**light, **_resolve(dark_block.group(1))}  # dark redefines the color tokens
    return {"light": light, "dark": dark}


# (foreground token, background token) — every text pairing the stylesheet renders.
_PAIRS: list[tuple[str, str]] = [
    ("ink", "paper"),  # body text on the page ground
    ("ink", "surface"),  # text inside cards (feed, post, composer, handover)
    ("ink", "surface-sunk"),  # readonly fields, insets
    ("ink", "green-tint"),  # notice / house-rule body text
    ("ink", "danger-tint"),  # error-block body text
    ("ink-soft", "paper"),  # muted text, bylines, footer
    ("ink-soft", "surface"),  # muted text inside cards
    ("ink-soft", "surface-sunk"),  # empty-state, clip-status
    ("green", "paper"),  # links
    ("green", "surface"),  # links inside cards
    ("green", "green-tint"),  # .role pill, .actions hover text
    ("green", "surface-sunk"),  # .preview-url
    ("amber", "paper"),  # the new-since boundary label
    ("amber", "amber-tint"),  # .flag pill, .date-banner text
    ("danger", "paper"),  # .danger button label
    ("danger", "surface"),  # .danger button inside a card row
    ("btn-ink", "btn-bg"),  # primary button label
]


def test_every_text_pair_meets_aa_in_both_themes() -> None:
    themes = _themes()
    failures: list[str] = []
    for theme, tokens in themes.items():
        for fg, bg in _PAIRS:
            assert fg in tokens, f"{theme}: missing token --{fg}"
            assert bg in tokens, f"{theme}: missing token --{bg}"
            ratio = _contrast(tokens[fg], tokens[bg])
            if ratio < _AA:
                failures.append(
                    f"{theme}: --{fg} ({tokens[fg]}) on --{bg} ({tokens[bg]}) "
                    f"= {ratio:.2f}:1 < {_AA}:1"
                )
    assert not failures, "WCAG AA contrast failures:\n" + "\n".join(failures)


def test_the_pair_list_is_non_vacuous() -> None:
    # Guard the guard: a parsing regression that emptied the token maps would make
    # the loop above pass vacuously. Pin that both themes parsed real colors and
    # that a deliberately-bad pairing is actually caught.
    themes = _themes()
    assert len(themes["light"]) >= 12 and len(themes["dark"]) >= 12
    # white-on-white must fail the computation, proving the ratio math is live.
    assert _contrast("#ffffff", "#fffdf7") < _AA
