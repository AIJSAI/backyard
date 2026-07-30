"""No credential literal lives in the seed and QA tooling.

This guard exists because one did, and it was live. `scripts/demo_seed.py` carried
`PW = "backyard-qa-2026"` in the public repository while that exact password signed in to
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
_SCANNED_DIRS = ("scripts", "docs/design/tools")

# A credential-shaped env var read with a literal fallback is still a committed credential.
_ENV_READERS = ("get", "getenv")


def _is_credential_name(name: str) -> bool:
    lowered = name.lower()
    return any(word in lowered for word in _CREDENTIAL_WORDS)


def _findings(source: str, label: str) -> list[str]:
    """Every credential literal in one module, as human-readable findings."""
    found: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        # Shape 1: NAME = "literal"
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str) and node.value.value:
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
                ):
                    found.append(f"{label}:{node.lineno} {key_name} read with a literal fallback")
    return found


def _scanned_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for directory in _SCANNED_DIRS:
        files.extend(sorted((_REPO_ROOT / directory).rglob("*.py")))
    return files


def test_the_seed_and_qa_tooling_carries_no_credential_literal() -> None:
    scanned = _scanned_files()
    # Guard the guard: an empty file list would make this pass while checking nothing, which
    # is how a path rename silently retires a gate.
    assert len(scanned) >= 4, f"expected to scan the seed/QA tooling, found {scanned}"

    findings: list[str] = []
    for path in scanned:
        findings.extend(_findings(path.read_text(), path.relative_to(_REPO_ROOT).as_posix()))
    assert not findings, "credential literals in seed/QA tooling:\n  " + "\n  ".join(findings)


def test_the_guard_catches_a_plain_assignment() -> None:
    assert _findings('PW = "backyard-qa-2026"\n', "fixture") == ["fixture:1 PW = <string literal>"]


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
