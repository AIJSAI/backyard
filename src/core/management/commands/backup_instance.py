"""Back up the whole instance to one archive (S-704 instance half, S-802).

One command captures the database and the media tree. Run in the migrator's
environment (POSTGRES_MIGRATOR_PASSWORD set); the runbook documents the wrapper
that does. Encrypt or ship the resulting file with your own tools.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from core import backups


class Command(BaseCommand):
    help = "Back up the whole instance (database + media) to a single archive."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("output", help="Path to write the backup archive to.")

    def handle(self, *args: Any, **options: Any) -> None:
        output = Path(options["output"])
        try:
            with output.open("wb") as destination:
                backups.write_backup(destination)
        except backups.BackupError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"instance backup written: {output} ({output.stat().st_size} bytes)")
