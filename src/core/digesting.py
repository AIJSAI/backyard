"""The digest lifecycle (S-501): enroll, confirm, unsubscribe, and who is due.

State machine, in family terms: a member turns the digest on and says how often;
their address gets ONE content-free confirmation email; only after they click it
does any family content flow; unsubscribing is a two-step confirm and flips the
subscription off without touching membership. The rendering and sending of actual
digests are separate increments; this module owns only the lifecycle, so there is
exactly one place that answers "may this address receive family content" and one
place that answers "who is due now".

Token discipline: the confirm and unsubscribe links are bearer capabilities held
to the Invite bar (>=128-bit CSPRNG, SHA-256 digest at rest, raw value shown only
inside the email that mints it). An invalid, revoked, or reused token resolves
exactly like an unknown one (DigestTokenInvalid carries nothing), so the links
leak no subscription existence. Revocation voids both digests through the TM-1
registry (core/revocation.py) when a member is removed.
"""

from __future__ import annotations

import datetime
import hashlib
import secrets
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from . import emailing
from .models import DigestSubscription, Member

# The confirmation email is content-free by construction (T-EMAIL-6): composed
# here from constants and the minted link only, so no family name, member name,
# or post fragment can ever reach an unconfirmed (possibly typo'd) address.
_CONFIRM_SUBJECT = "Confirm this address for a Backyard digest"
_CONFIRM_BODY = (
    "Someone asked a Backyard family instance to send its digest to this email "
    "address.\n\nIf that was you, confirm here:\n\n{link}\n\nIf it was not you, "
    "ignore this email; nothing else will be sent to this address."
)


class DigestTokenInvalid(Exception):
    """Unknown, voided, or superseded token. Carries nothing on purpose: the
    confirm and unsubscribe pages must be byte-identical for every failure shape."""


def _digest(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


_CADENCE_PERIOD = {
    DigestSubscription.DAILY: datetime.timedelta(days=1),
    DigestSubscription.WEEKLY: datetime.timedelta(days=7),
    # A fixed 30 days, documented rather than calendar-clever: elders get a steady
    # rhythm and the clock stays testable. Revisit only on a real complaint.
    DigestSubscription.MONTHLY: datetime.timedelta(days=30),
}


def subscribe(member: Member, *, address: str, cadence: str) -> DigestSubscription:
    """Enroll (or re-point) a member's digest, confirming only when it must.

    An address change (or a first enrollment, or a resend to a still-unconfirmed
    address) resets confirmed_at and sends the content-free confirmation: family
    content never follows an address the holder has not acknowledged (T-EMAIL-6).
    A cadence or re-enable tweak on an already-confirmed address changes nothing
    about trust, so it keeps the confirmation and sends no email (security review
    of #35 LOW-1: an elder switching weekly to daily must not silently pause their
    digest behind a new confirmation link). Cadence falls back to weekly on an
    unknown value (fail to the default, never to an error page from a form race).
    """
    if cadence not in _CADENCE_PERIOD:
        cadence = DigestSubscription.WEEKLY
    with transaction.atomic():
        existing = DigestSubscription.objects.select_for_update().filter(member=member).first()
        if existing and existing.address == address and existing.confirmed_at is not None:
            existing.cadence = cadence
            existing.enabled = True
            existing.save(update_fields=["cadence", "enabled", "updated_at"])
            return existing
        raw_confirm = secrets.token_urlsafe(32)  # 256 bits, shown once (in the email)
        # The raw unsubscribe value is deliberately dropped: nothing emails it at
        # this stage. The send path rotates unsubscribe_token_digest per issue and
        # mails that raw value inside the digest; the digest stored here only
        # guarantees the column is never empty-matchable in the interim.
        raw_unsubscribe = secrets.token_urlsafe(32)
        subscription, _created = DigestSubscription.objects.update_or_create(
            member=member,
            defaults={
                "address": address,
                "cadence": cadence,
                "enabled": True,
                "confirmed_at": None,
                "confirm_token_digest": _digest(raw_confirm),
                "unsubscribe_token_digest": _digest(raw_unsubscribe),
            },
        )
    emailing.send_family_email(
        to=address,
        subject=_CONFIRM_SUBJECT,
        text=_CONFIRM_BODY.format(link=emailing.absolute_url(f"/digest/confirm/{raw_confirm}/")),
    )
    return subscription


def _by_token(field: str, raw_token: str) -> DigestSubscription:
    if not raw_token:
        raise DigestTokenInvalid
    subscription = DigestSubscription.objects.filter(**{field: _digest(raw_token)}).first()
    if subscription is None:
        raise DigestTokenInvalid
    return subscription


def peek_confirmation(raw_token: str) -> DigestSubscription:
    """The subscription a confirm token points at, for the acknowledge page.
    Loading the link never confirms; confirming is an explicit POST."""
    return _by_token("confirm_token_digest", raw_token)


def confirm(raw_token: str) -> DigestSubscription:
    """Acknowledge the address (T-EMAIL-6). The token is single-use: confirming
    voids it, so a replayed link resolves like an unknown one."""
    with transaction.atomic():
        subscription = (
            DigestSubscription.objects.select_for_update()
            .filter(confirm_token_digest=_digest(raw_token))
            .first()
        )
        if not raw_token or subscription is None:
            raise DigestTokenInvalid
        subscription.confirmed_at = timezone.now()
        subscription.confirm_token_digest = ""
        subscription.save(update_fields=["confirmed_at", "confirm_token_digest"])
        return subscription


def peek_unsubscribe(raw_token: str) -> DigestSubscription:
    """The subscription an unsubscribe token points at, for the confirm step
    (S-501: unsubscribe requires a confirm step, never severs silently)."""
    return _by_token("unsubscribe_token_digest", raw_token)


def unsubscribe(raw_token: str) -> DigestSubscription:
    """Turn the digest off. Email-only: PodMembership is never touched here, and
    the token stays valid for the subscription so a later 'turn it back on' from
    the settings page is the member's own act."""
    subscription = _by_token("unsubscribe_token_digest", raw_token)
    subscription.enabled = False
    subscription.save(update_fields=["enabled"])
    return subscription


@dataclass
class DueRecipient:
    """One member due a digest now, with the window the next issue should cover."""

    subscription: DigestSubscription
    window_start: datetime.datetime
    window_end: datetime.datetime


def due_recipients(now: datetime.datetime) -> list[DueRecipient]:
    """Every member whose next digest is due at `now`.

    Due means: enabled, address confirmed (T-EMAIL-6), still in at least one pod
    (removal and leave drop a member here immediately, TM-1 — the check is live
    PodMembership, not any snapshot), and their cadence period has elapsed since
    their newest issue (or since confirmation, for a first digest). The window
    runs from that anchor to now; the send path re-resolves audience inside it
    at send time (TM-2), so nothing here carries content.
    """
    due: list[DueRecipient] = []
    subscriptions = (
        DigestSubscription.objects.filter(enabled=True, confirmed_at__isnull=False)
        .filter(member__pod_memberships__isnull=False)
        .select_related("member")
        .distinct()
    )
    for subscription in subscriptions:
        # Skip-not-crash on a cadence outside the dict (security review of #35
        # LOW-2): choices are not DB-enforced, and one bad row must degrade to one
        # member's missed digest, never a whole-batch outage.
        period = _CADENCE_PERIOD.get(subscription.cadence)
        if period is None:
            continue
        newest = subscription.member.digest_issues.order_by("-window_end").first()
        confirmed_at = subscription.confirmed_at
        if confirmed_at is None:  # filtered above; plain guard narrows the type
            continue
        anchor = newest.window_end if newest else confirmed_at
        if anchor + period <= now:
            due.append(DueRecipient(subscription=subscription, window_start=anchor, window_end=now))
    return due
