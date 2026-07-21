"""Restore the whole instance from a backup archive (S-704, S-802).

DESTRUCTIVE: clean-restores the database and replaces the media tree. Refuses a
database that still holds members unless --force is given, so it is safe to
point at a fresh box or a drill scratch DB and hard to fire by accident.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from core import backups


class Command(BaseCommand):
    help = "Restore the whole instance (database + media) from a backup archive."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("archive", help="Path to the backup archive to restore.")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Restore even over a database that still has members (destructive).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        archive = Path(options["archive"])
        if not archive.exists():
            raise CommandError(f"backup archive not found: {archive}")
        try:
            with archive.open("rb") as source:
                backups.restore_backup(source, force=bool(options["force"]))
        except backups.BackupError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"instance restored from {archive}")
