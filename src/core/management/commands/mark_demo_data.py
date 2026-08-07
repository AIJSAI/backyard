"""Stamp the demo marker onto fixture data that predates the marker, so the wipe can see it.

The live instance was seeded before `seeded_by` existed, so `wipe_demo_data` correctly finds
nothing there: its demo family carries the same empty marker every real person carries. This
is the step that makes launch day run through the guarded path instead of a shell snippet.

    manage.py mark_demo_data --yard maternal --yard paternal --dry-run
    manage.py mark_demo_data --yard maternal --yard paternal --yes
    manage.py wipe_demo_data --dry-run          # every existing refusal now applies
    manage.py wipe_demo_data --yes

`--undo` takes the marker back off, because an operator who marks the wrong yard needs a way
back that is not another hand-written UPDATE — and needs it before the wipe, not after.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from core import demo_data, demo_marking


class Command(BaseCommand):
    help = "Mark existing yards (and the pods/members contained by them) as fixture data."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--yard",
            action="append",
            default=[],
            dest="yards",
            metavar="SLUG",
            help="A yard slug to mark. Repeat for several. Pods and members are selected by "
            "CONTAINMENT, never by name — see core.demo_marking.",
        )
        parser.add_argument(
            "--marker",
            default=demo_data.SEED_MARKER,
            help=f"The marker to stamp. Default: {demo_data.SEED_MARKER!r}.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be marked, and what was deliberately spared, then stop.",
        )
        parser.add_argument(
            "--undo",
            action="store_true",
            help="Clear this marker from every row that carries it, and stop.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Actually write the marker. Required; there is no implicit write.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        marker = options["marker"]
        try:
            if options["undo"]:
                if not options["yes"]:
                    raise CommandError("--undo also needs --yes.")
                cleared = demo_marking.unmark(marker=marker)
                self.stdout.write(f"Cleared marker {marker!r}:")
                for model, count in sorted(cleared.items()):
                    self.stdout.write(f"  {model:8} {count}")
                self.stdout.write(
                    "\nNothing was deleted. `wipe_demo_data` will now find nothing to do."
                )
                return

            selected, spared = demo_marking.plan(yard_slugs=options["yards"], marker=marker)
        except demo_marking.DemoMarkingError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Would mark as {marker!r}:")
        for model, names in selected.items():
            self.stdout.write(f"  {model} ({len(names)}):")
            for name in names:
                self.stdout.write(f"    {name}")

        if spared:
            # Printed on every run, not only on a dry run. The spared list is how an operator
            # notices that the household they meant to remove reaches somebody real — which
            # is the thing they most need to see and the thing a count would hide.
            self.stdout.write("\nDeliberately NOT marked:")
            for reason in spared:
                self.stdout.write(f"  {reason}")

        if not any(selected.values()):
            self.stdout.write("\nNothing matched. Nothing was changed.")
            return

        if options["dry_run"] or not options["yes"]:
            self.stdout.write(
                "\nNothing was changed. Re-run with --yes to write the marker, then "
                "`wipe_demo_data --dry-run` to see what deleting it would actually touch. "
                "Marking is reversible with --undo --yes; the wipe is not reversible."
            )
            return

        try:
            stamped = demo_marking.apply(yard_slugs=options["yards"], marker=marker)
        except demo_marking.DemoMarkingError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"\nMarked as {marker!r}:")
        for model, count in sorted(stamped.items()):
            self.stdout.write(f"  {model:8} {count}")
        self.stdout.write(
            "\nNothing has been deleted. Run `wipe_demo_data --dry-run` next and READ the "
            "counts — the refusals for real content, stranded members and pod ownership all "
            "apply to what you just marked."
        )
