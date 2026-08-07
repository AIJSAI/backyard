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
    """Both directions, and the negative one deterministically.

    The first version asserted only that a SIGNED commit passes. If `unsigned()` regressed to
    always return `[]` — the most likely way this goes wrong, since every failure mode of a
    "find the missing thing" check is a false negative — that self-test still passed and the
    gate went vacuous. The docstring claimed both directions were covered, which is worse
    than claiming neither: it is the sentence that stops the next person checking.

    The negative case builds a real commit OBJECT with `git commit-tree` and no trailer. It
    is unreachable — no ref points at it, so it is invisible to `git log` and collected by
    `gc` — but it is a genuine commit that `git log -1 --format=%B` reads exactly like any
    other, so this exercises the real code path rather than a stubbed one.
    """
    errors = []
    if unsigned([]) != []:
        errors.append("selftest: an empty range reported findings")

    # NEGATIVE: a commit with no trailer must be flagged.
    try:
        tree = _git("rev-parse", "HEAD^{tree}")
        synthetic = subprocess.run(
            ["git", "commit-tree", tree, "-m", "selftest: deliberately unsigned"],
            capture_output=True,
            text=True,
            check=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "selftest",
                "GIT_AUTHOR_EMAIL": "s@e",
                "GIT_COMMITTER_NAME": "selftest",
                "GIT_COMMITTER_EMAIL": "s@e",
            },
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        return [
            *errors,
            f"selftest: could not build a synthetic commit ({exc}); "
            "this check cannot prove it detects anything",
        ]
    if not unsigned([(synthetic, "selftest: deliberately unsigned")]):
        errors.append(
            "selftest: an UNSIGNED commit passed the check. `unsigned()` is returning "
            "nothing, so this gate would report PASS over a branch with no sign-offs at all."
        )

    # POSITIVE: a commit that carries the trailer must not be flagged. Built the same way,
    # so the two cases differ ONLY in the trailer.
    signed = subprocess.run(
        ["git", "commit-tree", tree, "-m", f"selftest: signed\n\n{TRAILER} A Tester <t@e>"],
        capture_output=True,
        text=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "selftest",
            "GIT_AUTHOR_EMAIL": "s@e",
            "GIT_COMMITTER_NAME": "selftest",
            "GIT_COMMITTER_EMAIL": "s@e",
        },
    ).stdout.strip()
    if unsigned([(signed, "selftest: signed")]):
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
