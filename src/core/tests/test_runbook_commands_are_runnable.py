"""Every `manage.py` command a runbook tells an operator to run must actually parse.

The defect this exists for: `shutdown.md` documented
`backup_instance --output /data/final-backup.tar.enc`, but `output` is a POSITIONAL
argument and there is no `--output` flag, so the command exited with "unrecognized
arguments". The next step in that same runbook is `docker compose down -v`. An operator
working the list top to bottom would have destroyed the volume seconds after the last
backup silently failed to be written.

The existing `test_self_host_docs.py` could not catch it: it asserts the command *file*
exists, which it did, and it reads exactly one runbook. Existence is not runnability, and
one file is not the surface. `self-host.md` had the correct positional form the whole
time — the bug was fixed on the surface someone looked at and missed on the one they
did not, which is why this walks EVERY runbook and checks the ARGUMENTS against the real
parser rather than the command name against the filesystem.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest
from django.core.management import load_command_class
from django.core.management.base import CommandError

_ROOT = Path(__file__).resolve().parents[3]
_RUNBOOKS = sorted((_ROOT / "docs" / "runbooks").glob("*.md"))

# `shell` and `check` are Django's own; `migrate`/`runserver` likewise. We validate the
# commands this app defines, which are the ones that can drift when we rename a flag.
_OURS = {p.stem for p in (_ROOT / "src" / "core" / "management" / "commands").glob("*.py")} - {
    "__init__"
}

# Shell substitutions and placeholders that survive into argv as literal words. argparse
# only cares about the SHAPE (is this a flag? how many positionals?), so a placeholder
# standing in for a real path is fine — we are validating the invocation, not the values.
_PLACEHOLDER = re.compile(r"\$\([^)]*\)|\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|\.\.\.")


def _split(line: str) -> list[str] | None:
    """`shlex.split`, tolerating the ONE trailing quote that closes an outer wrapper.

    Real invocations are often wrapped in `sh -c '...'`, so capturing to end of line
    leaves a dangling `'`. Stripping every trailing quote would corrupt a genuine final
    argument like `--confirm "shut it down"`, so exactly one is dropped, and only when
    keeping it fails to parse.
    """
    attempts = [line]
    if line and line[-1] in "'\"":
        attempts.append(line[:-1])
    for attempt in attempts:
        try:
            return shlex.split(attempt)
        except ValueError:
            continue
    return None


def _invocations(text: str) -> list[tuple[str, list[str]]]:
    """Every `manage.py <command> <args...>` in the document, with line continuations
    joined and comment markers stripped, as (command, argv)."""
    # Strip a leading `#` per PHYSICAL line before joining, so a commented-out example
    # spanning two lines does not leak its second `#` into argv. Commented examples are
    # in scope on purpose: an operator copies those too.
    cleaned = "\n".join(
        ln.strip().lstrip("#").strip() if ln.strip().startswith("#") else ln
        for ln in text.splitlines()
    )
    # Join backslash-continued lines: the real commands are wrapped for width.
    joined = re.sub(r"\\\n\s*", " ", cleaned)
    found: list[tuple[str, list[str]]] = []
    for raw in re.findall(r"manage\.py\s+([^\n]+)", joined):
        line = _PLACEHOLDER.sub("PLACEHOLDER", raw.strip())
        if not line:
            continue
        parts = _split(line)
        if not parts or parts[0] not in _OURS:
            continue
        # Stop at a shell operator: what follows belongs to the next command, not argv.
        argv: list[str] = []
        for part in parts[1:]:
            if part in {"&&", "||", "|", ";", ">", "<", "2>&1"}:
                break
            argv.append(part)
        found.append((parts[0], argv))
    return found


_CASES = [
    pytest.param(book.name, command, argv, id=f"{book.stem}::{command}")
    for book in _RUNBOOKS
    for command, argv in _invocations(book.read_text())
]


def test_the_runbooks_actually_invoke_our_commands() -> None:
    """A denominator check, so this file cannot pass by finding nothing.

    Without it, a refactor that broke `_invocations` would turn every case below into
    silence and read as green — the failure mode this repo has been bitten by before.
    """
    assert len(_CASES) >= 5, (
        f"only {len(_CASES)} runbook invocations found across "
        f"{len(_RUNBOOKS)} runbooks — the extractor is probably broken, "
        "which would make every case below vacuous"
    )


@pytest.mark.parametrize(("book", "command", "argv"), _CASES)
def test_every_documented_invocation_parses(book: str, command: str, argv: list[str]) -> None:
    """The runbook's own argv, run through the command's real parser.

    No `pytest.skip` anywhere in here on purpose: a skip is how the previous version of
    this check hid the two commands that were missing from the guide.
    """
    parser = load_command_class("core", command).create_parser("manage.py", command)
    try:
        parser.parse_args(argv)
    except (CommandError, SystemExit) as exc:
        # Django's CommandParser raises CommandError where bare argparse would SystemExit;
        # catching only SystemExit would have let every one of these through as an ERROR
        # rather than a readable failure. Both mean "the operator's command does not run".
        pytest.fail(
            f"docs/runbooks/{book} tells the operator to run `manage.py {command} "
            f"{' '.join(argv)}`, which the command's own parser rejects: {exc}. "
            "An operator finds this out at the moment they need it — which for "
            "backup_instance is one step before `docker compose down -v`."
        )


# --- The layer the argparse check above cannot see -------------------------------------

_CONTAINER_EXEC = re.compile(r"compose\s+exec[^\n]*", re.M)


def _container_manage_invocations() -> list[tuple[str, str]]:
    """Every `docker compose exec … manage.py …` line in the runbooks, joined and decommented."""
    found = []
    for book in _RUNBOOKS:
        cleaned = "\n".join(
            ln.strip().lstrip("#").strip() if ln.strip().startswith("#") else ln
            for ln in book.read_text().splitlines()
        )
        joined = re.sub(r"\\\n\s*", " ", cleaned)
        for line in joined.splitlines():
            if "compose" in line and "exec" in line and "manage.py" in line:
                found.append((book.name, line.strip()))
    return found


def test_the_container_invocation_scan_finds_something() -> None:
    """Denominator, named: these runbooks DO drive manage.py inside the container."""
    books = {name for name, _ in _container_manage_invocations()}
    for required in ("backup-restore.md", "self-host.md"):
        assert required in books, (
            f"no container manage.py invocation found in {required}; the extractor is broken, "
            "so the check below would pass vacuously"
        )


@pytest.mark.parametrize(
    ("book", "line"),
    [
        pytest.param(book, cmd, id=f"{book}::{i}")
        for i, (book, cmd) in enumerate(_container_manage_invocations())
    ],
)
def test_every_container_command_supplies_the_secret_key(book: str, line: str) -> None:
    """A documented command must be able to START, not merely parse its arguments.

    The argparse check above validates the SHAPE of the arguments. It cannot see this,
    because `config/settings.py` raises before argparse is ever reached:

        RuntimeError: DJANGO_SECRET_KEY is empty, a placeholder, or too short

    The entrypoint generates the key at boot, writes it to /data/secret_key and exports it
    for gunicorn only. A fresh `docker compose exec` gets the container's CONFIGURED
    environment, which has never contained it -- so every documented command that omits
    `DJANGO_SECRET_KEY=$(cat /data/secret_key)` dies before doing anything.

    Verified against the live production instance: the bare form returns that RuntimeError,
    the sourced form returns the command's own --help. Seven invocations across four files
    were broken this way, including the printed emergency recovery card -- the one someone
    reads when the instance is already gone.
    """
    assert "secret_key" in line, (
        f"docs/runbooks/{book} runs manage.py in the container without supplying "
        f"DJANGO_SECRET_KEY, so it exits with a RuntimeError before it starts:\n\n    {line}\n\n"
        "Wrap it: sh -c 'DJANGO_SECRET_KEY=$(cat /data/secret_key) python manage.py …'"
    )
