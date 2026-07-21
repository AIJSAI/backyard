#!/usr/bin/env python3
"""TM-2 drift-guard: the digest builder reads ONLY through the audience guard.

src/core/digest.py must never grow a data-access path of its own: no model
manager, no raw SQL, no cursor. Every content byte it emits has to come through
core.scoping (directly or via digest_links/profiles, which are themselves
scoping-bound). A batch principal with its own query is the T-YARD-9 bug — a
cross-yard fusion mailed to an inbox is unrecallable — so the rule is enforced
here as a build failure, not a review comment.

The guard proves itself non-vacuous on every run (the parents[N] lesson): each
banned pattern is checked against a fixture line that MUST match, so a typo in
the pattern list breaks the build rather than going silently green.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# An argv override exists so the test suite can prove the guard trips on a
# poisoned file (non-vacuity is tested from both sides).
_DEFAULT = Path(__file__).resolve().parent.parent / "src" / "core" / "digest.py"
DIGEST = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT

# Each entry: (human name, compiled pattern, a fixture line the pattern MUST hit).
BANNED: list[tuple[str, re.Pattern[str], str]] = [
    (
        "model-manager access",
        re.compile(r"\b\w+\.objects\b"),
        "    posts = Post.objects.filter(pk=1)",
    ),
    (
        "base/all manager escape hatch",
        re.compile(r"\b(all_objects|_base_manager|_default_manager)\b"),
        "    Post._base_manager.all()",
    ),
    (
        "raw SQL",
        re.compile(r"\.raw\(|RawSQL|connection\.cursor|cursor\(\)"),
        "    with connection.cursor() as c:",
    ),
    (
        "related-manager traversal (the scoping.py HIGH-1 leak class)",
        re.compile(
            r"\.(pods|yards|members|memberships|pod_memberships|posts"
            r"|comments|reactions|media_assets|digest_issues|tokens)\b"
        ),
        "    count = post.media_assets.count()",
    ),
]

# The models import is parsed, not pattern-matched: the natural drift is
# appending ", Post" to the existing import line, which a first-name-anchored
# regex waves through (#37 review LOW-3). Only the issue row itself may enter.
_ALLOWED_MODEL_IMPORTS = {"DigestIssue"}


def _import_violations(source: str) -> list[str]:
    violations: list[str] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("from .models import "):
            continue
        names = {
            name.strip().split(" as ")[0]
            for name in stripped.removeprefix("from .models import ").strip("()").split(",")
            if name.strip()
        }
        rogue = names - _ALLOWED_MODEL_IMPORTS
        if rogue:
            violations.append(
                f"src/core/digest.py:{lineno}: model import outside the guard: {sorted(rogue)}"
            )
    return violations


def main() -> int:
    # Self-test first: a guard that cannot catch its own fixtures is a broken
    # guard, and broken must be loud (never-vacuous rule).
    for name, pattern, fixture in BANNED:
        if not pattern.search(fixture):
            print(f"SELFTEST FAILED: pattern for {name!r} misses its fixture {fixture!r}")
            return 2

    source = DIGEST.read_text()
    failures: list[str] = _import_violations(source)
    if not _import_violations("from .models import DigestIssue, Post"):
        print("SELFTEST FAILED: the import parser misses a multi-name drift")
        return 2
    for lineno, line in enumerate(source.splitlines(), start=1):
        for name, pattern, _fixture in BANNED:
            if pattern.search(line):
                failures.append(f"src/core/digest.py:{lineno}: {name}: {line.strip()}")
    if failures:
        print("TM-2 CONFINEMENT VIOLATION: digest.py must read only through core.scoping")
        print("\n".join(failures))
        return 1
    print("digest confinement OK (guard self-tested non-vacuous)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
