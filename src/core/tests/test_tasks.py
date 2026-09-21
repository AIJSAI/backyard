"""The Procrastinate worker's periodic tasks (ADR-002).

The tasks are thin triggers over already-tested functions, so these tests hold
the wiring, not the logic: the tasks are registered with the app, each carries a
cron schedule, and each carries NO audience or identifier payload (TS-DJ-11) so
it can only re-resolve live. Running a task drives the same effect as its
management-command twin, proving the no-second-path rule one layer down.
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone
from procrastinate.contrib.django import app

from core import tasks
from core.models import (
    DigestSubscription,
    Member,
    MemberWeekPresence,
    Pod,
    PodMembership,
    Post,
    Yard,
)

pytestmark = pytest.mark.django_db


def test_the_tasks_are_registered_with_cron_schedules() -> None:
    names = {t.name for t in app.tasks.values()}
    assert {"send_due_digests", "rollup_metrics", "clear_sessions"} <= names
    # Each is periodic: the app holds a cron schedule for it.
    scheduled = {pt.task.name for pt in app.periodic_registry.periodic_tasks.values()}
    assert {"send_due_digests", "rollup_metrics", "clear_sessions"} <= scheduled


def test_the_backup_and_certificate_checks_are_on_the_clock() -> None:
    """Registration is the whole feature here (S-806, T-MON-1).

    `backup_instance` shipped with nothing scheduling it, so the instance had a documented
    backup and no backups. A task that exists but is not on the periodic registry is the
    same defect with more code, and it is invisible: nothing else in the suite would fail.
    """
    scheduled = {pt.task.name for pt in app.periodic_registry.periodic_tasks.values()}
    assert {"scheduled_backup", "refresh_certificate_status"} <= scheduled


def test_the_scheduled_backup_task_carries_nothing_but_the_tick() -> None:
    """TS-DJ-11's shape, and here it also means the task cannot be told WHERE to write."""
    import inspect

    assert list(inspect.signature(tasks.scheduled_backup_task.func).parameters) == ["timestamp"]


def test_the_scheduled_backup_task_reraises_so_the_job_is_marked_failed(
    monkeypatch: object,
) -> None:
    """A swallowed failure is the T-MON-1 condition wearing a feature's costume: the queue
    would record a clean run for a night that produced no archive."""
    from core import scheduled_backup

    def boom() -> None:
        raise scheduled_backup.ScheduledBackupFailed("no passphrase")

    monkeypatch.setattr(scheduled_backup, "run", boom)  # type: ignore[attr-defined]
    with pytest.raises(scheduled_backup.ScheduledBackupFailed):
        tasks.scheduled_backup_task.func(int(timezone.now().timestamp()))


def test_the_certificate_refresh_does_nothing_on_a_plain_http_instance(
    monkeypatch: object, settings: object
) -> None:
    """No handshake against a localhost that has no TLS listener: the local repro is plain
    HTTP, and a nightly connection error is how a real alarm gets learned as noise."""
    from core import cert_expiry

    settings.BASE_URL = "http://localhost:8000"  # type: ignore[attr-defined]
    calls: list[str] = []
    monkeypatch.setattr(cert_expiry, "refresh", lambda: calls.append("refreshed"))  # type: ignore[attr-defined]

    tasks.refresh_certificate_status_task.func(int(timezone.now().timestamp()))

    assert calls == []


def test_finished_jobs_are_pruned_on_a_daily_schedule() -> None:
    """TS-PG-7, which is rated High and committed to scheduling this "from the wave it
    installs" while nothing did. Push raises the rate it matters at: one post is one job
    row, one reply is two, and `procrastinate_jobs` plus `procrastinate_events` grow
    without bound until the disk on a family box fills."""
    scheduled = {pt.task.name: pt for pt in app.periodic_registry.periodic_tasks.values()}
    assert "prune_finished_jobs" in scheduled
    assert scheduled["prune_finished_jobs"].cron == "50 4 * * *"
    # Both windows named, and the failed one longer: a succeeded job is a receipt nobody
    # reads, a failed one is the only record of what went wrong.
    assert tasks.SUCCEEDED_JOB_RETENTION_HOURS == 24 * 7
    assert tasks.FAILED_JOB_RETENTION_HOURS == 24 * 30
    assert tasks.FAILED_JOB_RETENTION_HOURS > tasks.SUCCEEDED_JOB_RETENTION_HOURS


def test_the_prune_calls_procrastinates_own_deletion_with_both_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It must not grow a DELETE of its own: which statuses count as finished, and which
    timestamp age is measured from, stay the library's business (it reads the newest
    `procrastinate_events` row, not `scheduled_at`)."""
    calls: list[dict[str, object]] = []

    async def record(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(app.job_manager, "delete_old_jobs", record)
    tasks.prune_finished_jobs_task.func(timestamp=0)

    assert calls == [
        {
            "nb_hours": tasks.FAILED_JOB_RETENTION_HOURS,
            "include_failed": True,
            "include_cancelled": True,
            "include_aborted": True,
        },
        {"nb_hours": tasks.SUCCEEDED_JOB_RETENTION_HOURS},
    ]


@pytest.mark.django_db(transaction=True)
def test_the_prune_really_removes_a_finished_job_row() -> None:
    """Against a real Postgres, through Procrastinate's own SQL. The rows are inserted
    with raw SQL because Procrastinate's Django models are deliberately read-only, and an
    event row is inserted with them because the deletion measures age from the newest
    event, not from the job."""
    from django.db import connection

    with connection.cursor() as cursor:
        for status, age_hours in (("succeeded", 24 * 8), ("succeeded", 1), ("failed", 24 * 8)):
            cursor.execute(
                "INSERT INTO procrastinate_jobs (queue_name, task_name, priority, args, status)"
                " VALUES ('push', 'push_new_post', 0, '{}', %s::procrastinate_job_status)"
                " RETURNING id",
                [status],
            )
            job_id = cursor.fetchone()[0]
            # The event TYPE is the job's own final status: the enum has succeeded and
            # failed, and no "finished". The deletion reads the newest event's `at`.
            cursor.execute(
                "INSERT INTO procrastinate_events (job_id, type, at)"
                " VALUES (%s, %s::procrastinate_job_event_type,"
                " NOW() - (%s || ' HOUR')::INTERVAL)",
                [job_id, status, age_hours],
            )
        cursor.execute("SELECT count(*) FROM procrastinate_jobs")
        assert cursor.fetchone()[0] == 3

    tasks.prune_finished_jobs_task.func(timestamp=0)

    with connection.cursor() as cursor:
        cursor.execute("SELECT status::text FROM procrastinate_jobs ORDER BY id")
        left = [row[0] for row in cursor.fetchall()]
        cursor.execute("DELETE FROM procrastinate_jobs")
    # The eight-day-old SUCCEEDED row is gone; the recent one and the failed one stay,
    # because a failure is kept thirty days.
    assert left == ["succeeded", "failed"]


def test_transcode_task_is_registered_but_not_periodic() -> None:
    # The first enqueued (non-periodic) task: registered so a video upload can defer it,
    # but not on the periodic registry — it fires per upload, not on a cron (S-402).
    names = {t.name for t in app.tasks.values()}
    assert "transcode_video" in names
    scheduled = {pt.task.name for pt in app.periodic_registry.periodic_tasks.values()}
    assert "transcode_video" not in scheduled


def test_attach_link_preview_task_is_registered_but_not_periodic() -> None:
    # S-725: the SSRF-sensitive link fetch is deferred per compose, off the web process.
    names = {t.name for t in app.tasks.values()}
    assert "attach_link_preview" in names
    scheduled = {pt.task.name for pt in app.periodic_registry.periodic_tasks.values()}
    assert "attach_link_preview" not in scheduled


def _post_with_a_link(body: str = "see http://example.com/x", **kwargs: object) -> Post:
    yard = Yard.objects.create(name="Y", slug="y")
    pod = Pod.objects.create(name="P")
    pod.yards.set([yard])
    author = Member.objects.create(display_name="A")
    PodMembership.objects.create(member=author, pod=pod)
    return Post.objects.create(author=author, pod=pod, body=body, **kwargs)


def test_attach_link_preview_task_re_resolves_the_post_and_delegates(monkeypatch: object) -> None:
    """S-725/TS-DJ-11: the task carries only the id, re-resolves the post live, and delegates
    the fetch to link_preview.attach_to_post (whose SSRF-hardened logic is tested there)."""
    from core import link_preview

    calls: list[int] = []
    monkeypatch.setattr(link_preview, "attach_to_post", lambda post: calls.append(post.id))  # type: ignore[attr-defined]
    post = _post_with_a_link()
    tasks.attach_link_preview.func(post_id=post.id)
    assert calls == [post.id]


def test_attach_link_preview_task_no_ops_on_a_deleted_post(monkeypatch: object) -> None:
    from core import link_preview

    calls: list[int] = []
    monkeypatch.setattr(link_preview, "attach_to_post", lambda post: calls.append(post.id))  # type: ignore[attr-defined]
    post = _post_with_a_link(deleted_at=timezone.now())
    tasks.attach_link_preview.func(post_id=post.id)
    assert calls == []  # a post deleted before the worker ran gets no preview


def test_attach_link_preview_task_is_idempotent_on_redelivery(monkeypatch: object) -> None:
    """S-725 review: the task runs on an at-least-once queue, so a re-delivered job (a worker
    killed mid-run) must not re-fetch or hit the LinkPreview OneToOne with a second create —
    the real attach_to_post no-ops when the post already has a card. Only the network fetch is
    mocked (to None → a bare-link card, no external I/O)."""
    from core import link_preview
    from core.models import LinkPreview

    fetches: list[str] = []

    def _record_fetch(url: str, deadline: float | None = None) -> None:
        fetches.append(url)  # record the outbound fetch; return None → a bare-link card

    monkeypatch.setattr(link_preview, "fetch_preview", _record_fetch)  # type: ignore[attr-defined]
    post = _post_with_a_link(body="see https://example.com/x")
    tasks.attach_link_preview.func(post_id=post.id)  # first delivery: creates the bare card
    tasks.attach_link_preview.func(post_id=post.id)  # re-delivery: must no-op, not raise
    assert LinkPreview.objects.filter(post=post).count() == 1  # no duplicate, no IntegrityError
    assert len(fetches) == 1  # the redundant re-fetch is skipped on re-delivery


def test_send_task_carries_no_audience_and_re_resolves_live() -> None:
    """TS-DJ-11: the task signature is a bare timestamp — no member, no post, no
    audience — so it CANNOT trust a payload; it re-resolves through the guard."""
    import inspect

    params = list(inspect.signature(tasks.send_due_digests_task.func).parameters)
    assert params == ["timestamp"]  # nothing but the tick


def test_send_task_sends_due_digests(monkeypatch: object) -> None:
    from django.core import mail

    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Cousins")
    pod.yards.set([yard])
    user_member = Member.objects.create(display_name="Nana")
    PodMembership.objects.create(member=user_member, pod=pod)
    Post.objects.create(author=user_member, pod=pod, body="hello")
    DigestSubscription.objects.create(
        member=user_member,
        address="nana@example.com",
        enabled=True,
        confirmed_at=timezone.now() - datetime.timedelta(days=8),
    )
    mail.outbox.clear()

    tasks.send_due_digests_task.func(int(timezone.now().timestamp()))
    assert len(mail.outbox) == 1  # the due digest went, through the same send path


def test_rollup_task_rolls_up_last_week() -> None:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Cousins")
    pod.yards.set([yard])
    member = Member.objects.create(display_name="Nana")
    PodMembership.objects.create(member=member, pod=pod)
    last_week = timezone.now() - datetime.timedelta(days=5)
    post = Post.objects.create(author=member, pod=pod, body="a post")
    Post.objects.filter(pk=post.pk).update(created_at=last_week)

    tasks.rollup_metrics_task.func(int(timezone.now().timestamp()))
    assert MemberWeekPresence.objects.filter(member=member).exists()
