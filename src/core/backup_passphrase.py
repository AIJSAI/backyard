"""Where the backup passphrase comes from. ONE answer, for every caller (S-802, T-BACKUP-1).

There are three places that encrypt a copy of the whole family database — the entrypoint's
pre-flight dump before every migration, the operator's `backup_instance`/`restore_instance`
commands, and the nightly scheduled run — and there are two configured routes to the
passphrase: `BACKYARD_BACKUP_PASSPHRASE`, and a 0600 keyfile named by
`BACKYARD_BACKUP_PASSPHRASE_FILE` (the tighter one, which both runbooks recommend because
the env value is visible to `docker inspect`).

Three callers times two routes is where the last defect lived: the entrypoint knew only the
env var, so an operator who took the guide's tighter advice got a PLAINTEXT dump of the
entire database written to /data on every single boot, three copies deep, with a warning
line in a container log as the only signal. A second implementation of "where does the
passphrase come from" is how one of them comes to disagree with the others, and the failure
mode when they disagree is not an error — it is silence plus a plaintext archive.

So: one module, and it is deliberately STDLIB ONLY. The entrypoint runs before Django is
configured (it is what generates the SECRET_KEY and runs the migrations), so this cannot
read `django.conf.settings`; it reads the environment, which is where compose puts both
variables for both containers.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "BACKYARD_BACKUP_PASSPHRASE"
FILE_ENV_VAR = "BACKYARD_BACKUP_PASSPHRASE_FILE"

# Short enough not to fight a careful operator, long enough that the scrypt cost is doing
# work against a real guessing attack rather than covering for "hunter2".
MIN_PASSPHRASE_CHARS = 12


class BackupPassphraseError(Exception):
    """The configured passphrase route exists but cannot be used.

    Never confused with "no passphrase configured", which is a legitimate state (the
    caller decides what to do about it) and is reported by returning None. A misconfigured
    keyfile must not silently degrade into "no passphrase", because for two of the three
    callers "no passphrase" means a plaintext archive or none at all.
    """


def resolve(keyfile: str | None = None) -> str | None:
    """The configured passphrase, or None if no route is configured at all.

    Precedence, and why:

    1. an explicit `--passphrase-file` (`keyfile`), because an operator who typed a path on
       the command line means that file and not whatever the container's environment holds;
    2. `BACKYARD_BACKUP_PASSPHRASE`;
    3. the keyfile named by `BACKYARD_BACKUP_PASSPHRASE_FILE`.

    Never an argv passphrase: a secret on the command line lands in shell history and is
    visible to every process on the box.
    """
    if keyfile:
        return _from_keyfile(Path(keyfile))
    from_env = _normalise(os.environ.get(ENV_VAR, ""))
    if from_env is not None:
        return _checked(from_env)
    configured = os.environ.get(FILE_ENV_VAR, "").strip()
    if configured:
        return _from_keyfile(Path(configured))
    return None


def _from_keyfile(path: Path) -> str:
    if not path.is_file():
        raise BackupPassphraseError(f"passphrase file not found: {path}")
    if path.stat().st_mode & 0o077:
        raise BackupPassphraseError(
            f"passphrase file {path} is readable by other users; "
            "run `chmod 600` on it before using it as a key."
        )
    try:
        secret = _normalise(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        # `head -c 32 /dev/urandom > keyfile` is the obvious way to make a *keyfile*,
        # and it used to die with a UnicodeDecodeError that printed a byte of the key.
        raise BackupPassphraseError(
            f"passphrase file {path} is not UTF-8 text. Use a text passphrase "
            "(a diceware phrase is ideal); raw binary key material is not supported."
        ) from exc
    if secret is None:
        raise BackupPassphraseError(f"passphrase file is empty: {path}")
    return _checked(secret)


def _normalise(secret: str) -> str | None:
    """One normalisation for BOTH sources. Whitespace-only is nothing.

    The env path used to strip and the keyfile path did not, so the same secret produced
    two different keys (`'hunter2\\n'` vs `'hunter2'`) depending on which you used. With no
    key escrow that is not an inconvenience, it is the permanent loss of the only copy of a
    family's history — back up via the env var, restore via --passphrase-file, and the
    archive is gone.
    """
    return secret.strip() or None


def _checked(secret: str) -> str:
    if len(secret) < MIN_PASSPHRASE_CHARS:
        raise BackupPassphraseError(
            f"that backup passphrase is too short ({len(secret)} characters; "
            f"{MIN_PASSPHRASE_CHARS} is the minimum). There is no key escrow and no reset: "
            "this passphrase is the only thing standing between a stolen archive and every "
            "photo of your family. Use a diceware phrase of four or more words."
        )
    return secret
