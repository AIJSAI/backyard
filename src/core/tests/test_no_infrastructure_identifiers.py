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


def _tracked_docs() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "*.md"], cwd=_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [_ROOT / rel for rel in out.split("\0") if rel]


def test_the_scan_actually_reads_the_documents() -> None:
    """Denominator: a broken glob would make the check below silently pass."""
    docs = _tracked_docs()
    assert len(docs) > 40, f"only {len(docs)} tracked .md files found; the glob is wrong"


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
