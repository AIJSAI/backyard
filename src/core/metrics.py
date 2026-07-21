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

from django.db import models, transaction
from django.utils import timezone

from .digest_links import in_yard_posts_q
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

    # The yard's own slice, through THE in-yard predicate (#40 review MEDIUM-1):
    # a bridge-pod post addressed exclusively to the other yard never lands in
    # this yard's counts.
    week_posts = (
        Post.objects.filter(deleted_at__isnull=True, created_at__gte=start, created_at__lt=end)
        .filter(in_yard_posts_q(yard.id))
        .distinct()
    )
    # Presence is GLOBAL on purpose (#40 review HIGH-1): "active" means any
    # deliberate touch anywhere (docs/metrics.md), and a per-yard posted set
    # would let rollup ORDER overwrite an active bridge member as quiet in the
    # one per-person datum. Every input to `touched` is yard-independent, so
    # every yard's rollup writes the identical presence row.
    posted_member_ids = set(
        Post.objects.filter(
            author_id__in=member_ids,
            deleted_at__isnull=True,
            created_at__gte=start,
            created_at__lt=end,
        ).values_list("author_id", flat=True)
    )
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
    # The published per-yard column is scoped to THIS yard's issues (#40 review
    # MEDIUM-2): a bridge member opening their paternal digest is one paternal
    # open, not one in each yard. The global set above still feeds presence.
    yard_digest_openers = set(
        DigestToken.objects.filter(
            first_used_at__gte=start, first_used_at__lt=end, issue__yard=yard
        ).values_list("member_id", flat=True)
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
        # Reciprocity is loop-closure by OTHERS (docs/metrics.md R2): the
        # author bumping their own post closes nothing (#40 review LOW-1).
        has_comment = (
            Comment.objects.filter(post=post, deleted_at__isnull=True, created_at__lt=deadline)
            .exclude(author=post.author)
            .exists()
        )
        has_reaction = (
            Reaction.objects.filter(post=post, created_at__lt=deadline)
            .exclude(member=post.author)
            .exists()
        )
        if has_comment or has_reaction:
            responded += 1

    email_replies = (
        Comment.objects.filter(
            via_email=True,
            deleted_at__isnull=True,
            created_at__gte=start,
            created_at__lt=end,
            author_id__in=member_ids,
        )
        .filter(
            # The same in-yard rule, one join deeper (#40 review MEDIUM-2).
            models.Q(post__audience_yards=yard)
            | models.Q(post__audience_yards__isnull=True, post__pod__yards=yard)
        )
        .distinct()
        .count()
    )

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
                "digest_opens": len(yard_digest_openers & set(member_ids)),
                "email_replies": email_replies,
            },
        )
    return row
