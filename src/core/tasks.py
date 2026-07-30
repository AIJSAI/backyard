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
import logging

from django.core.management import call_command
from django.utils import timezone
from procrastinate.contrib.django import app

from . import digest_send, staged_uploads
from .metrics import rollup_week
from .models import Yard

logger = logging.getLogger(__name__)


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


@app.periodic(cron="20 7 * * 1")  # Mondays 07:20, after the metrics rollup
@app.task(name="send_health_email")
def send_health_email_task(timestamp: int) -> None:
    """The weekly admin health email (S-806, T-MON-1): a dead backup cron or a filling
    disk must not go unnoticed for months."""
    from . import health_email

    result = health_email.send_health_emails()
    logger.info(
        "health email sent=%s skipped_no_confirmed_address=%s alarming=%s",
        result.sent,
        result.skipped_no_confirmed_address,
        result.alarming,
    )
    if result.sent == 0:
        # The one failure mode that silences the thing whose job is to break silence.
        logger.warning(
            "NOBODY received the health email: no instance admin has a digest "
            "subscription that is both ENABLED and CONFIRMED. An admin who confirmed an "
            "address and then turned the digest off is also excluded — the send path "
            "filters on enabled=True AND confirmed_at, so 'they confirmed it' is not "
            "enough. See docs/runbooks/handover.md"
        )


@app.periodic(cron="40 6 * * 1")  # Mondays 06:40, before the health email reads it
@app.task(name="refresh_domain_status")
def refresh_domain_status_task(timestamp: int) -> None:
    """Refresh the cached domain expiry (S-806, T-OP-G4). On the WORKER, never the edge
    (S-725): a hanging registry must not hold a web process, and a failure degrades one
    field rather than the whole email."""
    from . import domain_expiry

    status = domain_expiry.refresh()
    logger.info(
        "domain status refreshed domain=%s expires_at=%s error=%r",
        status.domain,
        status.expires_at,
        status.error,
    )


@app.periodic(cron="15 4 * * *")  # daily 04:15
@app.task(name="clear_sessions")
def clear_sessions_task(timestamp: int) -> None:
    """Purge expired db-session rows (threat model TS-DJ-1): db sessions never
    self-purge, so removed-member rows would otherwise accumulate."""
    call_command("clearsessions")


@app.periodic(cron="45 * * * *")  # HOURLY: a daily sweep made a 6h TTL mean ~30h
@app.task(name="sweep_staged_uploads")
def sweep_staged_uploads_task(timestamp: int) -> None:
    """Delete uploads abandoned at the confirm-on-widen step (TM-3).

    Photos are staged server-side so a wide post cannot lose them across the confirmation
    hop. A member who then closes the tab leaves family photographs on disk, and the
    session purge above does not touch files — so this walks the staging directory by
    mtime and collects anything past the TTL, including orphans whose session is long
    gone.

    Hourly, not daily: with a once-a-day cron a file staged just after the sweep lived
    ~30 hours against a TTL that claims 6, so the documented guarantee was not the real
    retention. The sweep is one iterdir over one directory."""
    removed = staged_uploads.sweep()
    if removed:
        logger.info("swept %s abandoned staged upload(s)", removed)


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


# The SSRF-sensitive link-preview fetch, moved off the web request path (S-725, TS-CO-4).
# The edge-facing web process (on the `edge` network) no longer makes the outbound fetch; it
# runs here on the worker, which is on neither `edge` nor `web-db` — so a hypothetical bug in
# the (already IP-pinning, non-global-rejecting) fetcher cannot pivot toward the reverse proxy.
# Carries only the post id and re-resolves live (TS-DJ-11); a deleted post no-ops.
@app.task(name="attach_link_preview", queue="preview")
def attach_link_preview(post_id: int) -> None:
    """Fetch and attach the best-effort link-preview card for a just-composed post (S-301,
    S-725). Best-effort: a URL with no fetchable preview still stores the cleaned bare link
    (link_preview.attach_to_post's graceful fallback); no URL means no row."""
    from . import link_preview
    from .models import Post

    post = Post.objects.filter(pk=post_id, deleted_at__isnull=True).first()
    if post is None:
        return  # deleted, or gone before the worker picked it up
    link_preview.attach_to_post(post)


@app.task(name="notify_reply")
def notify_reply_task(comment_id: int) -> None:
    """Send the opt-in reply nudge for one comment (S-305), off the request path.

    Carries only the id and re-resolves live (TS-DJ-11): the preference, the confirmed
    and still-enabled subscription, and whether the replier is visible to the author are
    all re-read now, so a comment deleted or a member removed between the reply and this
    tick sends nothing.
    """
    from . import notifications
    from .models import Comment

    comment = (
        Comment.objects.filter(pk=comment_id, deleted_at__isnull=True)
        .select_related("author", "post", "post__author")
        .first()
    )
    if comment is None:
        return  # deleted before the worker picked it up
    notifications.notify_reply(comment)
