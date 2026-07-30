"""Build and send the weekly admin health email (S-806).

Rides the S-501 delivery machinery (`emailing.send_family_email`) rather than a second
send path, so the control-stripped subject, the standing anti-phishing footer and the
one-recipient-per-send rule all apply unchanged.

Recipients mirror the digest's rule exactly — an instance admin with a CONFIRMED address
(T-EMAIL-6) — rather than inventing a looser one for ops mail. The consequence is real and
documented rather than papered over: an admin who never confirmed an address gets no health
email, so the runbook tells them to subscribe, and `send_health_emails` reports having sent
none instead of returning quietly.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.template.loader import render_to_string
from django.utils import timezone

from . import emailing, health
from .models import DigestSubscription, Member


@dataclass(frozen=True)
class HealthSendResult:
    sent: int
    skipped_no_confirmed_address: int
    alarming: bool


def admin_recipients() -> list[tuple[Member, str]]:
    """Instance admins with a confirmed email address."""
    subscriptions = DigestSubscription.objects.filter(
        enabled=True,
        confirmed_at__isnull=False,
        member__role=Member.INSTANCE_ADMIN,
    ).select_related("member")
    return [(s.member, s.address) for s in subscriptions]


def build(now: datetime.datetime | None = None) -> tuple[str, str, bool]:
    """(subject, text, alarming) for this week's health email."""
    now = now or timezone.now()
    fields = health.measure(now)
    alarming = health.has_anything_alarming(fields)
    domain = health.instance_domain() or "this instance"
    subject = f"{domain}: {'needs attention' if alarming else 'weekly health check'}"
    text = render_to_string(
        "core/email/health.txt",
        {"fields": fields, "alarming": alarming, "domain": domain},
    )
    return subject, text, alarming


def send_health_emails(now: datetime.datetime | None = None) -> HealthSendResult:
    now = now or timezone.now()
    subject, text, alarming = build(now)
    recipients = admin_recipients()
    admin_count = Member.objects.filter(role=Member.INSTANCE_ADMIN).count()
    for _member, address in recipients:
        emailing.send_family_email(to=address, subject=subject, text=text)
    return HealthSendResult(
        sent=len(recipients),
        skipped_no_confirmed_address=max(0, admin_count - len(recipients)),
        alarming=alarming,
    )
