"""Connection-health aggregates (S-705): counts, never surveillance.

Properties under test: the rollup counts one seeded week correctly per yard;
a bridging pod counts in both yards while each side's numbers never absorb the
other's activity; the ONLY per-person datum is the yes/no presence, pinned by
a structural anti-surveillance test over the exact field sets (any new
surveillance-shaped column breaks it); the digest-open proxy is the one-time
token stamp; re-runs are idempotent; and the panel is instance-admin only.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import metrics
from core.models import (
    Comment,
    Member,
    MemberWeekPresence,
    Pod,
    PodMembership,
    PodWeekMetrics,
    Post,
    Reaction,
    Yard,
    YardWeekMetrics,
)

pytestmark = pytest.mark.django_db
User = get_user_model()
_TEST_PW = "a-Strong-passphrase-9"


def _member_with_user(pod: Pod, name: str, role: str = Member.MEMBER) -> Member:
    user = User.objects.create_user(username=name.lower(), password=_TEST_PW)
    member = Member.objects.create(display_name=name, user=user, role=role)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _client_for(member: Member) -> Client:
    assert member.user is not None
    c = Client()
    c.force_login(member.user, backend="django.contrib.auth.backends.ModelBackend")
    return c


@dataclass
class World:
    maternal: Yard
    paternal: Yard
    bridge_pod: Pod
    m_pod: Pod
    p_pod: Pod
    bridge: Member
    poster: Member
    lurker: Member
    quiet: Member
    far: Member
    week_start: datetime.date


@pytest.fixture
def world() -> World:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    bridge_pod = Pod.objects.create(name="Bridge household")
    bridge_pod.yards.set([maternal, paternal])
    m_pod = Pod.objects.create(name="Maternal cousins")
    m_pod.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal cousins")
    p_pod.yards.set([paternal])
    week_start = timezone.localdate() - datetime.timedelta(days=6)
    return World(
        maternal=maternal,
        paternal=paternal,
        bridge_pod=bridge_pod,
        m_pod=m_pod,
        p_pod=p_pod,
        bridge=_member_with_user(bridge_pod, "Bridge"),
        poster=_member_with_user(m_pod, "Poster"),
        lurker=_member_with_user(m_pod, "Lurker"),
        quiet=_member_with_user(m_pod, "Quiet"),
        far=_member_with_user(p_pod, "Far"),
        week_start=week_start,
    )


def test_rollup_counts_a_seeded_week(world: World) -> None:
    post = Post.objects.create(author=world.poster, pod=world.m_pod, body="hello")
    post.audience_yards.set([world.maternal])
    Reaction.objects.create(member=world.bridge, post=post, kind=Reaction.HEART)
    Member.objects.filter(pk=world.lurker.pk).update(feed_last_seen_at=timezone.now())

    row = metrics.rollup_week(world.maternal, world.week_start)

    assert row.member_count == 4  # bridge, poster, lurker, quiet
    assert row.wcm == 3  # poster posted, bridge reacted, lurker visited; quiet is quiet
    assert row.posting_breadth == 1 and row.posts_in_week == 1
    assert row.posts_responded == 1  # the reaction closed the loop
    assert row.catch_up_members == 1
    presence = {
        p.member.display_name: p.present
        for p in MemberWeekPresence.objects.filter(week_start=world.week_start)
    }
    assert presence == {"Bridge": True, "Poster": True, "Lurker": True, "Quiet": False}


def test_bridging_pod_counts_both_sides_without_fusion(world: World) -> None:
    """The bridge pod's post counts in BOTH yards' breadth (the pod spans), but
    the far side's own activity never inflates the maternal numbers."""
    Post.objects.create(author=world.bridge, pod=world.bridge_pod, body="household note")
    far_post = Post.objects.create(author=world.far, pod=world.p_pod, body="far news")
    far_post.audience_yards.set([world.paternal])

    maternal_row = metrics.rollup_week(world.maternal, world.week_start)
    paternal_row = metrics.rollup_week(world.paternal, world.week_start)

    assert maternal_row.posting_breadth == 1  # the bridge pod, in the maternal count
    assert paternal_row.posting_breadth == 2  # the bridge pod AND the far pod
    assert maternal_row.posts_in_week == 1  # far_post never counts maternally
    assert maternal_row.wcm == 1  # the far poster is not a maternal member
    bridge_pod_rows = PodWeekMetrics.objects.filter(pod=world.bridge_pod)
    assert bridge_pod_rows.count() == 1 and bridge_pod_rows.get().post_count == 1


def test_rollup_is_idempotent(world: World) -> None:
    Post.objects.create(author=world.poster, pod=world.m_pod, body="once")
    metrics.rollup_week(world.maternal, world.week_start)
    metrics.rollup_week(world.maternal, world.week_start)
    assert YardWeekMetrics.objects.filter(yard=world.maternal).count() == 1
    assert MemberWeekPresence.objects.filter(member=world.poster).count() == 1


def test_digest_open_proxy_is_the_one_time_stamp(world: World) -> None:
    import time

    from core import digest_links
    from core.models import DigestIssue, DigestToken

    now = timezone.now()
    issue = DigestIssue.objects.create(
        member=world.lurker,
        yard=world.maternal,
        window_start=now - datetime.timedelta(days=7),
        window_end=now,
    )
    raw = digest_links.mint(issue)
    # A fetch inside the scanner grace never stamps (#40 review MEDIUM-3):
    # delivery-time link scanners must not count as an elder opening the digest.
    Client().get(reverse("digest_web", args=[raw]))
    token = DigestToken.objects.get()
    assert token.first_used_at is None  # the scanner-shaped fetch was ignored
    DigestToken.objects.update(created_at=now - datetime.timedelta(minutes=11))
    Client().get(reverse("digest_web", args=[raw]))
    time.sleep(0)  # ordering only; the stamp is synchronous
    token.refresh_from_db()
    first = token.first_used_at
    assert first is not None
    Client().get(reverse("digest_web", args=[raw]))  # a second open never re-stamps
    token.refresh_from_db()
    assert token.first_used_at == first

    row = metrics.rollup_week(world.maternal, world.week_start)
    assert row.digest_opens == 1
    assert MemberWeekPresence.objects.get(member=world.lurker).present is True


def test_email_reply_counts_as_presence_and_reply(world: World) -> None:
    post = Post.objects.create(author=world.poster, pod=world.m_pod, body="hi")
    Comment.objects.create(author=world.quiet, post=post, body="from mail", via_email=True)
    row = metrics.rollup_week(world.maternal, world.week_start)
    assert row.email_replies == 1
    assert MemberWeekPresence.objects.get(member=world.quiet).present is True


def test_anti_surveillance_field_sets_are_pinned(world: World) -> None:
    """The structural guarantee (S-705 acceptance): the exact field sets of the
    three metrics models. A time-on-site, session, streak, or per-person
    activity column CANNOT arrive without breaking this test — the
    NotificationPreference no-firehose pattern, extended."""
    yard_fields = {f.name for f in YardWeekMetrics._meta.get_fields() if not f.auto_created}
    assert yard_fields == {
        "yard",
        "week_start",
        "member_count",
        "wcm",
        "posting_breadth",
        "posts_in_week",
        "posts_responded",
        "catch_up_members",
        "digest_opens",
        "email_replies",
        "created_at",
    }
    pod_fields = {f.name for f in PodWeekMetrics._meta.get_fields() if not f.auto_created}
    assert pod_fields == {"pod", "week_start", "post_count", "created_at"}
    presence_fields = {f.name for f in MemberWeekPresence._meta.get_fields() if not f.auto_created}
    assert presence_fields == {"member", "week_start", "present", "created_at"}
    banned = ("session", "duration", "time_on", "streak", "seconds", "minutes")
    for name in yard_fields | pod_fields | presence_fields:
        assert not any(bad in name for bad in banned), name


def test_metrics_panel_is_instance_admin_only(world: World) -> None:
    metrics.rollup_week(world.maternal, world.week_start)
    yard_admin = _member_with_user(world.m_pod, "Yadmin", role=Member.YARD_ADMIN)
    instance_admin = _member_with_user(world.m_pod, "Iadmin", role=Member.INSTANCE_ADMIN)
    assert _client_for(world.poster).get(reverse("member_metrics")).status_code == 403
    assert _client_for(yard_admin).get(reverse("member_metrics")).status_code == 403
    body = _client_for(instance_admin).get(reverse("member_metrics")).content.decode()
    assert "Connection health" in body and "Maternal" in body


# --- folds from the #40 security review ---


def test_presence_is_rollup_order_independent(world: World) -> None:
    """#40 review HIGH-1, the reviewer's exact probe: a bridge member who posted
    only on one side must read present no matter which yard rolls up last (the
    command rolls yards alphabetically, so Paternal used to overwrite)."""
    m_only_pod = Pod.objects.create(name="Bridge maternal side pod")
    m_only_pod.yards.set([world.maternal])
    PodMembership.objects.create(member=world.bridge, pod=m_only_pod)
    Post.objects.create(author=world.bridge, pod=m_only_pod, body="maternal-side only")

    metrics.rollup_week(world.maternal, world.week_start)
    metrics.rollup_week(world.paternal, world.week_start)  # the overwriting order
    assert MemberWeekPresence.objects.get(member=world.bridge).present is True


def test_other_yard_addressed_posts_never_absorb(world: World) -> None:
    """#40 review MEDIUM-1: a bridge-pod post addressed exclusively to the
    paternal yard is paternal activity; the maternal counts never absorb it."""
    far_only = Post.objects.create(author=world.bridge, pod=world.bridge_pod, body="far only")
    far_only.audience_yards.set([world.paternal])
    maternal_row = metrics.rollup_week(world.maternal, world.week_start)
    paternal_row = metrics.rollup_week(world.paternal, world.week_start)
    assert maternal_row.posts_in_week == 0 and maternal_row.posting_breadth == 0
    assert paternal_row.posts_in_week == 1
    # Presence stays global: the bridge member touched the platform.
    assert MemberWeekPresence.objects.get(member=world.bridge).present is True


def test_digest_opens_and_email_replies_are_yard_scoped(world: World) -> None:
    """#40 review MEDIUM-2: opening a paternal digest is one paternal open,
    never one in each yard; an email reply to a paternal-only post is paternal."""
    from core import digest_links
    from core.models import DigestIssue, DigestToken

    now = timezone.now()
    issue = DigestIssue.objects.create(
        member=world.bridge,
        yard=world.paternal,
        window_start=now - datetime.timedelta(days=7),
        window_end=now,
    )
    digest_links.mint(issue)
    DigestToken.objects.update(created_at=now - datetime.timedelta(minutes=11), first_used_at=now)
    far_post = Post.objects.create(author=world.far, pod=world.p_pod, body="far")
    far_post.audience_yards.set([world.paternal])
    Comment.objects.create(author=world.bridge, post=far_post, body="from mail", via_email=True)

    maternal_row = metrics.rollup_week(world.maternal, world.week_start)
    paternal_row = metrics.rollup_week(world.paternal, world.week_start)
    assert maternal_row.digest_opens == 0 and paternal_row.digest_opens == 1
    assert maternal_row.email_replies == 0 and paternal_row.email_replies == 1


def test_self_response_never_counts_as_reciprocity(world: World) -> None:
    """#40 review LOW-1: reciprocity is loop closure by OTHERS (R2)."""
    post = Post.objects.create(author=world.poster, pod=world.m_pod, body="anyone?")
    Comment.objects.create(author=world.poster, post=post, body="bump")
    Reaction.objects.create(member=world.poster, post=post, kind=Reaction.HEART)
    row = metrics.rollup_week(world.maternal, world.week_start)
    assert row.posts_responded == 0
    Reaction.objects.create(member=world.lurker, post=post, kind=Reaction.HEART)
    assert metrics.rollup_week(world.maternal, world.week_start).posts_responded == 1


def test_app_wide_anti_surveillance_sweep(world: World) -> None:
    """#40 review LOW-2: the field-set pin covers three models; this closes the
    fourth-model residual — no model in the app grows a surveillance-shaped
    field name, and the metric-shaped model set is exactly the pinned three."""
    from django.apps import apps

    banned = ("session", "duration", "time_on", "streak", "seconds_on", "minutes_on")
    metric_shaped = set()
    for model in apps.get_app_config("core").get_models():
        for field in model._meta.get_fields():
            name = getattr(field, "name", "")
            assert not any(bad in name for bad in banned), f"{model.__name__}.{name}"
        if any(hint in model.__name__ for hint in ("Week", "Metric", "Presence")):
            metric_shaped.add(model.__name__)
    assert metric_shaped == {"YardWeekMetrics", "PodWeekMetrics", "MemberWeekPresence"}


def test_command_heals_the_previous_week(world: World) -> None:
    """#40 review LOW-3: each run re-rolls the week before, so a late-week
    post's reciprocity heals once its 7-day response window has really run."""
    from django.core.management import call_command

    call_command("rollup_metrics")
    weeks = set(
        YardWeekMetrics.objects.filter(yard=world.maternal).values_list("week_start", flat=True)
    )
    assert len(weeks) == 2  # the trailing week and the one before it
