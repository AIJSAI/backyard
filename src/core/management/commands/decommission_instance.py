"""Shut this instance down safely (S-804, threat rows TM-7 / T-OP-G1 / T-OP-G4).

Self-hosted family software mostly dies of neglect, not attack — the threat model calls
single-maintainer abandonment the likeliest way this instance ends. When it ends on
purpose, it should end in an order that cannot lose the family's history:

    1. EXPORT first, for at least two named members, so the archive leaves before
       anything is revoked. A decommission that revoked first and then failed to export
       would have destroyed access to data nobody had a copy of.
    2. REVOKE second, through the same one implementation a restore uses, so every
       printed QR, bookmarked elder link, digest deep link and reply address stops working
       while the box is still up to serve the 404 (T-OP-G4: a lapsed or handed-over host
       must not answer an old bearer URL).
    3. The operator destroys volumes and provider snapshots LAST, by hand.

Step 3 is deliberately not automated. Destroying a VPS volume or a provider snapshot needs
credentials this process has no business holding, and "the command deleted the snapshots
before I had checked the export" is not a recoverable mistake. The command prints the exact
steps and refuses to pretend it did them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from core import backups, export
from core.models import Member

MIN_RECIPIENTS = 2
CONFIRM_PHRASE = "shut it down"


class Command(BaseCommand):
    help = "Export for named members, revoke every credential, then print the manual steps."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--to",
            action="append",
            default=[],
            metavar="DISPLAY_NAME",
            help=(
                "A member who receives a final export. Repeat; at least two are required "
                "so the family's history never rests with one person."
            ),
        )
        parser.add_argument(
            "--output-dir", required=True, help="Directory to write the final exports into."
        )
        parser.add_argument(
            "--confirm",
            default="",
            help=f'Must be exactly "{CONFIRM_PHRASE}". Nothing happens without it.',
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["confirm"] != CONFIRM_PHRASE:
            raise CommandError(
                "this permanently revokes every elder link, digest link and session on the "
                f'instance.\nRe-run with --confirm "{CONFIRM_PHRASE}" if that is what you want.'
            )

        names = list(dict.fromkeys(options["to"]))  # de-duped, order kept
        if len(names) < MIN_RECIPIENTS:
            raise CommandError(
                f"name at least {MIN_RECIPIENTS} members with --to. A single custodian is the "
                "bus factor this whole procedure exists to remove."
            )

        members = []
        for name in names:
            found = list(Member.objects.filter(display_name=name))
            if not found:
                raise CommandError(f"no member named {name!r}; nothing has been changed.")
            if len(found) > 1:
                raise CommandError(
                    f"{len(found)} members are named {name!r}, so the export would be "
                    "ambiguous; rename one first. Nothing has been changed."
                )
            members.append(found[0])

        out = Path(options["output_dir"])
        out.mkdir(parents=True, exist_ok=True)

        # --- 1. export, before anything is revoked ---
        written: list[Path] = []
        for member in members:
            path = out / f"backyard-export-{member.id}-{_slug(member.display_name)}.zip"
            with path.open("wb") as handle:
                export.write_member_export(member, handle)
            written.append(path)
            self.stdout.write(
                f"exported {member.display_name}: {path} ({path.stat().st_size} bytes)"
            )

        self.stdout.write(
            self.style.WARNING(
                "\nCheck those files open before you continue. Everything below is irreversible."
            )
        )

        # --- 2. revoke, through the same implementation a restore uses ---
        counts = backups.revoke_every_credential()
        self.stdout.write("\nrevoked: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

        # --- 3. the steps this process must not take for you ---
        self.stdout.write(
            self.style.WARNING(
                "\nSTILL TO DO, BY HAND — this command cannot and will not do these:\n"
                "  1. Deliver the exports above to those people. Confirm they can open them.\n"
                "  2. Take a final encrypted instance backup and copy it OFF this box.\n"
                "  3. Destroy the provider snapshots and the volume (needs provider creds).\n"
                "  4. Leave the domain registered until every printed QR is out of circulation,\n"
                "     or a squatter inherits every bookmark (T-OP-G4).\n"
                "  5. Tell the family, in words, that it is going away and where their copy is.\n"
                "\nFull procedure: docs/runbooks/shutdown.md"
            )
        )


def _slug(name: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-") or "member"
