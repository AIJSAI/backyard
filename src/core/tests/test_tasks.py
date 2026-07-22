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
