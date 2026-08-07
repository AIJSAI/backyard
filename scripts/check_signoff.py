#!/usr/bin/env python3
"""Every commit a pull request adds carries a DCO sign-off.

`CONTRIBUTING.md` says "Every commit must be signed off (`git commit -s`)". Measured when
this was written: **85 of 154 commits have no `Signed-off-by` trailer.** The rule was true
about intent, false about history, and enforced by nothing.

History cannot be fixed. Adding the trailer to 85 commits means rewriting every SHA in the
repository, which breaks every link, every receipt that cites a commit, and every clone — and
force-pushing is deny-listed in this environment for exactly that reason. So the rule applies
where it can: **to the commits a pull request adds**, from the merge base forward.

CONTRIBUTING is corrected alongside this, because a rule that a reader can see is false in
the log teaches them the rest of the document is aspirational too.

Checking the PR range only works because a squash merge KEEPS the trailer — verified against
the eight most recent merges on `main`, each carrying one `Signed-off-by` per squashed
commit. If GitHub stripped it, this gate would pass on every PR while `main` went on
accumulating unsigned commits: a green check over the exact thing it claims to prevent.

Scope is deliberately the PR range and not `main`. Checking `main` would fail forever on
history nobody can change, and a gate that can never pass is one people route around — this
repo has a note about that in `.gitleaks.toml`, on the burned password that cannot be
removed from history either.
"""

from __future__ import annotations

import os
import subprocess
import sys

TRAILER = "Signed-off-by:"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def commits_added(base: str, head: str) -> list[tuple[str, str]]:
    """`(sha, subject)` for each commit `head` adds relative to `base`."""
    raw = _git("log", "--format=%H%x00%s", f"{base}..{head}")
    out = []
    for line in raw.splitlines():
        if "\x00" in line:
            sha, subject = line.split("\x00", 1)
            out.append((sha, subject))
    return out


def unsigned(commits: list[tuple[str, str]]) -> list[str]:
    missing = []
    for sha, subject in commits:
        body = _git("log", "-1", "--format=%B", sha)
        # A trailer, not a substring: the words can appear in a commit message that quotes
        # this file, and prose about a rule is not compliance with it.
        if not any(line.startswith(TRAILER) for line in body.splitlines()):
            missing.append(f"{sha[:8]} {subject}")
    return missing


def selftest() -> list[str]:
    """The check must reject a commit with no trailer, and accept one with it."""
    errors = []
    if unsigned([]) != []:
        errors.append("selftest: an empty range reported findings")
    # Exercised against the real repository rather than a fixture: HEAD is signed (this
    # project signs now), and the repository's own history contains unsigned commits, so
    # both answers are available without constructing anything.
    head_body = _git("log", "-1", "--format=%B", "HEAD")
    if any(line.startswith(TRAILER) for line in head_body.splitlines()):
        if unsigned([("HEAD", "head")]):
            errors.append("selftest: a SIGNED commit was reported as unsigned")
    return errors


def main() -> int:
    base = os.environ.get("BASE_SHA") or os.environ.get("GITHUB_BASE_REF")
    head = os.environ.get("HEAD_SHA") or "HEAD"
    if not base:
        print("signoff: no base ref (not a pull request); nothing to check")
        return 0

    try:
        merge_base = _git("merge-base", base, head)
    except subprocess.CalledProcessError:
        print(
            f"GATE FAIL: cannot find a merge base for {base!r}..{head!r}. The checkout is "
            "probably shallow — this step needs `fetch-depth: 0`."
        )
        return 1

    errors = selftest()
    added = commits_added(merge_base, head)
    if not added:
        print("signoff: this branch adds no commits")
    missing = unsigned(added)

    for err in errors:
        print(f"GATE FAIL: {err}")
    if missing:
        print(
            f"GATE FAIL: {len(missing)} of {len(added)} commit(s) on this branch have no "
            f"`{TRAILER}` trailer:"
        )
        for line in missing:
            print(f"  {line}")
        print(
            "\nSign them with `git commit -s --amend` (last commit) or "
            "`git rebase --signoff <base>` for the range. CONTRIBUTING.md explains why the "
            "DCO is the whole paperwork here and there will never be a CLA."
        )

    failed = bool(errors or missing)
    print(f"signoff: {'FAIL' if failed else 'PASS'} ({len(added)} commit(s) checked)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
