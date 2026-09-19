"""Instance health, for the weekly admin email and /healthz (S-806, threat row T-MON-1).

T-MON-1 is rated High and its stated mitigation did not exist: *"Nothing is watching: a
dead backup cron or a filling disk goes unnoticed for months, giving every other threat
unlimited dwell time."*

The rule this module is built around: **a field with no instrumentation is reported as NOT
MEASURED, never omitted.** An email that quietly drops a signal it cannot compute reads as
"everything is fine", which is the failure the threat row describes, dressed up as a
feature. Two of the five fields T-MON-1 lists genuinely cannot be answered by the app
today, and they say so on every send.

Nothing here is per-person activity. It is instance health, not surveillance: no member
names, no counts of who did what (P1, and the calm-surfaces rule in the threat model's
tension list).

Two readers, two amounts of detail. The weekly email and a signed-in instance admin get
every field; the unauthenticated /healthz endpoint gets `public_status` and nothing else,
because "3% disk free, no backup since July" published at a guessable URL is a map for
whoever asks first.
"""

from __future__ import annotations

import datetime
import pathlib
import shutil
from dataclasses import dataclass
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone

from .models import BackupFailure, BackupRun, CertificateStatus, DomainStatus

# What a field looks like when the app cannot answer it. Deliberately loud: an operator
# skimming on a phone must be able to tell "healthy" from "unknown" at a glance.
NOT_MEASURED = "NOT MEASURED"

# The whole of what an unauthenticated caller is told. Two words, no fields: /healthz is a
# public URL on a private family instance, and disk free space, backup age and certificate
# dates are an operational map for anyone who asks (TM-5). The detail goes to the weekly
# email and to a signed-in instance admin.
OK = "ok"
DEGRADED = "degraded"

# Below this, the disk line is called out rather than merely reported.
LOW_DISK_PERCENT = 15
# Inside this many days, the domain line is called out.
DOMAIN_WARN_DAYS = 45
# A backup older than this is called out.
STALE_BACKUP_DAYS = 8
# Inside this many days, the certificate line is called out. Caddy renews at roughly 30 days
# remaining on a 90-day certificate, so a certificate still here at 14 days has had two
# weeks of failed renewals — and the external monitor (.github/workflows/monitor.yml) uses
# the same threshold, so the two alarms agree rather than arguing.
CERTIFICATE_WARN_DAYS = 14


@dataclass(frozen=True)
class Field:
    label: str
    value: str
    alarming: bool = False

    @property
    def measured(self) -> bool:
        """Whether the app produced a real measurement.

        startswith, not equality: an unmeasured value always carries its REASON
        ("NOT MEASURED — no auth audit log exists yet"), so an equality check reported
        every one of them as measured. Reviewer catch on #102, and a latent trap rather
        than a visible bug — nothing depended on it yet, which is exactly how it would
        have survived to the first caller that did.
        """
        return not self.value.startswith(NOT_MEASURED)


def instance_domain() -> str:
    """The bare hostname of BASE_URL, which is the domain the family's links point at."""
    return urlparse(settings.BASE_URL).hostname or ""


def _last_backup_field(now: datetime.datetime) -> Field:
    run = BackupRun.objects.order_by("-finished_at").first()
    if run is None:
        # Distinct from NOT MEASURED: the instrumentation exists, the backup does not.
        # Conflating "never backed up" with "cannot tell" would hide the worse case.
        return Field("Last backup", "NEVER — no backup has completed on this instance", True)
    # max(0, ...) because auto_now_add stamps the row from the DATABASE clock, which can
    # sit microseconds after the `now` a caller passed in — so a backup taken seconds ago
    # rendered as "-1 days ago" in the operator's email. Caught by a test, not by reading.
    days = max(0, (now - run.finished_at).days)
    kind = "encrypted" if run.encrypted else "PLAINTEXT"
    human = "today" if days == 0 else f"{days} day{'s' if days != 1 else ''} ago"
    return Field("Last backup", f"{human} ({kind})", alarming=days >= STALE_BACKUP_DAYS)


def _scheduled_backup_field(now: datetime.datetime) -> Field:
    """Whether the nightly backup is WORKING, which "last backup" alone cannot say.

    A backup that ran two days ago and a backup that has been refusing to run for two days
    produce the same "Last backup" line, and the second one is the emergency. This reads the
    failure the scheduled run recorded and compares it against the newest success.
    """
    failure = BackupFailure.objects.order_by("-occurred_at").first()
    if failure is None:
        return Field("Scheduled backup", "no failures recorded")
    last_success = BackupRun.objects.order_by("-finished_at").first()
    if last_success is not None and last_success.finished_at >= failure.occurred_at:
        days = max(0, (now - failure.occurred_at).days)
        when = "today" if days == 0 else f"{days} day{'s' if days != 1 else ''} ago"
        return Field("Scheduled backup", f"working; last failure {when}")
    days = max(0, (now - failure.occurred_at).days)
    since = "today" if days == 0 else f"{days} day{'s' if days != 1 else ''} ago"
    return Field("Scheduled backup", f"FAILING since {since} — {failure.error}", alarming=True)


def _measurable_path() -> pathlib.Path:
    """The nearest existing ancestor of MEDIA_ROOT.

    MEDIA_ROOT may not exist yet — on a fresh box before the first upload, or in any
    environment where the volume is mounted elsewhere — and disk headroom is a property of
    the VOLUME, not of whether one directory has been created. Walking up finds the same
    filesystem the media will land on, so the field reports a real number instead of
    NOT MEASURED (which, being alarming, made a healthy instance shout).
    """
    path = pathlib.Path(settings.MEDIA_ROOT)
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return pathlib.Path(".")


def _disk_field() -> Field:
    try:
        usage = shutil.disk_usage(_measurable_path())
    except OSError as exc:  # pragma: no cover - an unreadable root is its own alarm
        return Field("Disk headroom", f"{NOT_MEASURED} ({exc.strerror})", True)
    free_percent = round(usage.free / usage.total * 100)
    free_gb = usage.free / 1024**3
    return Field(
        "Disk headroom",
        f"{free_percent}% free ({free_gb:.1f} GB)",
        alarming=free_percent < LOW_DISK_PERCENT,
    )


def _domain_field(now: datetime.datetime) -> Field:
    domain = instance_domain()
    status = DomainStatus.objects.filter(domain=domain).first()
    if status is None or status.checked_at is None:
        return Field("Domain", f"{NOT_MEASURED} — no successful lookup yet", True)
    if status.expires_at is None:
        return Field("Domain", f"{NOT_MEASURED} — {status.error or 'lookup failed'}", True)
    days = (status.expires_at - now).days
    stale_note = ""
    if (now - status.checked_at).days > 14:
        # A number from a month ago presented as current is worse than no number.
        stale_note = f", last checked {(now - status.checked_at).days} days ago"
    if days < 0:
        # "expires in -3 days" at the single moment this line matters most. Reviewer catch
        # on #102: a lapsed domain hands every printed QR to a squatter (T-OP-G4), so it
        # says so in words an operator cannot misread.
        gone = abs(days)
        return Field(
            "Domain",
            f"{domain} EXPIRED {gone} day{'s' if gone != 1 else ''} ago — renew it NOW, "
            f"or a squatter inherits every printed QR and elder link{stale_note}",
            alarming=True,
        )
    return Field(
        "Domain",
        f"{domain} expires in {days} days{stale_note}",
        alarming=days <= DOMAIN_WARN_DAYS,
    )


def served_over_https() -> bool:
    """Whether this instance has a certificate to have an opinion about at all."""
    return settings.BASE_URL.lower().startswith("https://")


def _certificate_field(now: datetime.datetime) -> Field:
    """Days until the TLS certificate expires, from the row the worker refreshes.

    The one outage on this list that a non-technical family cannot route around: an expired
    certificate is a full-page browser warning everywhere at once, and the advice that fixes
    it is not advice a grandparent can follow.
    """
    if not served_over_https():
        # The local clean-machine repro is plain HTTP and has no certificate at all. Saying
        # so beats an alarming line on every developer's instance, which is how a real alarm
        # gets learned as noise.
        return Field(
            "TLS certificate",
            f"{NOT_MEASURED} — this instance is served over plain HTTP, so it has none",
        )
    status = CertificateStatus.objects.filter(domain=instance_domain()).first()
    if status is None or status.checked_at is None:
        return Field("TLS certificate", f"{NOT_MEASURED} — no successful check yet", True)
    if status.expires_at is None:
        return Field("TLS certificate", f"{NOT_MEASURED} — {status.error or 'check failed'}", True)
    days = (status.expires_at - now).days
    stale_days = (now - status.checked_at).days
    # The check runs daily, so three days without one is a worker that has stopped.
    stale_note = f", last checked {stale_days} days ago" if stale_days > 3 else ""
    if days < 0:
        gone = abs(days)
        return Field(
            "TLS certificate",
            f"EXPIRED {gone} day{'s' if gone != 1 else ''} ago — every browser in the family "
            f"now shows a full-page security warning{stale_note}",
            alarming=True,
        )
    return Field(
        "TLS certificate",
        f"expires in {days} days{stale_note}",
        alarming=days <= CERTIFICATE_WARN_DAYS,
    )


def measure(now: datetime.datetime | None = None) -> list[Field]:
    """Every field the health email reports, measured or explicitly not."""
    now = now or timezone.now()
    return [
        _last_backup_field(now),
        _scheduled_backup_field(now),
        _disk_field(),
        _domain_field(now),
        _certificate_field(now),
        # The two T-MON-1 asks for that the app genuinely cannot answer today. Listed on
        # purpose: an operator who sees five expected lines and four printed ones learns
        # nothing, and a reader of this email should be able to tell which parts of
        # "nothing is watching" are still true.
        Field(
            "Failed sign-ins",
            f"{NOT_MEASURED} — no auth audit log exists yet (T-MON-1)",
        ),
        Field(
            "Off-box backup age",
            f"{NOT_MEASURED} — the instance cannot see where you copied a backup to "
            f"(T-OP-G3); check it yourself",
        ),
    ]


def has_anything_alarming(fields: list[Field]) -> bool:
    return any(f.alarming for f in fields)


def public_status(fields: list[Field]) -> str:
    """`ok` or `degraded` — the entire public answer, from the same fields as the email.

    Only a field the instance actually MEASURED can degrade it, which is a narrower rule
    than the email's and deliberately so. An instance that cannot reach the registry knows
    less, not worse; the email says "NOT MEASURED — registry unreachable" and asks the
    operator to look, while an external monitor polling this endpoint every half hour would
    turn the same fact into a failing check every half hour until someone made it stop. The
    cases that matter here are the ones the instance is sure of: no backup has ever
    completed, the nightly backup is failing, the disk is nearly full, the certificate is
    nearly gone — including the whole dead-worker family, because a stopped worker ages the
    backup past its threshold and that IS measured.
    """
    return DEGRADED if any(f.alarming and f.measured for f in fields) else OK
