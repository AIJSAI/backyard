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
                replay = backups.restore_backup(source, force=bool(options["force"]))
        except backups.BackupError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"instance restored from {archive}")
        self._print_security_replay(replay)

    def _print_security_replay(self, replay: dict[str, int]) -> None:
        """Surface the TM-7 / T-OP-G5 forced-security-replay outcome and the human half of
        it (the removals/deletions that postdate the backup, which no code can know)."""
        self.stdout.write(
            self.style.WARNING("\nSECURITY REPLAY (TM-7) — a restore is a security event:")
        )
        self.stdout.write(
            f"  - Rotated {replay['members_rotated']} members' token-signing material and cleared "
            f"{replay['digest_tokens_cleared']} digest confirm/unsubscribe tokens: every no-login "
            "elder link, digest deep-link, reply-by-email address, and digest confirm/unsubscribe "
            "link the backup carried is now DEAD. Re-provision only members who should keep access."
        )
        self.stdout.write(
            f"  - Flushed {replay['sessions_flushed']} sessions and voided "
            f"{replay['invites_voided']} outstanding invites: everyone re-authenticates; "
            "re-issue invites as needed."
        )
        self.stdout.write(
            self.style.WARNING(
                "  - REVIEW THE ROSTER: any member removed AFTER this backup, and any content "
                "deleted after it, has been restored. The restore cannot know what postdates it — "
                "remove those members again and re-delete that content now (T-OP-G5)."
            )
        )
