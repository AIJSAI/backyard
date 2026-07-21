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


def test_transcode_task_is_registered_but_not_periodic() -> None:
    # The first enqueued (non-periodic) task: registered so a video upload can defer it,
    # but not on the periodic registry — it fires per upload, not on a cron (S-402).
    names = {t.name for t in app.tasks.values()}
    assert "transcode_video" in names
    scheduled = {pt.task.name for pt in app.periodic_registry.periodic_tasks.values()}
    assert "transcode_video" not in scheduled


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
