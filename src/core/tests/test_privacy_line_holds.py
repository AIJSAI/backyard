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
    """Every human name the seed assigns, however it assigns it.

    Three shapes, not two. The third — `defaults={"display_name": "..."}` inside a
    `get_or_create` — was invisible to this extractor, and the moment the seed's one direct
    `Member.objects.create` became a `get_or_create`, the author's own name vanished from
    the parse. The denominator below caught it, which is the only reason this is a comment
    and not a hole: an extractor that silently stops seeing names cannot police them.
    """
    names = re.findall(r'display_name=["\']([^"\']+)["\']', source)
    names += re.findall(r'["\']display_name["\']\s*:\s*["\']([^"\']+)["\']', source)
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
    # A CEILING, not an exact match. This asserted `== ["James Shehan"]`, which made the
    # author's real surname REQUIRED in the seed: removing it — an unambiguous improvement,
    # and what happened when the operator's display name stopped being hardcoded and became
    # whatever the instance's superuser is called — failed this test for having leaked less.
    # A privacy check that goes red when a name is deleted is pinning the defect.
    assert not carrying, (
        f"demo seed names carrying the author's real surname: {carrying}. The demo family "
        "must be invented, and the operator's own row is named from the account that runs "
        "the instance — so no real surname belongs in this file at all."
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
        # The README is the first surface a stranger reads and the one that carries the
        # privacy claim itself, so leaving it out was the wrong scope. Review caught it.
        _ROOT / "README.md",
        _ROOT / "CONTRIBUTING.md",
    ]
    assert len(searched) > 50, f"only {len(searched)} files searched; the globs are wrong"

    offenders = []
    needle = _AUTHOR_SURNAME.casefold()
    for path in searched:
        if path.name == Path(__file__).name:
            continue  # this file names the surname in order to forbid it
        # casefold, not a substring of the original: the first version of this check was
        # case-SENSITIVE and passed while `priya-shehan.vcf` sat in a receipt -- a real,
        # live instance of exactly what it exists to forbid. Proving a guard fires against
        # the one mutation you thought of does not prove it catches the class.
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if needle not in line.casefold():
                continue
            # A COPYRIGHT NOTICE is the one place the author's own name belongs on a
            # reader-facing surface -- AGPL requires an identified copyright holder, so a
            # guard that forbade it would forbid the thing the licence demands. This guard
            # caught exactly that when the notice was added, which is the check working:
            # it forced the scope to be stated rather than assumed. Narrow on purpose --
            # the exemption is the word "copyright" on the same line, not the whole file.
            if "copyright" in line.casefold():
                continue
            offenders.append(f"{path.relative_to(_ROOT)}:{lineno}")
    assert not offenders, (
        f"the author's real surname reached files a stranger reads: {offenders}. "
        "It belongs in git authorship and the copyright notice, not in shipping source, "
        "receipts, or demo data."
    )
