"""CONTRIBUTING's privacy line has to be checkable, not just promised.

The rule: no real family member's name, likeness or content in this public repository. The
demo family is invented. It nearly was not -- `scripts/demo_seed.py` shipped "Priya <real
surname>" for the project's life, the surname reached a SHIPPING source comment in
`posting.py` and two receipts, and the README carried a blanket claim of "no real family
content appears anywhere" that was false a few files away.

The author's own name is deliberately exempt: it is in every commit's authorship and is his
to give. Everyone else in the seed must be invented, and this asserts that rather than
trusting it.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SEED = _ROOT / "scripts" / "demo_seed.py"

# The author's surname, which git authorship publishes on every commit anyway. Listed here
# so the check can tell "the author named himself" (allowed, once, as the instance admin)
# apart from "a relative's real surname leaked into a public repo" (never).
_AUTHOR_SURNAME = "Shehan"


def _display_names(source: str) -> list[str]:
    """Every human name the seed assigns, from both the helper and the direct create."""
    names = re.findall(r'display_name=["\']([^"\']+)["\']', source)
    names += re.findall(r'member\(\s*["\']([^"\']+)["\']', source)
    return names


def test_the_seed_actually_names_people() -> None:
    """Denominator: a broken extractor would make every assertion below vacuous."""
    names = _display_names(_SEED.read_text())
    assert len(names) >= 5, f"only {len(names)} display names parsed from {_SEED}"


def test_no_relative_carries_the_authors_real_surname() -> None:
    """The author may name himself. Nobody else in the demo family may share his surname.

    A relative's real surname in a public repo is the privacy line this product is *about*
    breaking -- and it is the kind of thing a stranger notices before any maintainer does.
    """
    names = _display_names(_SEED.read_text())
    carrying = [n for n in names if _AUTHOR_SURNAME in n]
    assert carrying == ["James " + _AUTHOR_SURNAME], (
        f"demo seed names carrying the author's real surname: {carrying}. Only the author's "
        "own account may; every other member of the demo family must be invented."
    )


def test_the_surname_does_not_reach_shipping_source_or_docs() -> None:
    """It escaped the seed once: into a `posting.py` comment and two receipts.

    Scoped to the surfaces a stranger reads. `docs/OUTSTANDING.md` is exempt because the
    backlog entry describing this very leak has to be able to name it.
    """
    searched = [
        *(_ROOT / "src").rglob("*.py"),
        *(_ROOT / "src").rglob("*.html"),
        *(_ROOT / "docs" / "receipts").rglob("*.md"),
    ]
    assert len(searched) > 50, f"only {len(searched)} files searched; the globs are wrong"

    offenders = []
    for path in searched:
        if path.name == Path(__file__).name:
            continue  # this file names the surname in order to forbid it
        if _AUTHOR_SURNAME in path.read_text(encoding="utf-8", errors="replace"):
            offenders.append(str(path.relative_to(_ROOT)))
    assert not offenders, (
        f"the author's real surname reached files a stranger reads: {offenders}. "
        "It belongs in git authorship, not in shipping source or receipts."
    )
