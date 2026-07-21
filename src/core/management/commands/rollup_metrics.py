"""Roll up last week's connection health for every yard (S-705).

A thin wrapper over core.metrics.rollup_week, the same shape as send_digests:
cron-able now, worker-wrapped later, one implementation either way. Covers the
seven days ending today; safe to re-run (idempotent per week).
"""

from __future__ import annotations

import datetime
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.metrics import rollup_week
from core.models import Yard


class Command(BaseCommand):
    help = "Compute weekly connection-health aggregates per yard (S-705). Idempotent."

    def handle(self, *args: Any, **options: Any) -> None:
        week_start = timezone.localdate() - datetime.timedelta(days=7)
        for yard in Yard.objects.all():
            row = rollup_week(yard, week_start)
            self.stdout.write(
                f"{yard.name} {week_start}: wcm={row.wcm}/{row.member_count} "
                f"breadth={row.posting_breadth} responded={row.posts_responded}/"
                f"{row.posts_in_week} catchup={row.catch_up_members} "
                f"opens={row.digest_opens} replies={row.email_replies}"
            )
