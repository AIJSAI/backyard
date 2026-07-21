"""Procrastinate periodic tasks (ADR-002): the worker's scheduled work.

These are the same functions the management commands wrap, deferred to the
Postgres-native worker instead of cron. The no-second-path rule (scoping.py's
shape) holds one layer down: a task is a periodic TRIGGER that carries no
audience and no identifiers at all, and re-resolves everything live through the
audience guard at run time (TS-DJ-11). A task against stale state re-reads state
now, so a member revoked or a post deleted since the last tick never ships.

The worker is the fourth container (ADR-002); until it runs, the identical
management commands are the cron-able path, so nothing here is a second
implementation, only a second driver over one implementation.
"""

from __future__ import annotations

import datetime

from django.core.management import call_command
from django.utils import timezone
from procrastinate.contrib.django import app

from . import digest_send
from .metrics import rollup_week
from .models import Yard


@app.periodic(cron="0 * * * *")  # hourly; the per-member cadence clock decides who is due
@app.task(name="send_due_digests")
def send_due_digests_task(timestamp: int) -> None:
    """Send every digest due now. Re-resolves recipients and content live
    (TS-DJ-11): the task itself carries nothing but the tick timestamp."""
    digest_send.send_due_digests(timezone.now())


@app.periodic(cron="30 6 * * 1")  # Mondays 06:30; the rollup covers the prior week
@app.task(name="rollup_metrics")
def rollup_metrics_task(timestamp: int) -> None:
    """Roll up last week's connection health per yard (S-705), plus the week
    before, so a late-week post's reciprocity heals (the command's LOW-3 fold)."""
    week_start = timezone.localdate() - datetime.timedelta(days=7)
    for yard in Yard.objects.all():
        rollup_week(yard, week_start - datetime.timedelta(days=7))
        rollup_week(yard, week_start)


@app.periodic(cron="15 4 * * *")  # daily 04:15
@app.task(name="clear_sessions")
def clear_sessions_task(timestamp: int) -> None:
    """Purge expired db-session rows (threat model TS-DJ-1): db sessions never
    self-purge, so removed-member rows would otherwise accumulate."""
    call_command("clearsessions")


# The first enqueued (non-periodic) task: a video upload defers one of these with its
# asset id. It carries only the id and re-resolves the asset live at run time (TS-DJ-11
# shape); a deleted or already-processed asset no-ops. It runs on the `transcode` queue,
# and the worker runs at concurrency 1 (docker-compose), so the expensive RE-ENCODE never
# runs in parallel (TS-PP-2). (The upfront probe and metadata strip run web-synchronously
# on upload and are bounded per call by the timeout, rlimits, and the web mem/pids limits,
# not by this concurrency-1.) The hardened ffmpeg lives in core/transcoding.
@app.task(name="transcode_video", queue="transcode")
def transcode_video(asset_id: int) -> None:
    """Transcode one pending video asset to its served rendition + poster (S-402)."""
    from . import transcoding

    transcoding.transcode_asset(asset_id)
