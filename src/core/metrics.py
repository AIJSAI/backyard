"""Weekly connection health (S-705): counts per pod and yard, nothing else.

rollup_week computes one yard's week from rows that already exist (posts,
comments, reactions, feed visits, digest-token first-use) and stores COUNTS.
It is a periodic job that never becomes a second authorization path
(docs/wave-plan.md rule, verbatim): no content object or reference is stored,
no audience is resolved, and nothing here can leak what it never holds. The
only per-person datum anywhere is MemberWeekPresence.present, a yes/no the
measured family is told about in the docs.

Honest undercounts, by design (docs/metrics.md): the digest-open proxy is
DigestToken first-use (no pixels, ever); elder touches are email replies until
the wave-5 token surface exists; catch-up reads feed_last_seen_at, which only
remembers the newest visit, so run the rollup weekly, not months later. Ship
the undercount, never enrich to pass.
"""

from __future__ import annotations

import datetime

from django.db import transaction
from django.utils import timezone

from .models import (
    Comment,
    DigestToken,
    Member,
    MemberWeekPresence,
    Pod,
    PodWeekMetrics,
    Post,
    Reaction,
    Yard,
    YardWeekMetrics,
)


def rollup_week(yard: Yard, week_start: datetime.date) -> YardWeekMetrics:
    """Compute and store one yard's week. Idempotent: re-running replaces the
    same (yard, week) rows rather than duplicating them."""
    start = timezone.make_aware(datetime.datetime.combine(week_start, datetime.time.min))
    end = start + datetime.timedelta(days=7)

    members = list(Member.objects.filter(pods__yards=yard).distinct())
    member_ids = [m.id for m in members]
    yard_pods = list(Pod.objects.filter(yards=yard))
    pod_ids = [p.id for p in yard_pods]

    week_posts = Post.objects.filter(
        pod_id__in=pod_ids, deleted_at__isnull=True, created_at__gte=start, created_at__lt=end
    )
    posted_member_ids = set(week_posts.values_list("author_id", flat=True))
    commented_member_ids = set(
        Comment.objects.filter(
            deleted_at__isnull=True, created_at__gte=start, created_at__lt=end
        ).values_list("author_id", flat=True)
    )
    reacted_member_ids = set(
        Reaction.objects.filter(created_at__gte=start, created_at__lt=end).values_list(
            "member_id", flat=True
        )
    )
    visited_member_ids = {
        m.id for m in members if m.feed_last_seen_at and start <= m.feed_last_seen_at < end
    }
    digest_open_member_ids = set(
        DigestToken.objects.filter(first_used_at__gte=start, first_used_at__lt=end).values_list(
            "member_id", flat=True
        )
    )
    touched = (
        posted_member_ids
        | commented_member_ids
        | reacted_member_ids
        | visited_member_ids
        | digest_open_member_ids
    )

    posts = list(week_posts)
    responded = 0
    for post in posts:
        deadline = post.created_at + datetime.timedelta(days=7)
        has_comment = Comment.objects.filter(
            post=post, deleted_at__isnull=True, created_at__lt=deadline
        ).exists()
        has_reaction = Reaction.objects.filter(post=post, created_at__lt=deadline).exists()
        if has_comment or has_reaction:
            responded += 1

    email_replies = Comment.objects.filter(
        via_email=True,
        deleted_at__isnull=True,
        created_at__gte=start,
        created_at__lt=end,
        author_id__in=member_ids,
    ).count()

    with transaction.atomic():
        for member in members:
            MemberWeekPresence.objects.update_or_create(
                member=member,
                week_start=week_start,
                defaults={"present": member.id in touched},
            )
        for pod in yard_pods:
            PodWeekMetrics.objects.update_or_create(
                pod=pod,
                week_start=week_start,
                defaults={"post_count": sum(1 for post in posts if post.pod_id == pod.id)},
            )
        row, _created = YardWeekMetrics.objects.update_or_create(
            yard=yard,
            week_start=week_start,
            defaults={
                "member_count": len(members),
                "wcm": len(touched & set(member_ids)),
                "posting_breadth": len({post.pod_id for post in posts}),
                "posts_in_week": len(posts),
                "posts_responded": responded,
                "catch_up_members": len(visited_member_ids),
                "digest_opens": len(digest_open_member_ids & set(member_ids)),
                "email_replies": email_replies,
            },
        )
    return row
