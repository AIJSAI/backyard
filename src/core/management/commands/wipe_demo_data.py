"""Remove the demo family, and only the demo family.

Replaces `BACKYARD_DEMO_WIPE=1` in `scripts/demo_seed.py`, which ran
`Pod.objects.all().delete()` — every pod on the instance, and by cascade every post,
comment, photograph, reaction, invite and membership. It was documented in four places as
the step to run immediately before the first real invite.

Refuses by default: `--dry-run` prints the real deletion closure and changes nothing, and
an actual wipe needs `--yes`. See `core.demo_data` for why a marker column rather than a
cleverer query.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from core import demo_data


class Command(BaseCommand):
    help = "Delete objects created by a fixture seed (default marker: 'demo'). Nothing else."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--marker",
            default=demo_data.SEED_MARKER,
            help=(
                "Only delete rows whose `seeded_by` equals this. Anything a real person "
                f"made has an empty marker and can never match. Default: "
                f"{demo_data.SEED_MARKER!r}."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print exactly what would be deleted, per table, and stop.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Actually delete. Without this the command refuses, whatever else is set.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        marker = options["marker"]
        try:
            planned = demo_data.preview(marker)
        except demo_data.DemoDataError as exc:
            raise CommandError(str(exc)) from exc

        if not planned:
            self.stdout.write(
                f"Nothing is marked `seeded_by={marker!r}`. Nothing to delete.\n\n"
                "If this instance was seeded before the marker existed, its fixture rows "
                "are unmarked and this command will not touch them — which is the safe "
                "direction. Mark them deliberately, or remove them by hand after a backup."
            )
            return

        self.stdout.write(f"Rows marked `seeded_by={marker!r}`, and everything they cascade to:")
        for label, count in sorted(planned.items()):
            self.stdout.write(f"  {count:>6}  {label}")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("\nDry run. Nothing was deleted."))
            return

        if not options["yes"]:
            raise CommandError(
                "Refusing to delete without --yes. Run with --dry-run first and read the "
                "counts above; this is not reversible without a backup."
            )

        try:
            removed = demo_data.wipe(marker)
        except demo_data.DemoDataError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("\nDeleted:"))
        for label, count in sorted(removed.items()):
            self.stdout.write(f"  {count:>6}  {label}")
