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
from django.db import DatabaseError

from core import backup_crypto, backup_passphrase, backups
from core.models import BackupRun

# The two variable NAMES, re-exported because this command's help text and its refusal
# message both name them. The length floor and every other rule stayed in
# backup_passphrase, where the one implementation lives.
ENV_VAR = backup_passphrase.ENV_VAR
FILE_ENV_VAR = backup_passphrase.FILE_ENV_VAR


def resolve_passphrase(options: dict[str, Any]) -> str | None:
    """The passphrase from a keyfile or the environment, or None if neither is set.

    The rules live in `core.backup_passphrase`, which the entrypoint's pre-flight dump and
    the nightly run read too — a passphrase that works for one of the three and not the
    others is the defect this indirection exists to prevent. All this adds is the command
    layer's exception type, so a misconfigured keyfile still prints as a CommandError
    rather than a traceback.
    """
    try:
        return backup_passphrase.resolve(options.get("passphrase_file"))
    except backup_passphrase.BackupPassphraseError as exc:
        raise CommandError(str(exc)) from exc


class Command(BaseCommand):
    help = "Back up the whole instance (database + media) to a single encrypted archive."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("output", help="Path to write the backup archive to.")
        parser.add_argument(
            "--passphrase-file",
            help=(
                f"File holding the encryption passphrase. Defaults to the {ENV_VAR} "
                f"environment variable, and then to the keyfile {FILE_ENV_VAR} names."
            ),
        )
        parser.add_argument(
            "--source",
            choices=[BackupRun.Source.MANUAL, BackupRun.Source.SCHEDULED],
            default=BackupRun.Source.MANUAL,
            help=(
                "Who asked for this backup. The nightly job passes `scheduled`; the health "
                "surface compares scheduled runs only, so a backup taken by hand can never "
                "report a dead nightly job as working. Defaults to `manual`, which is the "
                "safe direction: an unlabelled run never silences that alarm."
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
                f"Set {ENV_VAR} or {FILE_ENV_VAR}, or pass --passphrase-file, or, if you\n"
                "really want a plaintext archive, pass --no-encrypt explicitly."
            )

        # Written to a sidecar first, then renamed into place. Opening `output` directly
        # TRUNCATED yesterday's good backup before a byte of today's was written, so a full
        # disk or an interrupt destroyed the old archive and left a plausible-looking file
        # that only failed at restore. With no key escrow, "the backup that wasn't" is the
        # whole risk. 0600: the archive is the entire family database and every photo.
        partial = output.with_name(output.name + ".partial")
        # Every intermediate copy stages BESIDE the archive rather than in TMPDIR (S-806
        # review): a run makes two more full copies of the instance — the pg_dump plus the
        # media tar, and the single tar built from them — and in the container TMPDIR is the
        # image's writable layer while the archive lands on the mounted volume. The nightly
        # run's headroom guard measures the archive's volume, so copies on the other one are
        # both unmeasured and able to ENOSPC a dump that the guard just said would fit.
        staging = output.parent
        try:
            fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as destination:
                if passphrase is None or options["no_encrypt"]:
                    backups.write_backup(destination, staging_dir=staging)
                else:
                    # Staged through an unlinked temp file so the tar is built once and
                    # encrypted as it streams out; neither side is ever fully resident.
                    with tempfile.TemporaryFile(dir=staging) as staged:
                        backups.write_backup(staged, staging_dir=staging)
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
        byte_count = output.stat().st_size

        # Recorded AFTER the rename and the decrypt check, never before (S-806): a row
        # written on entry would make a crashed or undecryptable backup look successful,
        # and the health email's "last backup" line would then reassure an operator about
        # a backup that does not exist. A failure to record must not fail the backup
        # itself — the archive on disk is the thing that matters.
        # The NAME is recorded, not just the fact: retention deletes files, and it deletes
        # only files a scheduled row says this scheduler wrote. A `scheduled-2026-01-01.bak`
        # an operator copied in by hand matches the pattern and is not ours to remove.
        try:
            BackupRun.objects.create(
                byte_count=byte_count,
                encrypted=not options["no_encrypt"],
                source=options["source"],
                archive_name=output.name,
            )
        except DatabaseError as exc:  # pragma: no cover - the archive is already safe
            self.stderr.write(
                self.style.WARNING(
                    f"backup written, but recording it for the health email failed: {exc}"
                )
            )

        self.stdout.write(f"instance backup written ({shape}): {output} ({byte_count} bytes)")
