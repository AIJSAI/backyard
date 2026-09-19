"""A documented `--passphrase-file` path must be a path that exists INSIDE the container.

The defect this exists for was live on the **printed recovery sheet** — the one document
somebody reads when the instance is already gone. Its restore steps said:

    printf '%s' '<the passphrase>' > /root/backyard.key     # on the HOST
    chmod 600 /root/backyard.key
    docker compose exec -T web sh -c '... restore_instance ... --passphrase-file /root/backyard.key'

`--passphrase-file` is read by `core.backup_passphrase.resolve`, which runs inside the `web`
container. `/root/backyard.key` exists on the host and nowhere else, so the command dies with
"passphrase file not found" on a tired person's first attempt at the worst moment of the
project's life. Nothing caught it: `test_runbook_commands_are_runnable` proves the argv
PARSES, and this argv parses perfectly — the path is a well-formed string, it is simply not
in the filesystem the command will look in.

The rule, and it is the one the guide already states in prose: a keyfile lives on the host
and is MOUNTED read-only into the container, so the path on the command line is the path
inside the container. This asserts the document says how that path gets there rather than
assuming the reader knows. Deliberately NOT "the path must be under /data": `/data` is the
volume the archives live on, and both runbooks correctly forbid putting the key there — a key
beside the ciphertext buys nothing (T-BACKUP-1).

Scoped to `docs/runbooks/`, and `docs/archive/` is out of scope like every other dated
record in this repository.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_RUNBOOKS = sorted((_ROOT / "docs" / "runbooks").glob("*.md"))

# `--passphrase-file <path>`, with the wrapper quote that usually closes around it trimmed.
# Only an absolute path is a claim about a filesystem; a bare mention of the flag with no
# path (self-host.md says "--passphrase-file still overrides it") makes no claim to check.
_DOCUMENTED_KEYFILE = re.compile(r"--passphrase-file[=\s]+(/[^\s'\"\\]+)")


def _introductions(text: str, path: str) -> bool:
    """Does this document say how `path` comes to exist inside the container?

    Two shapes count, and both appear in `backup-restore.md` today:

    * a compose mount whose TARGET is the path — `"/root/x.key:/run/secrets/x.key:ro"`;
    * `BACKYARD_BACKUP_PASSPHRASE_FILE=<path>`, which is the variable compose passes into
      both containers and is only ever set to an in-container path.
    """
    mount = re.compile(rf":{re.escape(path)}(:[a-z,]+)?[\"']")
    named = re.compile(rf"BACKYARD_BACKUP_PASSPHRASE_FILE[=:]\s*{re.escape(path)}")
    return bool(mount.search(text) or named.search(text))


def _documented() -> list[tuple[str, str]]:
    found = []
    for book in _RUNBOOKS:
        for path in _DOCUMENTED_KEYFILE.findall(book.read_text(encoding="utf-8")):
            found.append((book.name, path))
    return found


def test_the_scan_finds_the_keyfile_the_runbooks_document() -> None:
    """Denominator, named. The check below is a loop over whatever this finds, so an
    extractor that finds nothing passes it without reading a document — which is how the
    original defect survived a suite that already parsed every documented command."""
    documented = _documented()
    assert documented, (
        "no `--passphrase-file <path>` found in any runbook; the extractor is broken, so the "
        "check below iterates an empty list and proves nothing"
    )
    assert any(book == "backup-restore.md" for book, _ in _documented()), (
        "backup-restore.md documents the keyfile option and must be in scope"
    )


@pytest.mark.parametrize(
    ("book", "path"),
    [pytest.param(book, path, id=f"{Path(book).stem}::{path}") for book, path in _documented()],
)
def test_every_documented_keyfile_path_is_introduced_in_the_same_document(
    book: str, path: str
) -> None:
    text = (_ROOT / "docs" / "runbooks" / book).read_text(encoding="utf-8")
    assert _introductions(text, path), (
        f"docs/runbooks/{book} passes `--passphrase-file {path}` to a command that runs "
        f"INSIDE the container, but never says how {path} gets there. If it is a host path, "
        "the command fails with 'passphrase file not found' at the moment somebody needs a "
        "restore. Mount the key read-only and document the mount in this file, or drop the "
        "flag and let the command read BACKYARD_BACKUP_PASSPHRASE from the environment."
    )


def test_the_rule_can_actually_fail() -> None:
    """Non-vacuity, from both sides: the exact sheet text that was wrong must be rejected,
    and the mount-documenting text that is right must be accepted."""
    was_wrong = (
        "printf '%s' 'four random words' > /root/backyard.key\n"
        "chmod 600 /root/backyard.key\n"
        "docker compose exec -T web sh -c '... --passphrase-file /root/backyard.key'\n"
    )
    paths = _DOCUMENTED_KEYFILE.findall(was_wrong)
    assert paths == ["/root/backyard.key"], paths
    assert not _introductions(was_wrong, paths[0]), (
        "creating a file on the HOST is not introducing it into the container; if this "
        "passes, the guard would have missed the defect it was written for"
    )

    now_right = was_wrong.replace(
        "docker compose exec",
        'volumes: [ "/root/backyard.key:/run/secrets/backyard.key:ro" ]\ndocker compose exec',
    ).replace("--passphrase-file /root/backyard.key", "--passphrase-file /run/secrets/backyard.key")
    assert _introductions(now_right, "/run/secrets/backyard.key"), (
        "a documented read-only mount must be accepted as the introduction"
    )
