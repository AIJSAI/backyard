"""Every command a runbook tells an operator to run must parse — as a shell line, and
then as arguments to the command's own parser.

The defect this exists for: `shutdown.md` documented
`backup_instance --output /data/final-backup.tar.enc`, but `output` is a POSITIONAL
argument and there is no `--output` flag, so the command exited with "unrecognized
arguments". The next step in that same runbook is `docker compose down -v`. An operator
working the list top to bottom would have destroyed the volume seconds after the last
backup silently failed to be written.

The existing `test_self_host_docs.py` could not catch it: it asserts the command *file*
exists, which it did, and it reads exactly one runbook. Existence is not runnability, and
one file is not the surface.

There are THREE layers, and each one exists because the layer above it was not enough:

1. **Shell parseability.** A command with an unbalanced quote cannot be copy-pasted at all.
   This layer was added after the argparse layer below passed cleanly on
   `backup-recovery-sheet.md` — the printed EMERGENCY RECOVERY CARD — while its restore
   command opened `sh -c '` and never closed it. The argparse check could not see it: the
   broken quote sits BEFORE `manage.py`, so the capture that starts after `manage.py` was
   quote-free and parsed perfectly. A substring or a regex cannot answer "does this parse";
   only a parser can, which is why this layer runs `shlex` over the whole command.
2. **Argument shape**, against the command's real argparse parser.
3. **Startability**: `config/settings.py` raises on a missing `DJANGO_SECRET_KEY` before
   argparse is ever reached, so a documented `docker compose exec` that does not supply it
   dies before doing anything. See `test_every_container_command_supplies_the_secret_key`.

Two rules this file follows, both learned the hard way in this repo:

* **Never drop a command from the corpus.** The previous version returned `None` when a
  line would not `shlex.split` and the caller turned that into `continue`, so an
  unparseable command left the test corpus instead of failing it. Two invocations in
  `founder-qa.md` were being silently deleted this way. Anything this file cannot parse is
  now reported, never skipped.
* **Denominators name what they cover.** `len(_CASES) >= 5` was a count floor: it stayed
  green while covering four of our eight management commands, and deleting a whole runbook
  would still have left five. `test_documented_command_coverage_is_what_we_think` pins the
  set instead, so a command silently falling out of the documentation fails the build.
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

# Commands that legitimately appear in no runbook, each with the reason. Adding a command
# to `src/core/management/commands/` therefore forces a decision: document it, or say here
# why an operator never types it. That is the difference between a denominator and a floor.
_NOT_OPERATOR_FACING = {
    "ensure_setup": "runs from the container entrypoint at every boot; nobody types it",
    "rollup_metrics": "a Procrastinate periodic (tasks.py, Mondays 06:40)",
    "send_digests": "a Procrastinate periodic (tasks.py, hourly)",
    "break_glass": "documented in docs/security/, not in a runbook — it is a recovery"
    " credential path rather than an operations step",
}

# Shell substitutions and placeholders that survive into argv as literal words. argparse
# only cares about the SHAPE (is this a flag? how many positionals?), so a placeholder
# standing in for a real path is fine — we are validating the invocation, not the values.
_PLACEHOLDER = re.compile(r"\$\([^)]*\)|\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|\.\.\.")

# A commented line inside a code block is either a copy-pasteable example (an operator
# uncomments it and runs it, so it IS in scope) or English prose explaining the block. We
# keep the first and drop the second. Getting this wrong in the safe-looking direction —
# decommenting everything — makes an apostrophe in "the family's history" open a shell
# quote and reports the surrounding prose as a broken command. Measured: three such false
# positives before this filter existed.
_LOOKS_LIKE_A_COMMAND = re.compile(
    r"\bmanage\.py\b"
    r"|^\s*(?:\.\.\.\s*)?(?:docker|python|sh|uv|make|psql|tar|printf|chmod|scp|export)\b"
)

_CONTAINER_EXEC = re.compile(r"\bcompose\s+exec\b")


def _code_regions(text: str) -> list[tuple[int, str]]:
    """Every fenced (```) or indented code region, as (1-based first line, body).

    The unit matters: an operator copies a block, not a line. The emergency recovery card
    uses indented blocks under numbered list items, and `backup-restore.md` uses fenced
    ones, so both shapes have to be read or half the surface goes unchecked.
    """
    lines = text.splitlines()
    regions: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        if lines[index].lstrip().startswith("```"):
            start = index + 2
            body: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].lstrip().startswith("```"):
                body.append(lines[index])
                index += 1
            index += 1
            regions.append((start, "\n".join(body)))
            continue
        if lines[index].startswith(("    ", "\t")):
            start = index + 1
            body = []
            while index < len(lines) and (
                lines[index].startswith(("    ", "\t")) or not lines[index].strip()
            ):
                body.append(lines[index])
                index += 1
            regions.append((start, "\n".join(body)))
            continue
        index += 1
    return regions


def _logical_commands(region: str) -> tuple[list[str], str]:
    """Split a code region into complete shell commands.

    Returns `(commands, unterminated)`. A non-empty `unterminated` means the region ran out
    of lines with a quote still open — i.e. the block cannot be pasted into a shell.

    The continuation rule here is the shell's own, and it has to be, because both shapes
    occur in these runbooks: a command wrapped for width with trailing backslashes, and a
    command whose single-quoted argument spans several lines with no backslash at all
    (`backup-restore.md`'s decrypt drill opens `sh -c '` and closes it six lines later).
    Treating either one as a line-per-command produces a false failure on the other, so a
    line is consumed until what we hold parses.
    """
    marked: list[tuple[bool, str]] = []
    for line in region.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            marked.append((True, stripped.lstrip("#").strip()))
        else:
            marked.append((False, line))

    # Join backslash continuations, remembering whether the run STARTED as a comment.
    logical: list[tuple[bool, str]] = []
    buffer: str | None = None
    from_comment = False
    for is_comment, text in marked:
        if buffer is None:
            buffer, from_comment = text, is_comment
        else:
            buffer = f"{buffer} {text}"
        if buffer.rstrip().endswith("\\"):
            buffer = buffer.rstrip()[:-1]
            continue
        logical.append((from_comment, buffer))
        buffer = None
    if buffer is not None:
        logical.append((from_comment, buffer))

    kept = [
        text
        for is_comment, text in logical
        if not (is_comment and not _LOOKS_LIKE_A_COMMAND.search(text))
    ]

    commands: list[str] = []
    pending = ""
    for line in kept:
        pending = line if not pending else f"{pending}\n{line}"
        try:
            shlex.split(pending)
        except ValueError:
            continue  # a quote is still open; the command continues on the next line
        if pending.strip():
            commands.append(pending)
        pending = ""
    return commands, pending


def _regions_with_commands() -> list[tuple[str, int, str]]:
    """(book, first line, region) for every code region that drives manage.py."""
    found = []
    for book in _RUNBOOKS:
        for start, region in _code_regions(book.read_text()):
            if "manage.py" in region:
                found.append((book.name, start, region))
    return found


def _shell_words(text: str) -> list[str] | None:
    """Tokens of a captured argument tail, cut at the wrapper quote that closes around it.

    A real invocation is usually `sh -c 'DJANGO_SECRET_KEY=… python manage.py backup_instance …'`,
    so a capture starting after `manage.py` runs into the wrapper's CLOSING quote with no
    opener. The old code dropped exactly one trailing quote, which handled the common case
    and silently discarded anything else (`manage.py shell' < scripts/demo_seed.py`, twice
    in `founder-qa.md`). Cutting at a quote handles both, and returning `None` here is now
    reported by a test rather than swallowed by a `continue`.

    Candidates are tried LONGEST FIRST, which is not cosmetic. The wrapper's closing quote
    is the LAST one on the line, so cutting at the first quote instead throws away real
    arguments: `shutdown.md`'s decommission command became `--to` with nothing after it and
    failed as though the runbook were wrong, when the runbook is correct.
    """
    candidates = [text]
    for position in reversed([i for i, character in enumerate(text) if character in "'\""]):
        candidates.append(text[:position])
    for candidate in candidates:
        try:
            return shlex.split(candidate)
        except ValueError:
            continue
    return None


def _invocations(text: str) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """Every `manage.py <command> <args…>` in the document, as (command, argv).

    Also returns the tails this function could not tokenise at all, so the caller can fail
    on them instead of quietly shrinking the corpus.
    """
    cleaned = "\n".join(
        line.strip().lstrip("#").strip() if line.strip().startswith("#") else line
        for line in text.splitlines()
    )
    joined = re.sub(r"\\\n\s*", " ", cleaned)
    found: list[tuple[str, list[str]]] = []
    unparseable: list[str] = []
    for raw in re.findall(r"manage\.py\s+([^\n]+)", joined):
        line = _PLACEHOLDER.sub("PLACEHOLDER", raw.strip())
        if not line:
            continue
        parts = _shell_words(line)
        if parts is None:
            unparseable.append(line)
            continue
        if not parts or parts[0] not in _OURS:
            continue
        # Stop at a shell operator: what follows belongs to the next command, not argv.
        argv: list[str] = []
        for part in parts[1:]:
            if part in {"&&", "||", "|", ";", ">", "<", "2>&1"}:
                break
            argv.append(part)
        found.append((parts[0], argv))
    return found, unparseable


_PER_BOOK = {book.name: _invocations(book.read_text()) for book in _RUNBOOKS}

_CASES = [
    pytest.param(name, command, argv, id=f"{Path(name).stem}::{command}::{index}")
    for name, (invocations, _) in _PER_BOOK.items()
    for index, (command, argv) in enumerate(invocations)
]


# --- Layer 1: can an operator paste it at all? -----------------------------------------


@pytest.mark.parametrize(
    ("book", "line", "region"),
    [pytest.param(*row, id=f"{Path(row[0]).stem}::{row[1]}") for row in _regions_with_commands()],
)
def test_every_documented_command_block_is_shell_parseable(
    book: str, line: int, region: str
) -> None:
    """A block with an unbalanced quote cannot be copy-pasted, whatever argparse thinks.

    Found live in `backup-recovery-sheet.md` — the card someone prints and reads when the
    instance is already gone — where the restore step opened `sh -c '` and the block ended
    three lines later with the quote still open. Every other layer in this file passed on it.
    """
    _, unterminated = _logical_commands(region)
    assert not unterminated.strip(), (
        f"docs/runbooks/{book}, code block at line {line}, ends with a quote still open, so "
        f"the command cannot be pasted into a shell:\n\n    {unterminated.strip()}\n\n"
        "Close the quote. This is the emergency-recovery-card class of defect: the argument "
        "check below passes, because the broken quote sits before `manage.py`."
    )


def test_the_shell_parse_layer_can_actually_fail() -> None:
    """Non-vacuity, from both sides: the walker must accept a multi-line quoted command and
    reject an unterminated one. Without this the check above would go quiet if
    `_logical_commands` ever started returning an empty tail unconditionally."""
    good = "docker compose exec -T web sh -c '\n  python -c \"print(1)\"\n'"
    commands, unterminated = _logical_commands(good)
    assert commands and not unterminated, "a balanced multi-line quote must be accepted"

    bad = "docker compose exec -T web sh -c 'python manage.py restore_instance /x.bak"
    _, unterminated = _logical_commands(bad)
    assert unterminated.strip(), "an unterminated quote must be reported"


# --- Layer 2: do the arguments match the real parser? ----------------------------------


def test_no_documented_invocation_is_dropped_from_the_corpus() -> None:
    """Anything the extractor cannot tokenise is a failure, never a silent removal.

    The previous version turned an unparseable tail into `None` and the caller into
    `continue`, which deleted the command from the test corpus. Measured before this test
    existed: two invocations in `founder-qa.md` were being discarded that way.
    """
    dropped = {name: tails for name, (_, tails) in _PER_BOOK.items() if tails}
    assert not dropped, (
        f"these documented invocations could not be tokenised, so they were being checked "
        f"by nothing: {dropped}. Fix the command, or fix `_shell_words` — do not let it "
        "return None."
    )


def test_documented_command_coverage_is_what_we_think() -> None:
    """The denominator, named rather than counted.

    A count floor (`len(_CASES) >= 5`) stayed green while four of our eight commands were
    covered by nothing, and would have survived deleting an entire runbook. This pins the
    set, so a command falling out of the docs fails here and a NEW command forces an
    explicit decision: document it, or record why an operator never types it.
    """
    covered = {command for _, (invocations, _) in _PER_BOOK.items() for command, _ in invocations}
    unexplained = sorted(_OURS - covered - set(_NOT_OPERATOR_FACING))
    assert not unexplained, (
        f"{unexplained} are management commands that appear in no runbook and are not "
        "listed in _NOT_OPERATOR_FACING. Either document the command, or add it there with "
        "the reason an operator never runs it."
    )
    stale = sorted(set(_NOT_OPERATOR_FACING) - _OURS)
    assert not stale, f"_NOT_OPERATOR_FACING names commands that no longer exist: {stale}"


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


# --- Layer 3: the startability the argparse check cannot see ---------------------------


def _container_manage_invocations() -> list[tuple[str, str]]:
    """Every `docker compose exec … manage.py …` command in the runbooks.

    Built from `_logical_commands` rather than a substring scan so that a command wrapped
    across lines is one entry, and so `_CONTAINER_EXEC` does the matching it was compiled
    for. It was previously defined and never used, while the scan tested
    `"compose" in line and "exec" in line` — three substrings standing in for a pattern.
    """
    found = []
    for book, _, region in _regions_with_commands():
        commands, _ = _logical_commands(region)
        for command in commands:
            flat = " ".join(command.split())
            if _CONTAINER_EXEC.search(flat) and "manage.py" in flat:
                found.append((book, flat))
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
    ("book", "command"),
    [
        pytest.param(book, command, id=f"{Path(book).stem}::{index}")
        for index, (book, command) in enumerate(_container_manage_invocations())
    ],
)
def test_every_container_command_supplies_the_secret_key(book: str, command: str) -> None:
    """A documented command must be able to START, not merely parse its arguments.

    The argparse check above validates the SHAPE of the arguments. It cannot see this,
    because `config/settings.py` raises before argparse is ever reached:

        RuntimeError: DJANGO_SECRET_KEY is empty, a placeholder, or too short

    The entrypoint generates the key at boot, writes it to /data/secret_key and exports it
    for gunicorn only. A fresh `docker compose exec` gets the container's CONFIGURED
    environment, which has never contained it -- so every documented command that omits
    `DJANGO_SECRET_KEY=$(cat /data/secret_key)` dies before doing anything.

    Asserted on the ASSIGNMENT, not on the path. The first version of this looked for the
    lowercase substring `secret_key`, which the path `/data/secret_key` satisfies wherever
    it appears -- including in a line that never sets the variable at all.

    Verified against the live production instance: the bare form returns that RuntimeError,
    the sourced form returns the command's own --help. Seven invocations across four files
    were broken this way, including the printed emergency recovery card -- the one someone
    reads when the instance is already gone.
    """
    assert "DJANGO_SECRET_KEY=" in command, (
        f"docs/runbooks/{book} runs manage.py in the container without supplying "
        f"DJANGO_SECRET_KEY, so it exits with a RuntimeError before it starts:\n\n"
        f"    {command}\n\n"
        "Wrap it: sh -c 'DJANGO_SECRET_KEY=$(cat /data/secret_key) python manage.py …'"
    )
