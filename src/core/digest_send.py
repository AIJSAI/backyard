"""Send orchestration (S-501): who gets a digest now, sent through one function.

send_due_digests is THE send path — the management command calls it today, the
Procrastinate task calls the same function when the worker container lands, and
neither ever grows send logic of its own (the same no-second-path rule
scoping.py states for reads). It carries identifiers only, never content
(TS-DJ-11): every email body is re-resolved through digest.build_digest at send
time, so a post deleted or narrowed after the due list was computed simply is
not in what goes out.

Each (member, yard) send is one atomic act. The subscription is re-fetched
under lock INSIDE the transaction, so a member revoked or unsubscribed between
due-resolution and send gets nothing (TM-1: revocation's registry step disables
the subscription, and the re-check here is what makes "cancel queued sends"
true). The issue row's unique constraint makes overlapping runs idempotent. A
transport failure records on DigestDelivery for the admin panel and NEVER
touches subscription state (T-EMAIL-6: bounces surface, nothing auto-severs);
a hard crash rolls the whole recipient back — fully recorded or fully absent,
never half-sent-marked (the TS-DJ-2 shape).

Duplicate honesty: the SMTP conversation happens inside the transaction, so a
crash in the window between relay acceptance and commit re-sends that one
digest on the next run. At family scale a rare duplicate email is the right
side of that trade (the alternative is silently recording sends that never
happened); provider-grade dedup belongs to the delivery matrix when a provider
exists.
"""

from __future__ import annotations

import datetime
import smtplib
from dataclasses import dataclass, field

from django.db import transaction

from . import digest, digest_links, digesting, emailing, reply_addresses, scoping
from .models import DigestDelivery, DigestIssue, DigestSubscription


@dataclass
class SendReport:
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    crashed: int = 0
    details: list[str] = field(default_factory=list)

    def note(self, outcome: str, what: str) -> None:
        self.details.append(f"{outcome}: {what}")


def send_due_digests(now: datetime.datetime) -> SendReport:
    """Send every digest due at `now`: one email per (member, yard), each its
    own transaction, resolved live. Synchronous and enqueue-shaped on purpose —
    cron-able today, worker-wrapped later, same function either way."""
    report = SendReport()
    for due in digesting.due_recipients(now):
        member = due.subscription.member
        # One unsubscribe capability per subscription per RUN, shared by that
        # run's per-yard emails: rotating per email would kill the first
        # email's link the moment the second sent (live-repro finding on the
        # bridge topology). The first sending yard mints it, inside its own
        # transaction, so a fully rolled-back run rolls the rotation back too.
        unsubscribe_raw: str | None = None
        for yard in scoping.visible_yards(member):
            # Per-recipient isolation (#38 review MEDIUM): one poisoned row must
            # not starve every later recipient on every run. _send_one's atomic
            # block still rolls the crashed recipient back whole (TS-DJ-2); the
            # batch continues, and the command surfaces the crash count loudly.
            try:
                outcome, unsubscribe_raw = _send_one(
                    subscription_id=due.subscription.pk,
                    yard_id=yard.pk,
                    window_start=due.window_start,
                    window_end=due.window_end,
                    unsubscribe_raw=unsubscribe_raw,
                )
            except Exception as exc:  # noqa: BLE001  # the isolation point, by design
                report.crashed += 1
                report.note("crashed", f"member={member.pk} yard={yard.pk} {type(exc).__name__}")
                continue
            setattr(report, outcome, getattr(report, outcome) + 1)
            report.note(outcome, f"member={member.pk} yard={yard.pk}")
    return report


def _send_one(
    *,
    subscription_id: int,
    yard_id: int,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    unsubscribe_raw: str | None,
) -> tuple[str, str | None]:
    """One (member, yard) digest, atomically. Returns (outcome, the unsubscribe
    raw in play) where outcome is 'sent', 'failed', or 'skipped'. Takes
    identifiers only (TS-DJ-11) plus the run's already-minted unsubscribe raw,
    if an earlier yard minted one: everything else is re-read live inside the
    transaction."""
    with transaction.atomic():
        subscription = (
            DigestSubscription.objects.select_for_update()
            .select_related("member")
            .get(pk=subscription_id)
        )
        member = subscription.member
        # The liveness re-check that makes queued-send cancellation real (TM-1):
        # revocation disabled the subscription, unsubscribe flipped enabled,
        # a pod-leave dropped the yard — whatever happened since the due list
        # was computed wins, because it is checked NOW, under lock.
        if not subscription.enabled or subscription.confirmed_at is None:
            return "skipped", unsubscribe_raw
        if yard_id not in scoping.member_yard_ids(member):
            return "skipped", unsubscribe_raw

        # The window anchors per (member, yard), not per member (#38 review
        # MEDIUM): after a partial crash, the crashed yard resumes from ITS own
        # newest issue, so no yard ever loses a window to a sibling's success.
        # The due computation's member-level anchor is only the first-digest
        # fallback.
        newest_for_yard = (
            DigestIssue.objects.filter(member=member, yard_id=yard_id)
            .order_by("-window_end")
            .first()
        )
        # No issue for THIS yard yet means its first digest, anchored at
        # confirmation exactly like due_recipients' first-ever case — never at
        # a sibling yard's success, which is how a crashed yard's window was
        # getting lost.
        if newest_for_yard is not None:
            yard_window_start = newest_for_yard.window_end
        else:
            yard_window_start = subscription.confirmed_at or window_start
        if yard_window_start >= window_end:
            return "skipped", unsubscribe_raw  # this yard is already covered

        issue, created = DigestIssue.objects.get_or_create(
            member=member,
            yard_id=yard_id,
            window_start=yard_window_start,
            defaults={"window_end": window_end},
        )
        if not created:
            return "skipped", unsubscribe_raw  # an overlapping run covered this window

        # Everything from the token mint onward sits behind a savepoint (#38
        # review HIGH): a transport failure must not commit a rotated
        # unsubscribe digest whose raw value only exists in an email the relay
        # refused — that would kill the member's previously emailed link with
        # no delivered replacement. Rolling back to here restores the old
        # digest and drops the orphan DigestToken, while the issue row and the
        # delivery record still commit.
        savepoint = transaction.savepoint()
        raw_digest_token = digest_links.mint(issue)
        rotated_here = False
        if unsubscribe_raw is None:
            unsubscribe_raw = digesting.rotate_unsubscribe_token(subscription)
            rotated_here = True
        # Per-post reply capabilities (S-502), minted inside the savepoint so a
        # refused send also rolls back the supersession of the member's older
        # addresses (a failed send must not kill last week's working ones).
        post_ids = list(digest_links.issue_posts(issue).values_list("id", flat=True))
        reply_domain = emailing.reply_domain()
        reply_map = {
            post_id: f"{local}@{reply_domain}"
            for post_id, local in reply_addresses.mint_for_issue(issue, post_ids).items()
        }
        built = digest.build_digest(
            issue,
            digest_token=raw_digest_token,
            unsubscribe_token=unsubscribe_raw,
            reply_addresses=reply_map,
        )
        try:
            emailing.send_family_email(
                to=subscription.address,
                subject=built.subject,
                text=built.text,
                html=built.html,
            )
        except (smtplib.SMTPException, OSError) as exc:
            transaction.savepoint_rollback(savepoint)
            # Transport truth for the admin panel (T-EMAIL-6): the failure is
            # recorded, the issue stays (so the next run does not hammer the
            # same window), and subscription state is untouched. Anything
            # non-transport propagates and rolls this recipient back whole.
            DigestDelivery.objects.create(
                issue=issue,
                status=DigestDelivery.REJECTED,
                detail=str(exc)[:200],
            )
            # If this call minted the rotation, it was just rolled back: the
            # next yard must re-rotate rather than email a raw whose digest no
            # longer exists.
            return "failed", (None if rotated_here else unsubscribe_raw)
        transaction.savepoint_commit(savepoint)
        DigestDelivery.objects.create(issue=issue, status=DigestDelivery.HANDED_TO_RELAY)
        return "sent", unsubscribe_raw
