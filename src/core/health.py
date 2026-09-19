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
import json
import os
import pathlib
import re
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

# The one health field an OPERATOR writes. The copy step lives on the HOST on purpose (the
# destination credential must not sit beside the ciphertext on the data volume, which is
# T-BACKUP-1), so the instance cannot watch the copy happen — it can only be TOLD. This is
# the file the host's job writes to say how it went; the contract is in
# docs/runbooks/backup-restore.md, "Getting a copy off the box".
OFFBOX_STATUS_NAME = ".offbox-status.json"
_OFFBOX_LABEL = "Off-box copy"
# A nightly copy job that has not reported success in two nights has missed one. One night
# would alarm on every host whose cron runs a little later than the instance's clock.
OFFBOX_STALE_HOURS = 48
# Enough for the contract plus a generous error sentence, and nowhere near enough to matter
# on a box whose problem may BE memory or disk. The file is operator-written, on the volume
# the app also writes to, and read by a worker job and by an endpoint a robot polls.
OFFBOX_MAX_BYTES = 4096
# The error is the host's words, quoted into an operator's email. Long enough to carry a
# real rclone or rsync line, short enough that it cannot become the email.
OFFBOX_ERROR_CHARS = 160
# Two machines, two clocks. A host a few seconds or a minute ahead of the instance has taken
# a copy; a stamp hours ahead is a broken clock or a forged file, and it matters because a
# future date is the one value that can never age into an alarm.
OFFBOX_CLOCK_SKEW = datetime.timedelta(minutes=5)
# Control characters, including the newline. The weekly email is one line per field and an
# alarming line starts with "[!]", so an error carrying newlines could write lines of its
# own into an operator's health report. Stripped at the source; HTML escaping stays the
# renderer's job (Django autoescapes every template, `.txt` included, and /healthz is
# JSON-encoded), because escaping twice is how "&amp;amp;" reaches a reader.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


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
    """Whether the NIGHTLY backup is WORKING, which "last backup" alone cannot say.

    A backup that ran two days ago and a backup that has been refusing to run for two days
    produce the same "Last backup" line, and the second one is the emergency. The newest
    failure is compared against the newest SCHEDULED run only: a hand-run `backup_instance`
    writes a BackupRun row too, and taking one by hand is the operator's first response to
    this very alarm, so counting it would flip the line to "working" and /healthz back to
    `ok` with the scheduler still dead. The row carries its own provenance
    (BackupRun.Source), so this asks the database rather than inferring ownership from a
    filename anybody can write.
    """
    failure = BackupFailure.objects.order_by("-occurred_at").first()
    if failure is None:
        return Field("Scheduled backup", "no failures recorded")
    days = max(0, (now - failure.occurred_at).days)
    when = "today" if days == 0 else f"{days} day{'s' if days != 1 else ''} ago"
    newest = (
        BackupRun.objects.filter(source=BackupRun.Source.SCHEDULED).order_by("-finished_at").first()
    )
    if newest is not None and newest.finished_at >= failure.occurred_at:
        return Field("Scheduled backup", f"working; last failure {when}")
    return Field("Scheduled backup", f"FAILING since {when} — {failure.error}", alarming=True)


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
        # The REASON, when there is one. A check that has never succeeded still recorded why
        # it failed, and "no successful check yet" alone cannot distinguish a certificate
        # that is broken from one this box simply cannot reach from the inside (a NAT
        # without hairpinning), which are different jobs for the operator.
        reason = status.error if status is not None and status.error else "no successful check yet"
        return Field("TLS certificate", f"{NOT_MEASURED} — {reason}", True)
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


def offbox_status_path() -> pathlib.Path:
    """Where the host's copy job reports, beside the archives it copies."""
    return pathlib.Path(settings.BACKUP_ROOT) / OFFBOX_STATUS_NAME


def _one_line(text: str, limit: int) -> str:
    """One line, capped. Whatever the host wrote, this is what an operator reads."""
    cleaned = " ".join(_CONTROL_CHARACTERS.sub(" ", text).split())
    if len(cleaned) > limit:
        return cleaned[:limit].rstrip() + "…"
    return cleaned


def _offbox_error(value: object) -> str:
    """The host's reason, quoted safely, or a stand-in when it gave none."""
    reason = _one_line(value, OFFBOX_ERROR_CHARS) if isinstance(value, str) else ""
    return reason or "the copy job gave no reason"


def _offbox_when(age: datetime.timedelta) -> str:
    """How long ago, in the units this field turns on: hours inside the window, days past
    it. "2 days ago" is the sentence that makes a stale copy obvious at a glance."""
    hours = max(0, int(age.total_seconds() // 3600))
    if hours < 1:
        return "less than an hour ago"
    if hours < OFFBOX_STALE_HOURS:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def _offbox_at(value: object) -> datetime.datetime | None:
    """The `at` stamp, or None if the file does not carry one this can read."""
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        # The contract says UTC, and `date -u +%Y-%m-%dT%H:%M:%S` without the trailing Z is
        # the near-miss a host job actually writes. Reading it as UTC is the contract, not
        # a guess; treating it as local time would be the guess.
        return stamp.replace(tzinfo=datetime.UTC)
    return stamp


def _read_offbox_status() -> dict[str, object]:
    """The status file as a JSON object, or raise OSError/ValueError saying what is wrong.

    Hostile input by construction: operator-written, on the volume the app itself writes to,
    read by a weekly worker job and by an endpoint an outside monitor polls every half hour.
    Every way this can go wrong has to become a FIELD, so each one is raised with a reason
    that finishes the sentence "the status file ...".
    """
    # O_NOFOLLOW rather than `is_symlink()` and then open: the check and the open must be
    # the same syscall, or a link swapped in between them is followed anyway. A followed
    # link would turn this reader into a way to make the instance open a path of somebody
    # else's choosing — a mounted keyfile, `/proc/self/environ` — and quote what it found
    # into the operator's weekly email.
    descriptor = os.open(offbox_status_path(), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        # One byte past the cap: a file at the cap is read whole, and an oversized one is
        # refused without ever being held. The box whose copy job is failing may be the box
        # that is out of memory or disk.
        blob = os.read(descriptor, OFFBOX_MAX_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(blob) > OFFBOX_MAX_BYTES:
        raise ValueError(f"is larger than {OFFBOX_MAX_BYTES} bytes")
    try:
        payload = json.loads(blob.decode("utf-8"))
    except ValueError as exc:  # both a bad decode and bad JSON land here
        raise ValueError(f"is not valid JSON ({_one_line(str(exc), 60)})") from exc
    if not isinstance(payload, dict):
        raise ValueError("does not hold a JSON object")
    return payload


def _offbox_unreadable(reason: str) -> Field:
    """A status file that is present and wrong.

    Unlike a missing one this DEGRADES, and it is reported as MEASURED so that it reaches
    /healthz: somebody wired a copy job up and it is now writing rubbish, or something else
    is writing this path. Either way the instance was asked a question it can no longer
    answer, which is a fact about the instance and not a gap in what it knows.
    """
    return Field(
        _OFFBOX_LABEL,
        f"UNREADABLE — {OFFBOX_STATUS_NAME} {_one_line(reason, OFFBOX_ERROR_CHARS)}, so the "
        "instance cannot tell whether a copy left the box",
        alarming=True,
    )


def _offbox_field(now: datetime.datetime) -> Field:
    """Whether a copy of the archives got off this box, as reported by the HOST (T-OP-G3).

    The instance cannot watch this happen. The copy step is deliberately outside the
    containers, because a copy step inside one needs the destination's credential and that
    credential would then sit beside the ciphertext on the data volume (T-BACKUP-1) — so
    the only honest way to answer is to be TOLD, by a file the host's job writes.

    Four states, and the difference between the first two is the one that matters: NO FILE
    means nobody set a copy job up, which is where every instance starts and is not a
    failure, while a file that is there and wrong is. An instance that went `degraded` the
    day this shipped would teach its one operator that the word means nothing — and the
    backup alarm, the disk alarm and the certificate alarm all ride that same word.
    """
    try:
        payload = _read_offbox_status()
    except FileNotFoundError:
        # NOT SET UP. Same wording as before this field could measure anything, because for
        # an instance with no copy job nothing has changed: unmeasured, unalarming, `ok`.
        return Field(
            _OFFBOX_LABEL,
            f"{NOT_MEASURED} — the instance cannot see where you copied a backup to "
            f"(T-OP-G3) unless the host's copy job writes {OFFBOX_STATUS_NAME} beside the "
            "archives (docs/runbooks/backup-restore.md); until it does, check it yourself",
        )
    except OSError as exc:
        # A symlink (ELOOP), a directory, a permission, a failing disk. Something is at that
        # path and the instance cannot read it, which is not the same as nobody setting one up.
        return _offbox_unreadable(f"could not be read ({exc.strerror or type(exc).__name__})")
    except ValueError as exc:
        return _offbox_unreadable(str(exc))

    ok = payload.get("ok")
    if not isinstance(ok, bool):
        return _offbox_unreadable("does not say whether the copy succeeded")
    at = _offbox_at(payload.get("at"))
    if at is None:
        # Strict, unlike `remote_objects` below: `ok` and `at` are what the four states are
        # computed from, and a success with no readable time is a success that can never
        # age into an alarm.
        return _offbox_unreadable("carries no `at` time the instance can read")
    if at > now + OFFBOX_CLOCK_SKEW:
        return _offbox_unreadable("is dated in the future")

    when = _offbox_when(now - at)
    if not ok:
        return Field(
            _OFFBOX_LABEL, f"FAILED {when} — {_offbox_error(payload.get('error'))}", alarming=True
        )
    if now - at > datetime.timedelta(hours=OFFBOX_STALE_HOURS):
        return Field(
            _OFFBOX_LABEL,
            f"LAST COPIED {when} — no success reported in over {OFFBOX_STALE_HOURS} hours, so "
            "the host's copy job has stopped or is failing silently",
            alarming=True,
        )
    remote = payload.get("remote_objects")
    # Decoration, and lenient on purpose: `isinstance(True, int)` is True in Python, and a
    # host job that reports its count as a string has a cosmetic bug. Turning a family's
    # instance red over a number nobody acts on is how a real alarm gets learned as noise.
    count = (
        f" ({remote} objects at the destination)"
        if isinstance(remote, int) and not isinstance(remote, bool) and remote >= 0
        else ""
    )
    return Field(_OFFBOX_LABEL, f"copied {when}{count}")


def measure(now: datetime.datetime | None = None) -> list[Field]:
    """Every field the health email reports, measured or explicitly not."""
    now = now or timezone.now()
    return [
        _last_backup_field(now),
        _scheduled_backup_field(now),
        _disk_field(),
        _domain_field(now),
        _certificate_field(now),
        # The T-MON-1 ask the app genuinely cannot answer today. Listed on purpose: an
        # operator who sees five expected lines and four printed ones learns nothing, and a
        # reader of this email should be able to tell which parts of "nothing is watching"
        # are still true.
        Field(
            "Failed sign-ins",
            f"{NOT_MEASURED} — no auth audit log exists yet (T-MON-1)",
        ),
        _offbox_field(now),
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
