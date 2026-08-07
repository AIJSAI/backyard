"""Provider identifiers for the live instance must not be published.

`docs/runbooks/live-repro.md` and the 2026-07-26 audit both carried the real Ubicloud project
id and Cloudflare zone id on public `main`. Neither is a credential on its own — but a zone id
plus a leaked API token is a working pair, and an audit that names the project, the zone, the
SSH key path and the 1Password item is a map of the deployment for anyone who finds one of
them.

The prod IP was parameterised in these files long ago; the identifiers beside it were not,
which is the tell that this was an oversight rather than a decision.

Scoped by SHAPE, not by a list of known values, so a NEW identifier of the same kind fires
too. A denylist of the two that leaked would only ever catch those two — the same defect as
allowlisting file extensions in the credential guard.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]

# Ubicloud project ids are 26 lowercase base32-ish chars; Cloudflare zone/account ids are
# 32 lowercase hex. Both are matched only when a provider word is nearby, so ordinary hashes
# (git shas, checksums, DKIM keys) do not trip this.
_PROVIDER_LINE = re.compile(
    r"(?i)(ubicloud|cloudflare)[^\n]{0,120}?\b([a-z0-9]{26}|[0-9a-f]{32})\b"
)


# Documents that MUST be in scope, named rather than counted. `len(docs) > 40` was the first
# version and is brittle both ways: it breaks when an unrelated doc is deleted, and it passes
# when the scan points somewhere plausible but wrong. Review flagged the identical brittleness
# in a sibling guard earlier today and I reintroduced it here -- naming the files makes a
# failure say WHAT is missing, and two of these are where the identifiers actually leaked.
_MUST_SCAN = (
    "README.md",
    "docs/runbooks/live-repro.md",
    "docs/audits/2026-07-26-honest-100-audit.md",
)


def _tracked_docs() -> list[Path]:
    """Tracked markdown, with a filesystem fallback when git is unavailable.

    `check=True` with no fallback would CRASH the suite in a source tarball or any checkout
    without git metadata -- turning a disclosure guard into a build break for someone who has
    done nothing wrong. The credential guard already handles that case
    (`test_no_hardcoded_demo_credentials._tracked_files`); this now matches it rather than
    inventing a second convention.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "*.md"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        paths = [_ROOT / rel for rel in out.split("\0") if rel]
        if paths:
            return paths
    except (OSError, subprocess.CalledProcessError):
        pass
    skip = {".git", ".venv", "node_modules", ".claude", "staticfiles", "__pycache__"}
    return [p for p in _ROOT.rglob("*.md") if not any(part in skip for part in p.parts)]


def test_the_scan_actually_reads_the_documents() -> None:
    """Denominator, by NAME: the check below is vacuous if the scan misses these."""
    scanned = {p.relative_to(_ROOT).as_posix() for p in _tracked_docs()}
    missing = [name for name in _MUST_SCAN if name not in scanned]
    assert not missing, (
        f"these documents are not being scanned: {missing}. Two of them are where the "
        "identifiers leaked, so their absence would make this guard silently vacuous."
    )


def test_no_provider_identifier_is_published() -> None:
    """A real project/zone id in a public repo, in any tracked document."""
    offenders = []
    for path in _tracked_docs():
        if path.name == Path(__file__).name:
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if _PROVIDER_LINE.search(line):
                # Report the LOCATION, never the value: printing it into CI output would
                # publish the thing this test exists to keep unpublished.
                offenders.append(f"{path.relative_to(_ROOT)}:{lineno}")
    assert not offenders, (
        f"provider identifiers published at: {offenders}. Parameterise them "
        "(<CLOUDFLARE_ZONE_ID>, <UBICLOUD_PROJECT_ID>) and read the real values from "
        "1Password at run time, the way the production IP already is."
    )
