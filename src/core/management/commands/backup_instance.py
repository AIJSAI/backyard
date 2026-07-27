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
        secret = path.read_text(encoding="utf-8").strip()
        if not secret:
            raise CommandError(f"passphrase file is empty: {path}")
        return secret
    return os.environ.get(ENV_VAR) or None


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

        try:
            if passphrase is None or options["no_encrypt"]:
                with output.open("wb") as destination:
                    backups.write_backup(destination)
            else:
                # Staged through a temp file so the tar is built once and encrypted as it
                # is streamed out; neither side is ever fully resident.
                with tempfile.TemporaryFile() as staged:
                    backups.write_backup(staged)
                    staged.seek(0)
                    with output.open("wb") as destination:
                        backup_crypto.encrypt(staged, destination, passphrase)
        except (backups.BackupError, backup_crypto.BackupCryptoError) as exc:
            raise CommandError(str(exc)) from exc

        shape = "PLAINTEXT" if options["no_encrypt"] else "encrypted"
        self.stdout.write(
            f"instance backup written ({shape}): {output} ({output.stat().st_size} bytes)"
        )
