"""Back up the whole instance to one archive (S-704 instance half, S-802).

One command captures the database and the media tree. Run in the migrator's
environment (POSTGRES_MIGRATOR_PASSWORD set); the runbook documents the wrapper
that does.

ENCRYPTED BY DEFAULT (S-802). The passphrase comes from the environment or a keyfile,
never from argv, so it cannot end up in shell history or a process listing. Plaintext
output is still possible — an operator whose storage layer already encrypts should not be
forced to double up — but it takes an explicit --no-encrypt and it says so loudly.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from core import backup_crypto, backups

ENV_VAR = "BACKYARD_BACKUP_PASSPHRASE"


# Short enough not to fight a careful operator, long enough that the scrypt cost is doing
# work against a real guessing attack rather than covering for "hunter2".
MIN_PASSPHRASE_CHARS = 12


def _normalise(secret: str) -> str | None:
    """One normalisation for BOTH sources. Whitespace-only is nothing.

    The env path used to strip and the keyfile path did not, so the same secret produced
    two different keys (`'hunter2\n'` vs `'hunter2'`) depending on which you used. With no
    key escrow that is not an inconvenience, it is the permanent loss of the only copy of a
    family's history — back up via the env var, restore via --passphrase-file, and the
    archive is gone.
    """
    return secret.strip() or None


def resolve_passphrase(options: dict[str, Any]) -> str | None:
    """The passphrase from a keyfile or the environment, or None if neither is set.

    Never an argv flag: a passphrase on the command line lands in shell history and is
    visible to every process on the box.
    """
    keyfile = options.get("passphrase_file")
    if keyfile:
        path = Path(keyfile)
        if not path.is_file():
            raise CommandError(f"passphrase file not found: {path}")
        if path.stat().st_mode & 0o077:
            raise CommandError(
                f"passphrase file {path} is readable by other users; "
                "run `chmod 600` on it before using it as a key."
            )
        try:
            secret = _normalise(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError as exc:
            # `head -c 32 /dev/urandom > keyfile` is the obvious way to make a *keyfile*,
            # and it used to die with a UnicodeDecodeError that printed a byte of the key.
            raise CommandError(
                f"passphrase file {path} is not UTF-8 text. Use a text passphrase "
                "(a diceware phrase is ideal); raw binary key material is not supported."
            ) from exc
        if secret is None:
            raise CommandError(f"passphrase file is empty: {path}")
    else:
        secret = _normalise(os.environ.get(ENV_VAR, ""))
    if secret is not None and len(secret) < MIN_PASSPHRASE_CHARS:
        raise CommandError(
            f"that backup passphrase is too short ({len(secret)} characters; "
            f"{MIN_PASSPHRASE_CHARS} is the minimum). There is no key escrow and no reset: "
            "this passphrase is the only thing standing between a stolen archive and every "
            "photo of your family. Use a diceware phrase of four or more words."
        )
    return secret


class Command(BaseCommand):
    help = "Back up the whole instance (database + media) to a single encrypted archive."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("output", help="Path to write the backup archive to.")
        parser.add_argument(
            "--passphrase-file",
            help=(
                "File holding the encryption passphrase. Defaults to the "
                f"{ENV_VAR} environment variable."
            ),
        )
        parser.add_argument(
            "--no-encrypt",
            action="store_true",
            help="Write a PLAINTEXT archive. Everything in it is readable by anyone.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        output = Path(options["output"])
        passphrase = resolve_passphrase(options)

        if options["no_encrypt"]:
            self.stderr.write(
                self.style.WARNING(
                    "\n*** WARNING: writing an UNENCRYPTED backup ***\n"
                    "This archive contains the entire family database and every photo and\n"
                    "video, in the clear. Anyone who can read the file can read all of it.\n"
                    "Store it only on media you control and can erase.\n"
                )
            )
        elif passphrase is None:
            raise CommandError(
                "refusing to write an unencrypted backup by accident.\n"
                f"Set {ENV_VAR} or pass --passphrase-file, or, if you really want a\n"
                "plaintext archive, pass --no-encrypt explicitly."
            )

        # Written to a sidecar first, then renamed into place. Opening `output` directly
        # TRUNCATED yesterday's good backup before a byte of today's was written, so a full
        # disk or an interrupt destroyed the old archive and left a plausible-looking file
        # that only failed at restore. With no key escrow, "the backup that wasn't" is the
        # whole risk. 0600: the archive is the entire family database and every photo.
        partial = output.with_name(output.name + ".partial")
        try:
            fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as destination:
                if passphrase is None or options["no_encrypt"]:
                    backups.write_backup(destination)
                else:
                    # Staged through an unlinked temp file so the tar is built once and
                    # encrypted as it streams out; neither side is ever fully resident.
                    with tempfile.TemporaryFile() as staged:
                        backups.write_backup(staged)
                        staged.seek(0)
                        backup_crypto.encrypt(staged, destination, passphrase)

            if passphrase is not None and not options["no_encrypt"]:
                # Prove the archive actually decrypts under the passphrase we were given,
                # before it replaces the previous one. A backup nobody can open is worse
                # than no backup, because it is trusted.
                with partial.open("rb") as check, open(os.devnull, "wb") as sink:
                    backup_crypto.decrypt(check, sink, passphrase)

            os.replace(partial, output)
        except (backups.BackupError, backup_crypto.BackupCryptoError, OSError) as exc:
            Path(partial).unlink(missing_ok=True)
            raise CommandError(str(exc)) from exc

        shape = "PLAINTEXT" if options["no_encrypt"] else "encrypted"
        self.stdout.write(
            f"instance backup written ({shape}): {output} ({output.stat().st_size} bytes)"
        )
