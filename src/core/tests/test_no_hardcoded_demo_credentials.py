"""No credential literal lives in the seed and QA tooling.

This guard exists because one did, and it was live. `scripts/demo_seed.py` carried
`PW = "<a fixed password a person chose>"` in the public repository while that exact
password signed in to
the internet-reachable production instance as a seeded member. The line beside it read
"a disposable demo credential, wiped before any share" — a promise about a future action,
guarding a credential that worked that minute. **A comment is not a guard.**

The existing secrets gate did not catch it and structurally could not: gitleaks scanned 287
commits and reported no leaks, because a human-chosen password assigned to `PW` looks nothing
like a provider API key, and the CI selftest that proves the gate non-vacuous plants an
AWS-shaped key — so it proves the scanner works for exactly the class this was not. That is
the gap this file closes, and it is the class a hobbyist self-hoster is most likely to commit.

Checked with `ast`, not a text search, so a comment beside the assignment cannot defeat it and
reformatting cannot either. Two shapes are caught, because the second is where the other seed
script hid its literal:

    PASSWORD = "hunter2"                             # a constant on a credential-named target
    PW = os.environ.get("SOME_PASSWORD", "hunter2")  # a literal FALLBACK, which reads env-driven

Scope is the tooling that mints logins (`scripts/`, `docs/design/tools/`). Application code
gets its credentials from `Settings`, which is a separate rule enforced elsewhere; test
fixtures are deliberately synthetic and out of scope.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess

# "key" is deliberately absent: it collides with dictionary-key locals and would make the
# guard noisy enough that someone eventually allowlists their way around it.
_CREDENTIAL_WORDS = (
    "pw",
    "pass",
    "password",
    "passwd",
    "passphrase",
    "secret",
    "token",
    "credential",
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

# Python scanned with `ast`. `src` is included because the original guard omitted it while
# the leaked credential was re-published into src/core/tests/ -- inside the one directory
# gitleaks was also allowlisting, so nothing at all covered it.
_SCANNED_DIRS = ("scripts", "docs/design/tools", "src")

# Prose scanned as text. This is the gap that let the SAME credential be re-published three
# times AFTER it was removed from code: an `ast` check cannot see a password quoted in a
# markdown receipt, and gitleaks is blind to a low-entropy one. Both misses at once is how a
# value the repo declared "no longer published" sat in five tracked files.
_SCANNED_DOC_DIRS = ("docs",)

# Values that are permitted to appear as literals anywhere, because they are synthetic and
# exist to make the guards testable. Anything NOT on this list is a finding. Kept in step
# with the allowlist in .gitleaks.toml -- a test below asserts they do not drift.
_ALLOWED_LITERALS = frozenset(
    {
        "a-Strong-passphrase-9",
        "a-fine-passphrase-1234",
        "correct-horse-battery-staple-42",
        "old-Passphrase-9",
        "aX9!mnpq2ffz",
        "a-literal-password",
        "correct horse battery staple",
        "a-drill-migrator-passphrase-1",
        "a-fine-password-1234",
        "solitude-92",
    }
)

# Credentials this project is known to have published. They are dead or being rotated, and
# they must never reappear in any tracked file -- including in prose explaining the incident,
# which is exactly how each one came back.
#
# ASSEMBLED AT RUNTIME, and do not "tidy" this into plain literals. The first attempt wrote
# them as adjacent string literals ("backyard" "-qa-" "2026") and `ruff format` helpfully
# folded them straight back into the published value -- so the file enforcing "this credential
# appears nowhere" published it on line 82. A join() is a call, and no formatter folds a call.
_BURNED_CREDENTIALS = (
    "-".join(("backyard", "qa", "2026")),
    "-".join(("local", "demo", "only", "not", "a", "secret")),
)

# A credential-shaped env var read with a literal fallback is still a committed credential.
_ENV_READERS = ("get", "getenv")


def _is_credential_name(name: str) -> bool:
    lowered = name.lower()
    return any(word in lowered for word in _CREDENTIAL_WORDS)


def _findings(source: str, label: str, allowed: frozenset[str] = frozenset()) -> list[str]:
    """Every credential literal in one module, as human-readable findings.

    `allowed` is applied HERE rather than by filtering the returned strings, because a
    finding deliberately does not contain the offending value -- printing it would put a
    credential into CI output, which is the mistake this whole file exists to stop.
    """
    found: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        # Shape 1: NAME = "literal"
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str) and node.value.value not in allowed | {""}:
                for target in node.targets:
                    name = getattr(target, "id", None) or getattr(target, "attr", None)
                    if name and _is_credential_name(name):
                        found.append(f"{label}:{node.lineno} {name} = <string literal>")

        # Shape 2: os.environ.get("SOMETHING_PASSWORD", "literal") / os.getenv(..., "literal")
        if isinstance(node, ast.Call) and len(node.args) >= 2:
            attr = getattr(node.func, "attr", None)
            if attr in _ENV_READERS:
                key, default = node.args[0], node.args[1]
                if not (isinstance(key, ast.Constant) and isinstance(default, ast.Constant)):
                    continue
                key_name, fallback = key.value, default.value
                if (
                    isinstance(key_name, str)
                    and _is_credential_name(key_name)
                    and isinstance(fallback, str)
                    and fallback
                    and fallback not in allowed
                ):
                    found.append(f"{label}:{node.lineno} {key_name} read with a literal fallback")
    return found


def _scanned_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for directory in _SCANNED_DIRS:
        files.extend(sorted((_REPO_ROOT / directory).rglob("*.py")))
    return files


def _doc_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for directory in _SCANNED_DOC_DIRS:
        files.extend(sorted((_REPO_ROOT / directory).rglob("*.md")))
    return files


def _tracked_files() -> list[pathlib.Path]:
    """Files git actually tracks, because "tracked" is what the disclosure claim is about.

    Said "tracked" while walking the filesystem before review pointed it out: `rglob` picks up
    untracked local work (agent worktrees, a local .env, __pycache__) and would fail the build
    on files that were never published, which is how a real guard gets dismissed as noisy.
    Falls back to the filesystem walk when there is no git -- a source tarball still gets
    checked, just less precisely.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return _scanned_files() + _doc_files()
    paths = [_REPO_ROOT / rel for rel in out.split("\0") if rel]
    return [p for p in paths if p.suffix in {".py", ".md", ".yml", ".yaml", ".toml", ".sh"}]


def test_every_scanned_directory_actually_has_files() -> None:
    """Per-directory, not a global count.

    The previous floor was `len(scanned) >= 4` against a real scope of 8 files across two
    directories -- so deleting or renaming `docs/design/tools/` entirely left 4 and the guard
    stayed green with half its scope silently retired, including the file that hid the
    literal-fallback shape. A global count cannot detect the loss of a directory.
    """
    for directory in _SCANNED_DIRS + _SCANNED_DOC_DIRS:
        root = _REPO_ROOT / directory
        assert root.is_dir(), f"{directory} is gone -- the guard's scope shrank silently"
        pattern = "*.md" if directory in _SCANNED_DOC_DIRS else "*.py"
        # next(), not list(): this only has to prove non-emptiness, and `src/` is a big walk.
        assert next(root.rglob(pattern), None) is not None, (
            f"{directory} matched no {pattern} files"
        )


def test_the_seed_and_qa_tooling_carries_no_credential_literal() -> None:
    scanned = _scanned_files()
    findings: list[str] = []
    for path in scanned:
        rel = path.relative_to(_REPO_ROOT).as_posix()
        findings.extend(_findings(path.read_text(), rel, allowed=_ALLOWED_LITERALS))
    assert not findings, (
        "credential literals in scanned code (add a genuinely synthetic value to "
        "_ALLOWED_LITERALS *and* .gitleaks.toml):\n  " + "\n  ".join(findings)
    )


def test_no_burned_credential_reappears_in_any_tracked_file() -> None:
    """The one that would have caught all three re-leaks.

    Every previously-published credential, searched for as plain text across code AND prose.
    A password quoted in a markdown receipt is the same disclosure as one in a script, and
    is invisible to both an `ast` check and to a scanner tuned for high entropy.
    """
    hits: list[str] = []
    for path in _tracked_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel == "src/core/tests/test_no_hardcoded_demo_credentials.py":
            continue  # this file names them, split, in _BURNED_CREDENTIALS
        text = path.read_text()
        for burned in _BURNED_CREDENTIALS:
            if burned in text:
                line = text[: text.index(burned)].count("\n") + 1
                hits.append(f"{rel}:{line} republishes a burned credential")
    assert not hits, "a previously-published credential is back in the tree:\n  " + "\n  ".join(
        hits
    )


def test_the_burned_list_and_the_gitleaks_allowlist_do_not_drift() -> None:
    """The synthetic-fixture allowlist here and in .gitleaks.toml must stay in step, or one
    gate starts reporting what the other exempts and somebody silences the wrong one."""
    config = (_REPO_ROOT / ".gitleaks.toml").read_text()
    missing = [v for v in _ALLOWED_LITERALS if v not in config]
    assert not missing, f"allowed literals absent from .gitleaks.toml: {missing}"


def test_the_guard_catches_a_plain_assignment() -> None:
    # A synthetic literal on purpose. The earlier version of this line used the REAL leaked
    # password as its fixture, which re-published it inside the very guard written to stop that
    # -- and inside the one directory the gitleaks allowlist blanket-hid. The assertion is
    # identical for any literal, so there was never a reason to use the live one.
    assert _findings('PW = "a-literal-password"\n', "fixture") == [
        "fixture:1 PW = <string literal>"
    ]


def test_the_guard_catches_a_literal_env_fallback() -> None:
    # The shape the OTHER seed script actually used. A guard that only knew shape 1 would
    # have reported this file clean while a working password sat in it.
    source = 'import os\nPW = os.environ.get("BACKYARD_DEMO_PASSWORD", "local-demo-only")\n'
    assert _findings(source, "fixture") == [
        "fixture:2 BACKYARD_DEMO_PASSWORD read with a literal fallback"
    ]


def test_the_guard_catches_an_attribute_target() -> None:
    assert _findings('cfg.password = "hunter2"\n', "fixture") == [
        "fixture:1 password = <string literal>"
    ]


def test_the_guard_accepts_the_generated_and_env_driven_forms() -> None:
    # The shapes the fixed scripts use, so the guard cannot be satisfied only by deleting
    # the seeding altogether.
    clean = (
        "import os, secrets\n"
        'PW = os.environ.get("BACKYARD_DEMO_PASSWORD") or secrets.token_urlsafe(12)\n'
        'MFA_PW = sys.argv[6] if len(sys.argv) > 6 else ""\n'
        'ELDER_TOKEN = os.environ["ELDER_TOKEN"]\n'
    )
    assert _findings(clean, "fixture") == []


def test_a_non_credential_name_is_not_flagged() -> None:
    # The guard has to stay quiet on ordinary strings or it gets allowlisted into uselessness.
    assert _findings('GREETING = "hello"\nsort_field = "display_name"\n', "fixture") == []
