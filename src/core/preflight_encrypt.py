"""Encrypt the entrypoint's pre-flight dump (TS-CO-2, T-BACKUP-1, S-802).

The pre-flight dump is the ENTIRE family database, written to /data before every migration
on every container start, three copies deep. It has to be encrypted whenever the operator
has configured a passphrase by EITHER route, and the entrypoint is a `/bin/sh` script that
cannot be unit-tested — so the decision ("is there a passphrase, and what is it") lives
here, in a module the suite exercises, and the shell only reports what this returned.

It imports `backup_passphrase`, which is the same resolver `backup_instance` and the
nightly run use. That is the whole point: this file existing as an inline python -c snippet
with its own idea of where the passphrase lives is what left the keyfile configuration —
the one the self-host guide RECOMMENDS — writing plaintext on every boot.

Django is deliberately not imported: this runs before `manage.py migrate`, before the
SECRET_KEY exists on a first boot, as the migrator rather than the app role.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .backup_crypto import encrypt
from .backup_passphrase import BackupPassphraseError, resolve

# A distinct exit code, because the two failures need OPPOSITE words from the entrypoint:
# "no passphrase is configured, so this dump is plaintext — set one" is an instruction to
# the operator, while a raised BackupPassphraseError (a group-readable keyfile, a binary
# one) means a passphrase IS configured and something is wrong with it. Collapsing them
# would tell an operator with a broken keyfile to go and set a passphrase they already set.
NO_PASSPHRASE = 3


def main(argv: list[str]) -> int:
    """Encrypt argv[0] into argv[1]. 0 encrypted, NO_PASSPHRASE none configured, 1 failed."""
    source, destination = Path(argv[0]), Path(argv[1])
    try:
        passphrase = resolve()
    except BackupPassphraseError as exc:
        print(f"pre-flight backup: {exc}", file=sys.stderr)
        return 1
    if passphrase is None:
        return NO_PASSPHRASE
    # 0600 and O_TRUNC, like every other archive this product writes: the ciphertext is the
    # whole database, and a partial file from an earlier crash must not survive underneath.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with source.open("rb") as plain, os.fdopen(fd, "wb") as out:
            encrypt(plain, out, passphrase)
    except (OSError, ValueError) as exc:
        # The caller removes the half-written ciphertext and says the plaintext dump is
        # still there; what it must never do is proceed as though the dump were encrypted.
        print(f"pre-flight backup encryption failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - the entrypoint calls main() directly
    sys.exit(main(sys.argv[1:]))
