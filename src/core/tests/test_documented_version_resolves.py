"""Every version a document tells a reader to install must be a tag that exists.

The defect this exists for is one this repo was about to create. `v0.1.0` was withdrawn and
deleted, and eight documents named it — README's clone command, SECURITY.md's supported-versions
table, CONTRIBUTING, the changelog link. Deleting the tag without updating them leaves the
install path pointing at nothing:

    git clone --branch v0.1.0 ...   ->   fatal: Remote branch v0.1.0 not found

Nothing caught that, because no gate reads a version out of prose and checks it.

Scope is the documents that tell a stranger WHAT TO INSTALL, listed in `_READER_FACING`.
Three kinds of file sit outside it, and the distinction is the point:

* `docs/receipts/` and `docs/audits/` are dated records of what was true when written.
  Rewriting one to keep a grep clean is how a project loses the ability to trust its history.
* `docs/RESUME-HERE.md` is an internal handoff note that names withdrawn versions ON PURPOSE
  ("`v0.1.0` is WITHDRAWN") so the next session does not point anyone at them. Guarding it
  would fail the build for saying the true and useful thing.

An earlier version of this docstring listed RESUME-HERE among the guarded documents while
`_READER_FACING` did not. Review caught the contradiction; the list was right and the prose
was wrong, which is the safer direction for the two to disagree in but still worth fixing.

Three checks were added after this file was measured and found to be doing nothing:

* **The in-flight exemption had swallowed the whole check.** Exempting the newest CHANGELOG
  version is correct only while that version has no tag; unconditionally, it exempts the
  version README tells you to clone, forever. Measured at `v0.1.1`: every actionable
  reference in all four documents was exempt, so this file compared an empty set and passed.
  `test_something_is_actually_being_checked_against_the_tags` measures the set the assertion
  consumes, rather than the set the extractor found — which is what a denominator is for.
* **"Current" is an instruction too.** `_ACTIONABLE` is deliberately blind to prose, so
  SECURITY.md's supported-versions table and CONTRIBUTING's opening line could name a
  superseded release indefinitely, in the two files a stranger reads to decide what is safe
  to install. Both did.
* **`pyproject.toml` had drifted two releases behind**, because nothing read it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]

# The documents a person reads to decide what to install. If a version appears here it is an
# instruction, not a record.
_READER_FACING = (
    "README.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    # The install guide, and the most actionable document of the five: it is the one that
    # says `git clone --branch <tag>`. It was outside this list while carrying two hardcoded
    # tags, so the file that tells a stranger exactly what to type was the only one nothing
    # checked. Paths are repo-relative, not bare names, so a document anywhere can be guarded.
    "docs/runbooks/self-host.md",
)

# ACTIONABLE references only: a command a reader runs, or a URL they click. A bare mention
# is not one, and conflating the two is what the first version of this check did -- it failed
# on SECURITY.md's "v0.1.0 | withdrawn - do not install" row and on the CHANGELOG's historical
# `## [0.1.0]` heading, i.e. on the documents CORRECTLY telling a reader a version is gone.
# A guard that fires on saying "do not install this" is pushing toward deleting the warning.
_ACTIONABLE = re.compile(
    r"""(?x)
    (?: --branch \s+ | git\ checkout \s+ | /tree/ | /releases/tag/ )
    (v\d+\.\d+\.\d+)
    """
)


def _tags() -> set[str]:
    out = subprocess.run(
        ["git", "tag", "--list"], cwd=_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return {t.strip() for t in out.splitlines() if t.strip()}


def _versions_in(path: Path) -> set[str]:
    """Versions a reader could ACT on: clone commands and tree/tag URLs.

    HTML comments are stripped FIRST. A comment is not something a reader clicks, and the
    comment in CHANGELOG.md explaining why 0.1.0 deliberately has no link quotes
    `/tree/v0.1.0` in order to say it 404s — which satisfied this check and failed the build
    for documenting the decision correctly.

    That is the third time in one session that prose defeated a source-text assertion in this
    repo (a `{% url %}` in a template comment, a `{# #}` variant of the same, now this).
    The rule generalises: if a check reads source text, strip every comment syntax that
    source has before matching, or the check is answerable by writing about it.
    """
    from core.tests.comment_stripping import without_comments

    return set(_ACTIONABLE.findall(without_comments(path.read_text(encoding="utf-8"))))


def _release_in_flight(tags: set[str]) -> str | None:
    """The newest CHANGELOG version, IF it has not been tagged yet.

    A release lands as: update the documents, merge, then cut the tag. Between those steps the
    documents name a version that does not exist, and that is correct — so exempting exactly
    the newest changelog entry is a real distinction, not a loophole.

    The `tags` argument closes the loophole it became. Exempting the newest changelog entry
    UNCONDITIONALLY exempts it forever, and in steady state the newest changelog version is
    also the version README tells you to clone — so every actionable reference in every
    guarded document was exempt and this file checked NOTHING. Measured on `v0.1.1`:
    `ACTUALLY_CHECKED` was empty for all four documents. A release that has been cut is no
    longer in flight, so once the tag exists there is nothing left to excuse.
    """
    for line in (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        found = re.match(r"^## \[(\d+\.\d+\.\d+)\]", stripped)
        if found:
            version = f"v{found.group(1)}"
            if version in tags:
                return None
            # "Not tagged" has two causes and only one of them is in flight. A WITHDRAWN
            # release also has no tag — `v0.1.0`'s was deleted when it was withdrawn — and
            # treating that as in-flight would exempt, forever, the exact version this file
            # exists to stop a stranger installing.
            #
            # The CHANGELOG already distinguishes them: a live entry is a bracketed heading
            # with a link at the foot of the file, a withdrawn one loses both and says so.
            # `test_a_withdrawn_release_keeps_the_shape_that_marks_it` makes that a rule
            # rather than a habit, because this function reads it as one.
            if _is_withdrawn(f"{found.group(1)}"):
                return None
            return version
    return None


def _is_withdrawn(version: str) -> bool:
    """Does the CHANGELOG say this version was withdrawn?"""
    body = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return (
        re.search(rf"^##\s*\[?{re.escape(version)}\]?.*\(withdrawn\)", body, re.M | re.I)
        is not None
    )


def test_the_reader_facing_documents_actually_name_a_version() -> None:
    """Denominator. If the regex or the file list breaks, every assertion below goes quiet
    rather than failing — which is the failure mode this repo keeps finding in its own gates.
    """
    named = {v for name in _READER_FACING for v in _versions_in(_ROOT / name)}
    assert named, (
        f"no ACTIONABLE vX.Y.Z reference (clone command or tree/tag URL) found in any of "
        f"{_READER_FACING} — the extractor is broken, so the check below cannot fail and "
        "proves nothing"
    )


def test_something_is_actually_being_checked_against_the_tags() -> None:
    """The denominator that matters, measured AFTER the exemption rather than before.

    The test above counts references the extractor found. That is the wrong quantity: it
    stayed green while the in-flight-release exemption removed every one of those references
    from the comparison, so this file passed by checking an empty set. A denominator has to
    measure what the assertion actually consumes, or it is decoration.

    Skipped, loudly, only in a checkout with no tags at all — see the reasoning below.
    """
    tags = _tags()
    if not tags:
        pytest.skip("no tags in this checkout; the check below has nothing to resolve against")
    pending = _release_in_flight(tags)
    checked = {
        version
        for name in _READER_FACING
        for version in _versions_in(_ROOT / name)
        if version != pending
    }
    assert checked, (
        "every actionable version reference in "
        f"{_READER_FACING} was exempted as the release in flight ({pending}), so nothing "
        "was compared against the tag list and this file proved nothing. Either the "
        "documents name only the unreleased version, or the exemption is too wide."
    )


def _newest_release() -> str:
    changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    newest = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.M)
    assert newest, "CHANGELOG.md has no `## [x.y.z]` heading to compare against"
    return f"v{newest.group(1)}"


# A document that says "this is the current version" in prose or a table. The regex above
# is deliberately blind to these — it fires only on things a reader CLICKS or RUNS, after an
# earlier version failed the build for correctly saying "v0.1.0 | withdrawn — do not install".
# But a reader acts on "current" too, and nothing was checking it: both of these still named
# v0.1.1 after v0.1.2 was prepared, in the two files a stranger reads to decide what is safe
# to install.
_CURRENCY_CLAIMS = {
    "SECURITY.md": re.compile(r"^\|\s*`(v\d+\.\d+\.\d+)`\s*\|\s*✅", re.M),
    "CONTRIBUTING.md": re.compile(r"^Backyard is at \[`(v\d+\.\d+\.\d+)`\]", re.M),
}


@pytest.mark.parametrize("document", sorted(_CURRENCY_CLAIMS))
def test_the_document_that_says_which_version_is_current_is_right(document: str) -> None:
    """Whatever a document calls the current release must be the newest one."""
    text = (_ROOT / document).read_text(encoding="utf-8")
    claimed = _CURRENCY_CLAIMS[document].search(text)
    assert claimed, (
        f"{document} no longer states which version is current in the shape this check "
        "reads, so the check is vacuous. Update the pattern, or restore the claim."
    )
    newest = _newest_release()
    assert claimed.group(1) == newest, (
        f"{document} tells a reader {claimed.group(1)} is the current release; the newest "
        f"entry in CHANGELOG.md is {newest}. Update it in the release commit — this is the "
        "file people read to decide what is safe to install."
    )


def test_the_package_version_matches_the_newest_release_in_the_changelog() -> None:
    """`pyproject.toml` is a document too, and it drifted through two releases.

    It still said `0.1.0` after `v0.1.1` was cut, because nothing read it. That is harmless
    right now — nothing is published to an index — and it is exactly the kind of harmless
    that becomes a wrong version stamped on an artifact later. The newest CHANGELOG heading
    is the single source of what this tree calls itself.
    """
    changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    newest = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.M)
    assert newest, "CHANGELOG.md has no `## [x.y.z]` heading to compare against"

    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version = "(\d+\.\d+\.\d+)"', pyproject, re.M)
    assert declared, 'pyproject.toml has no `version = "x.y.z"` line'

    assert declared.group(1) == newest.group(1), (
        f"pyproject.toml says {declared.group(1)} and the newest CHANGELOG entry is "
        f"{newest.group(1)}. Bump the version in the same commit that adds the release notes."
    )


@pytest.mark.parametrize("document", _READER_FACING)
def test_every_version_a_document_tells_you_to_install_exists(document: str) -> None:
    """An ACTIONABLE version reference must resolve to a real tag.

    CHANGELOG is included on purpose: its `[x.y.z]: .../tree/vX.Y.Z` links are what a reader
    follows to see what a release contained, and a link to a deleted tag is a 404. Verified
    live while writing this -- `/tree/v0.1.0` returned 404 the moment the tag was deleted.
    """
    tags = _tags()
    if not tags:
        # A skip here is exactly how this guard went quiet: `actions/checkout` fetches
        # shallowly WITHOUT tags, so CI hit this branch on every run and the check never
        # executed on a runner -- decorative in the one place it needed to hold. CI now sets
        # `fetch-tags: true`, so no-tags means something is wrong rather than expected.
        #
        # Still a skip and not a failure, because a legitimate tagless checkout exists (a
        # source tarball, a fresh clone before the first tag). But it is LOUD: if the
        # CHANGELOG names a released version, tags should exist, and their absence is a
        # broken checkout rather than a young repository.
        if _release_in_flight(tags):
            pytest.fail(
                "no git tags in this checkout, but CHANGELOG.md names a release. In CI this "
                "means the checkout is not fetching tags (`fetch-tags: true`), which makes "
                "this whole check skip silently -- which is how it went unnoticed before."
            )
        pytest.skip("no tags and no released version yet; nothing to resolve against")

    pending = _release_in_flight(tags)
    missing = sorted(v for v in _versions_in(_ROOT / document) if v not in tags and v != pending)
    assert not missing, (
        f"{document} names {missing}, which is not a tag in this repository. "
        f"Existing tags: {sorted(tags)}. A reader following that instruction gets "
        "'Remote branch not found'. If a version was withdrawn, update the document in the "
        "same commit that deletes the tag."
    )


def test_a_withdrawn_release_keeps_the_shape_that_marks_it() -> None:
    """`_release_in_flight` reads this convention, so it has to be a rule.

    "Not tagged" has two causes: the release is mid-flight (documents updated, tag not cut
    yet — legitimate, and the reason the exemption exists), or the release was WITHDRAWN and
    its tag deleted. `v0.1.0` is the second. Treating it as the first would exempt, forever,
    the exact version this file exists to stop a stranger installing.

    The CHANGELOG distinguishes them by shape: a live entry is a bracketed heading with a
    link reference at the foot of the file; a withdrawn one has neither and says
    `(withdrawn)` in the heading. That was a habit maintained by hand. Since a function now
    depends on it, it is asserted.
    """
    body = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = re.findall(r"^##\s+(.+)$", body, re.M)
    withdrawn = [h for h in headings if "(withdrawn)" in h.casefold()]
    assert withdrawn, (
        "no withdrawn release in the CHANGELOG, so this check is measuring nothing. If the "
        "last withdrawal was genuinely removed from history, delete this test with it — but "
        "`_release_in_flight` depends on the convention, so read that first."
    )
    for heading in withdrawn:
        assert "[" not in heading, (
            f"the withdrawn release heading `## {heading}` is BRACKETED. A bracketed heading "
            "is how `_release_in_flight` recognises a live release, so this one would be "
            "read as in-flight and exempted from every version check — permanently "
            "recommending the release the heading says not to install."
        )

    # And the other half: the newest live entry must be bracketed, or nothing is ever
    # exempt and a real in-flight release fails the build.
    live = [h for h in headings if "(withdrawn)" not in h.casefold()]
    assert live and live[0].startswith("["), (
        f"the newest CHANGELOG entry `## {live[0] if live else '(none)'}` is not bracketed, "
        "so `_release_in_flight` sees no release in flight and the documents cannot name a "
        "version between merging the release notes and cutting the tag"
    )
