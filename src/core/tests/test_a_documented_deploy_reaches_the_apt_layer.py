"""A documented REDEPLOY must rebuild with `--pull`, and must chain that build into the `up`.

The defect: the app image installs `postgresql-client-18` and `ffmpeg` in a layer above the
application code, so nothing an ordinary upgrade changes can invalidate it. `docker compose
up --build` never re-resolves `python:3.13-slim`, so both binaries stay at the versions of
the day the box was first built -- on the process that decodes video somebody sent your
family, and the one that takes your pre-flight backup of the whole database.

Two rules, because fixing the first one opened the second:

1. **A redeploy builds with `--pull`.** `up --build` is correct for a FIRST install (there is
   no cached base to go stale) and wrong everywhere else. The first fix reached the two
   runbooks a stranger reads and missed `docs/RESUME-HERE.md`, which is the command the one
   live instance is actually redeployed with -- so the defect survived in the only place it
   was being hit.
2. **The build is CHAINED to the `up`.** `up --build -d` was a single command: a failed build
   started nothing. Split into two unchained lines, a failed build (a registry timeout, a
   full disk) is followed unconditionally by an `up -d` that starts the PREVIOUS image, and
   in `handover.md` the line after that printed `serving`. Splitting the command must not
   cost the atomicity it had.

Both rules are checked against the fenced CODE BLOCKS of the named region, never the prose
around them: these documents deliberately discuss `up --build` in order to tell you not to
use it, and a substring scan reads that explanation as the defect it warns about.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]

# Dated records of what was true when they were written. Rewriting one to keep a scan clean
# is how a project loses the ability to trust its own history -- the same carve-out, for the
# same reason, as `test_documented_version_resolves.py`.
#
# `docs/archive/` joined them when `RESUME-HERE.md` was replaced with a current one and the
# superseded handoff was kept rather than deleted. It carries a deploy command that was real
# in August and is not how this instance is deployed now; holding it to the live rules would
# either fail the build for preserving history or push somebody to edit the record.
_RECORD_DIRECTORIES = (
    "docs/archive",
    "docs/audits",
    "docs/receipts",
    "docs/retro",
    "docs/research",
)

_SUFFIXES = {".md", ".yml", ".yaml", ".py", ".sh", ""}

# A compose invocation that BUILDS the app image, in ANY form. Anything matching this is a
# place the frozen-apt-layer defect can live.
#
# It used to spell out three shapes -- `up --build`, `--build … up`, and `build --pull` -- and
# so could not see a bare `docker compose build` (issue 169). That is the one shape a future
# document reaches by DROPPING the flag this file exists to require, which made the blind spot
# point exactly at the defect: a redeploy doc that lost `--pull` stopped being classified, so
# the denominator below never forced a decision about it and the two rules never ran on it.
# `build` covers all four, since `--build` contains it.
_BUILDING_COMPOSE = re.compile(r"docker compose\b[^\n]*?\bbuild\b")

_UP_THAT_BUILDS = re.compile(r"\bup\b[^\n]*?--build|--build[^\n]*?\bup\b")

# `build --pull …` reaching an `up` with nothing but `&&` between them. Applied to a region
# whose backslash continuations have been flattened, so a command wrapped for width is one
# line here exactly as it is one command in a shell.
_CHAINED_INTO_UP = re.compile(r"build\s+--pull\b[^\n]*?&&[^\n]*?\bup\b")

# Bringing a stack up from a FRESH checkout, where there is no cached base layer to go
# stale. `up --build` is the right command in each of these, and the reason is named so that
# a new one cannot be waved through as "probably a first install too".
_FIRST_INSTALL = {
    "README.md": "the install command, run seconds after `git clone`",
    "docs/runbooks/self-host.md": "section 3, 'Start it' -- the first boot of a new instance",
    "docs/runbooks/live-repro.md": "provisioning a brand-new VM from nothing",
    "docker-compose.prod.yml": "the overlay's header, which names the first install AND the"
    " `build --pull` redeploy below it",
    "Makefile": "`make up` is the local dev stack on a developer's machine",
    ".github/workflows/ci.yml": "a runner starts with no image cache at all",
}

# Redeploying or upgrading an instance that ALREADY EXISTS: (path, the heading that opens the
# region, what the region is for). The anchor is a heading rather than a line number so that
# editing the document above it cannot silently move the check off its target.
_REDEPLOY = (
    (
        "docs/runbooks/self-host.md",
        "## Upgrades",
        "a self-hoster moving an existing box to a new tag",
    ),
    (
        "docs/runbooks/handover.md",
        "## 2. Rotate every secret",
        "the last build before somebody else owns the box",
    ),
    (
        "docs/RESUME-HERE.md",
        "## Deploying (there is no automation)",
        "the deploy that actually happens, against the one live instance",
    ),
    (
        "docs/runbooks/move-to-a-new-server.md",
        "## 4. Build the image and start the app, with Caddy held back",
        "standing an existing instance back up on new hardware",
    ),
)

# Files that NAME a building compose command without instructing anybody to deploy. Listed
# rather than pattern-matched out, because "it is only prose" is exactly the claim that
# should cost somebody a line in this file.
_PROSE_ONLY = {
    "Dockerfile": "the FROM comment explains why `up --build` cannot reach the apt layer",
    "scripts/check_compose_overlay.py": "its docstring quotes CI's and the README's commands"
    " to explain the delta between them",
    "src/core/tests/test_a_documented_deploy_reaches_the_apt_layer.py": "this file's own"
    " fixtures, which are command-shaped on purpose",
}


def _tracked_files() -> list[Path]:
    found = []
    for path in _ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in _SUFFIXES:
            continue
        parts = path.relative_to(_ROOT).parts
        if path.relative_to(_ROOT).as_posix().startswith(_RECORD_DIRECTORIES):
            continue
        if any(part.startswith(".") and part != ".github" for part in parts):
            continue
        found.append(path)
    return found


def _files_that_build() -> set[str]:
    """Every live file containing a compose command that builds the app image."""
    return {
        path.relative_to(_ROOT).as_posix()
        for path in _tracked_files()
        if _BUILDING_COMPOSE.search(path.read_text(encoding="utf-8", errors="ignore"))
    }


def _region(document: str, anchor: str) -> str:
    """The document from `anchor` up to the next `##` heading."""
    lines = (_ROOT / document).read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index(anchor)
    except ValueError:
        return ""
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body)


def _shell_lines(region: str) -> str:
    """The region's fenced code blocks, comments stripped and continuations flattened.

    Three reductions, each load-bearing. Only fenced blocks, because these documents explain
    at length why NOT to use `up --build` and a scan over prose reads the warning as the
    defect. No `#` comments, because `handover.md`'s block says "`build --pull` and not
    `up --build`" in one. And backslash continuations joined, because a command wrapped for
    width is still one command, which is the whole subject of the chaining rule.
    """
    lines = region.splitlines()
    kept: list[str] = []
    inside = False
    for line in lines:
        if line.lstrip().startswith("```"):
            inside = not inside
            continue
        if inside and not line.strip().startswith("#"):
            kept.append(line)
    return re.sub(r"\\\n\s*", " ", "\n".join(kept))


def test_every_building_compose_command_is_accounted_for() -> None:
    """The denominator, named rather than counted.

    The first fix for this defect landed in two runbooks and missed `RESUME-HERE.md`, which
    is the only document the live box is ever deployed from. A count would have gone green
    on two of three. This pins the set, so a NEW document that tells somebody to build forces
    the same decision: first install, redeploy, or prose.
    """
    classified = set(_FIRST_INSTALL) | {path for path, _, _ in _REDEPLOY} | set(_PROSE_ONLY)
    found = _files_that_build()
    unclassified = sorted(found - classified)
    assert not unclassified, (
        f"{unclassified} contain a compose command that builds the app image and are not "
        "classified in this file. Say which it is: a FIRST install (`up --build` is fine), a "
        "REDEPLOY (it must `build --pull` and chain that into the `up`), or prose that only "
        "names the command."
    )
    stale = sorted(classified - found)
    assert not stale, (
        f"{stale} are classified here but no longer contain a building compose command. "
        "Remove the entry, or find out why the command left the document — an entry for a "
        "file that no longer deploys anything is how this list stops describing the tree."
    )


@pytest.mark.parametrize(
    ("document", "anchor", "purpose"),
    [pytest.param(*row, id=f"{Path(row[0]).stem}") for row in _REDEPLOY],
)
def test_the_redeploy_region_exists(document: str, anchor: str, purpose: str) -> None:
    """Non-vacuity: an anchor that no longer matches would make both checks below pass on an
    empty string. Renaming the heading is a legitimate edit; silently disarming the guard
    that reads it is not."""
    region = _region(document, anchor)
    assert region.strip(), f"`{anchor}` is not a heading in {document} ({purpose})"
    assert _shell_lines(region).strip(), (
        f"the `{anchor}` region of {document} has no fenced command block left, so the "
        "checks below would pass without reading a command"
    )


@pytest.mark.parametrize(
    ("document", "anchor", "purpose"),
    [pytest.param(*row, id=f"{Path(row[0]).stem}") for row in _REDEPLOY],
)
def test_a_documented_redeploy_pulls_the_base_image(
    document: str, anchor: str, purpose: str
) -> None:
    """`up --build` reuses the cached base, so the pg client and ffmpeg never move."""
    commands = _shell_lines(_region(document, anchor))
    stale = _UP_THAT_BUILDS.search(commands)
    assert not stale, (
        f"{document} ({purpose}) redeploys with `{stale.group(0) if stale else ''}`, which "
        "builds on whatever base image the box already cached. The `pg_dump` client and the "
        "`ffmpeg` that decodes uploaded video sit in a layer only a re-resolved `FROM` can "
        "invalidate, so they would stay at their first-build versions forever. Use "
        "`build --pull`, chained into the `up`."
    )
    assert "build --pull" in commands, (
        f"{document} ({purpose}) names no `build --pull`, so nothing in this region refreshes "
        "the apt layer the app image installs pg_dump and ffmpeg into."
    )


@pytest.mark.parametrize(
    ("document", "anchor", "purpose"),
    [pytest.param(*row, id=f"{Path(row[0]).stem}") for row in _REDEPLOY],
)
def test_a_documented_redeploy_chains_the_build_into_the_up(
    document: str, anchor: str, purpose: str
) -> None:
    """A failed build must not be followed by an `up` that starts the previous image."""
    commands = _shell_lines(_region(document, anchor))
    assert _CHAINED_INTO_UP.search(commands), (
        f"{document} ({purpose}) runs `build --pull` and `up` as separate commands. The "
        "command they replaced (`up --build -d`) was atomic: a failed build started nothing. "
        "Unchained, a registry timeout or a full disk fails the build and the next line "
        f"brings the OLD image up anyway -- in handover.md the line after that prints "
        "`serving`. Join them with `&&`."
    )


def test_the_chaining_check_can_actually_fail() -> None:
    """Non-vacuity, from both sides. The rule this file exists for is one regex; if it ever
    matches everything, every assertion above goes quiet while still reporting green."""
    flags = "-f docker-compose.yml -f docker-compose.prod.yml"
    unchained = f"docker compose {flags} build --pull\ndocker compose {flags} up -d"
    assert not _CHAINED_INTO_UP.search(unchained), "two unchained lines must be rejected"

    chained = f"docker compose {flags} build --pull && docker compose {flags} up -d"
    assert _CHAINED_INTO_UP.search(chained), "a chained command must be accepted"

    wrapped = f"docker compose {flags} build --pull \\\n  && docker compose {flags} up -d"
    assert _CHAINED_INTO_UP.search(_shell_lines(f"```bash\n{wrapped}\n```")), (
        "a command wrapped across lines with a backslash is still one command"
    )

    assert _UP_THAT_BUILDS.search(f"docker compose {flags} up --build -d"), (
        "the stale-build shape must be recognised in both flag orders"
    )
    assert _UP_THAT_BUILDS.search(f"docker compose {flags} up -d --build")
    assert not _UP_THAT_BUILDS.search(f"docker compose {flags} up -d")


def test_every_shape_that_builds_the_image_enters_the_denominator() -> None:
    """The classification rule is only as wide as the regex that feeds it (issue 169).

    All four shapes must be seen, and the bare `build` is the one that was missed: it is what
    a document reaches by dropping the `--pull` these tests demand, so a doc could lose the
    flag and leave the set at the same time -- disarming the guard with the edit it exists to
    catch. And a compose command that builds NOTHING must stay out, or the denominator names
    every file that mentions compose and somebody prunes the list instead of the tree.
    """
    flags = "-f docker-compose.yml -f docker-compose.prod.yml"
    for command in (
        f"docker compose {flags} build",
        f"docker compose {flags} build --pull",
        f"docker compose {flags} up --build -d",
        f"docker compose {flags} up -d --build",
    ):
        assert _BUILDING_COMPOSE.search(command), f"{command!r} builds the image and was missed"

    for command in (
        f"docker compose {flags} up -d",
        f"docker compose {flags} down -v",
        "docker compose exec -T web sh -c 'python manage.py migrate'",
    ):
        assert not _BUILDING_COMPOSE.search(command), (
            f"{command!r} builds nothing, so reading it as a deploy would put files in the "
            "denominator that have no build decision to make"
        )


def test_the_prose_that_warns_about_up_build_is_not_read_as_a_command() -> None:
    """The guard has to survive the documents explaining themselves.

    `self-host.md` says "`up -d --build` never does" and `handover.md`'s block opens with
    "# `build --pull` and not `up --build`". Both are the correct advice; a scan that cannot
    tell them from an instruction fails the build for saying the true thing, which is how a
    guard gets deleted instead of fixed.
    """
    sample = "\n".join(
        (
            "Prose explaining that `docker compose up -d --build` cannot reach the layer.",
            "```bash",
            "# `build --pull` and not `up --build`: the base image gets refreshed",
            "docker compose build --pull && docker compose up -d",
            "```",
        )
    )
    commands = _shell_lines(sample)
    assert not _UP_THAT_BUILDS.search(commands), (
        "prose and in-block comments must not be read as commands"
    )
    assert _CHAINED_INTO_UP.search(commands), "the real command in the block must still be read"
