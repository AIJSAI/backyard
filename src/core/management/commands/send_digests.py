"""Send every due digest, now. The cron-able driver until the worker lands.

This command is a thin wrapper over core.digest_send.send_due_digests — the
one send path. When the Procrastinate worker container arrives (ADR-002), its
periodic task wraps the SAME function; neither driver ever grows send logic of
its own, so command-now and worker-later cannot drift apart.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.digest_send import send_due_digests


class Command(BaseCommand):
    help = "Send every digest due now (S-501). Safe to re-run: sends are idempotent per window."

    def handle(self, *args: Any, **options: Any) -> None:
        report = send_due_digests(timezone.now())
        self.stdout.write(
            f"digests: sent={report.sent} failed={report.failed} skipped={report.skipped}"
        )
        for line in report.details:
            self.stdout.write(f"  {line}")
