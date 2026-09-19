"""Where the backup passphrase comes from, and that every caller asks the same question.

The defect these pin (#166 review): the entrypoint's pre-flight dump — the entire family
database, written to /data before every migration on every boot — knew only
`BACKYARD_BACKUP_PASSPHRASE`. The self-host guide RECOMMENDS the other route, a 0600
keyfile with the env var deliberately unset, because the env value is visible to `docker
inspect`. An operator who took that advice got a PLAINTEXT copy of everything, three copies
deep, with one line in a container log as the only signal — T-BACKUP-1 and T-MEDIA-5
reopened by the documentation that was supposed to close them.

So the rule lives in one module and the callers ask it. These tests cover the rule, the
pre-flight caller that had its own idea of it, and the compose wiring without which the
variable never reaches the container that takes the dump. The finding's own words: neither
half works alone.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from core import backup_crypto, backup_passphrase, preflight_encrypt

# The synthetic value the credential guard and .gitleaks.toml already know about, rather
# than a new credential-shaped literal in this repository.
_PASSPHRASE = "a-fine-passphrase-1234"

_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _no_ambient_passphrase(monkeypatch: Any) -> None:
    """Neither route configured, unless the test says so. The runner's own environment
    deciding the answer is how a test about configuration stops testing anything."""
    monkeypatch.delenv(backup_passphrase.ENV_VAR, raising=False)
    monkeypatch.delenv(backup_passphrase.FILE_ENV_VAR, raising=False)


def _keyfile(tmp_path: Path, secret: str = _PASSPHRASE, mode: int = 0o600) -> Path:
    path = tmp_path / "backyard.key"
    path.write_text(secret, encoding="utf-8")
    path.chmod(mode)
    return path


# ---------------------------------------------------------------- the rule itself


def test_neither_route_configured_is_none_rather_than_an_error() -> None:
    """A legitimate state with three different right answers (the command refuses, the
    pre-flight warns, the nightly run records a failure), so the resolver reports it
    instead of deciding."""
    assert backup_passphrase.resolve() is None


def test_the_environment_variable_is_read(monkeypatch: Any) -> None:
    monkeypatch.setenv(backup_passphrase.ENV_VAR, _PASSPHRASE)

    assert backup_passphrase.resolve() == _PASSPHRASE


def test_the_configured_keyfile_is_read_with_no_flag_to_pass(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """The recommended configuration, and the one that used to work for exactly one of the
    three callers. Neither the entrypoint nor a periodic task has a command line."""
    monkeypatch.setenv(backup_passphrase.FILE_ENV_VAR, str(_keyfile(tmp_path)))

    assert backup_passphrase.resolve() == _PASSPHRASE


def test_an_explicit_keyfile_beats_the_environment(monkeypatch: Any, tmp_path: Path) -> None:
    """An operator who typed a path means that file, not whatever the container holds."""
    monkeypatch.setenv(backup_passphrase.ENV_VAR, "the-environment-one-1234")

    assert backup_passphrase.resolve(str(_keyfile(tmp_path))) == _PASSPHRASE


def test_the_environment_beats_the_configured_keyfile(monkeypatch: Any, tmp_path: Path) -> None:
    """Both set is a configuration in transition, not an error. It resolves the same way
    for all three callers, which is the property that matters: an instance where the
    pre-flight dump and the nightly archive used DIFFERENT keys would be unrestorable in
    exactly the half the operator did not test."""
    other = _keyfile(tmp_path, "the-keyfile-one-12")
    monkeypatch.setenv(backup_passphrase.ENV_VAR, _PASSPHRASE)
    monkeypatch.setenv(backup_passphrase.FILE_ENV_VAR, str(other))

    assert backup_passphrase.resolve() == _PASSPHRASE


def test_a_group_readable_configured_keyfile_is_refused(monkeypatch: Any, tmp_path: Path) -> None:
    """The same refusal the typed `--passphrase-file` has always applied. A key every
    process on the box can read is not a key, and this route is the one being recommended."""
    monkeypatch.setenv(backup_passphrase.FILE_ENV_VAR, str(_keyfile(tmp_path, mode=0o644)))

    with pytest.raises(backup_passphrase.BackupPassphraseError, match="readable by other users"):
        backup_passphrase.resolve()


def test_a_missing_configured_keyfile_is_an_error_not_silence(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """Falling back to "no passphrase" would answer a typo with a plaintext archive."""
    monkeypatch.setenv(backup_passphrase.FILE_ENV_VAR, str(tmp_path / "never-mounted.key"))

    with pytest.raises(backup_passphrase.BackupPassphraseError, match="not found"):
        backup_passphrase.resolve()


def test_a_short_passphrase_is_refused_by_either_route(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv(backup_passphrase.FILE_ENV_VAR, str(_keyfile(tmp_path, "hunter2")))

    with pytest.raises(backup_passphrase.BackupPassphraseError, match="too short"):
        backup_passphrase.resolve()


# ---------------------------------------------------------------- the pre-flight dump


def _dump(tmp_path: Path) -> tuple[Path, Path]:
    plain = tmp_path / "preflight-20260918000000.dump"
    plain.write_bytes(b"PGDMP" + b"the whole family database" * 100)
    return plain, tmp_path / "preflight-20260918000000.dump.enc"


def test_the_preflight_dump_is_encrypted_from_the_environment(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv(backup_passphrase.ENV_VAR, _PASSPHRASE)
    plain, encrypted = _dump(tmp_path)

    assert preflight_encrypt.main([str(plain), str(encrypted)]) == 0
    assert encrypted.read_bytes().startswith(backup_crypto.MAGIC)


def test_the_preflight_dump_is_encrypted_from_the_recommended_keyfile(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """THE defect. This configuration — keyfile mounted, env var unset — is what both
    runbooks tell the operator to set up, and it left the whole database in the clear on
    /data on every container start."""
    monkeypatch.setenv(backup_passphrase.FILE_ENV_VAR, str(_keyfile(tmp_path)))
    plain, encrypted = _dump(tmp_path)

    assert preflight_encrypt.main([str(plain), str(encrypted)]) == 0
    assert encrypted.read_bytes().startswith(backup_crypto.MAGIC)
    # And it is a real archive, not merely a file with the right first bytes.
    written = tmp_path / "round-trip"
    with encrypted.open("rb") as source, written.open("wb") as out:
        backup_crypto.decrypt(source, out, _PASSPHRASE)
    assert written.read_bytes() == plain.read_bytes()


def test_the_preflight_dump_reports_no_passphrase_distinctly(tmp_path: Path) -> None:
    """Not an error: the entrypoint's answer to this is the loud plaintext warning, which
    is a different sentence from "your keyfile is broken"."""
    plain, encrypted = _dump(tmp_path)

    assert preflight_encrypt.main([str(plain), str(encrypted)]) == preflight_encrypt.NO_PASSPHRASE
    assert not encrypted.exists()


def test_a_broken_keyfile_never_reads_as_no_passphrase(monkeypatch: Any, tmp_path: Path) -> None:
    """The dangerous direction: a passphrase IS configured, so silently treating this as
    "none configured" would leave the dump plaintext while the operator believes otherwise."""
    monkeypatch.setenv(backup_passphrase.FILE_ENV_VAR, str(_keyfile(tmp_path, mode=0o644)))
    plain, encrypted = _dump(tmp_path)

    assert preflight_encrypt.main([str(plain), str(encrypted)]) == 1
    assert not encrypted.exists()


# ---------------------------------------------------------------- the wiring


def _service_block(text: str, service: str) -> str:
    """One compose service's body, by indentation. (No PyYAML in the test venv.)"""
    body: list[str] = []
    capturing = False
    for line in text.splitlines():
        if re.match(rf"^  {re.escape(service)}:\s*$", line):
            capturing = True
            continue
        if capturing and line.strip() and not line.startswith("    "):
            break
        if capturing:
            body.append(line)
    assert body, f"no {service} service in docker-compose.yml"
    return "\n".join(body)


def test_compose_passes_the_keyfile_path_to_BOTH_containers_that_encrypt() -> None:
    """The other half of the defect, which no amount of Python fixes: the variable was
    passed to the worker only, and the pre-flight dump runs in WEB's entrypoint."""
    compose = (_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    for service in ("web", "worker"):
        assert backup_passphrase.FILE_ENV_VAR in _service_block(compose, service), (
            f"{service} never receives {backup_passphrase.FILE_ENV_VAR}, so a keyfile "
            "mounted into it is not read by anything"
        )


def test_the_entrypoint_delegates_the_passphrase_decision() -> None:
    """The shell cannot be unit-tested, so what is pinned here is that it no longer HOLDS
    the decision: it calls the module the tests above exercise. The old gate,
    `if [ -n "${BACKYARD_BACKUP_PASSPHRASE:-}" ]`, is what made the keyfile invisible."""
    entrypoint = (_ROOT / "entrypoint.sh").read_text(encoding="utf-8")

    assert "preflight_encrypt" in entrypoint
    assert 'if [ -n "${BACKYARD_BACKUP_PASSPHRASE:-}" ]' not in entrypoint
