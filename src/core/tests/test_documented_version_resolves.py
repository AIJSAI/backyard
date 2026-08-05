"""Every version a document tells a reader to install must be a tag that exists.

The defect this exists for is one this repo was about to create. `v0.1.0` was withdrawn and
deleted, and eight documents named it — README's clone command, SECURITY.md's supported-versions
table, CONTRIBUTING, the changelog link, RESUME-HERE. Deleting the tag without updating them
leaves the install path pointing at nothing:

    git clone --branch v0.1.0 ...   ->   fatal: Remote branch v0.1.0 not found

Nothing caught that, because no gate reads a version out of prose and checks it.

Scope is deliberately the READER-FACING documents. Receipts and audits under `docs/receipts/`
and `docs/audits/` name old tags on purpose — they are dated records of what was true when
they were written, and rewriting one to keep a grep clean is how a project loses the ability
to trust its own history.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]

# The documents a person reads to decide what to install. If a version appears here it is an
# instruction, not a record.
_READER_FACING = ("README.md", "SECURITY.md", "CONTRIBUTING.md", "CHANGELOG.md")

_VERSION = re.compile(r"\bv\d+\.\d+\.\d+\b")


def _tags() -> set[str]:
    out = subprocess.run(
        ["git", "tag", "--list"], cwd=_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return {t.strip() for t in out.splitlines() if t.strip()}


def _versions_in(path: Path) -> set[str]:
    return set(_VERSION.findall(path.read_text(encoding="utf-8")))


def _release_in_flight() -> str | None:
    """The newest CHANGELOG version, which may legitimately have no tag yet.

    A release lands as: update the documents, merge, then cut the tag. Between those steps the
    documents name a version that does not exist, and that is correct — so exempting exactly
    the newest changelog entry is a real distinction, not a loophole. Every OLDER version must
    still resolve, which is the defect being guarded: a withdrawn tag left dangling in the
    install instructions.
    """
    for line in (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        found = re.match(r"^## \[(\d+\.\d+\.\d+)\]", line.strip())
        if found:
            return f"v{found.group(1)}"
    return None


def test_the_reader_facing_documents_actually_name_a_version() -> None:
    """Denominator. If the regex or the file list breaks, every assertion below goes quiet
    rather than failing — which is the failure mode this repo keeps finding in its own gates.
    """
    named = {v for name in _READER_FACING for v in _versions_in(_ROOT / name)}
    assert named, (
        f"no vX.Y.Z reference found in any of {_READER_FACING} — the extractor is broken, "
        "so the check below cannot fail and proves nothing"
    )


@pytest.mark.parametrize("document", _READER_FACING)
def test_every_version_a_document_tells_you_to_install_exists(document: str) -> None:
    """A reader-facing version must resolve to a real tag.

    CHANGELOG is included on purpose: its `[x.y.z]: .../tree/vX.Y.Z` links are what a reader
    follows to see what a release contained, and a link to a deleted tag is a 404.
    """
    tags = _tags()
    if not tags:
        pytest.skip("no tags in this checkout (shallow clone); nothing to resolve against")

    pending = _release_in_flight()
    missing = sorted(v for v in _versions_in(_ROOT / document) if v not in tags and v != pending)
    assert not missing, (
        f"{document} names {missing}, which is not a tag in this repository. "
        f"Existing tags: {sorted(tags)}. A reader following that instruction gets "
        "'Remote branch not found'. If a version was withdrawn, update the document in the "
        "same commit that deletes the tag."
    )
