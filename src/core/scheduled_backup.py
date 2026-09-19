"""The daily instance backup, taken by the worker (S-802, S-806, threat row T-MON-1).

`backup_instance` existed and nothing ran it. A backup command nobody runs is a document,
not a backup, and T-MON-1's "a dead backup cron goes unnoticed for months" was generous
about this instance: there was no cron to die. This module is the thing that runs, on the
same Procrastinate periodic machinery as the digest and the health email (core/tasks.py).

No second implementation: it calls the SAME management command the runbook tells an
operator to type, with no `--no-encrypt`, so the encrypt-by-default refusal (S-802) is the
one that applies here too — an instance with no passphrase gets a loud failure and no
archive, never a plaintext copy of the family's whole history written at 03:30 every night.

A failure is recorded before it is raised (BackupFailure), because the archive is not the
only thing that has to survive the night: the REASON has to reach the operator's weekly
email and the health surface, or a backup that has been refusing to run for six days reads
exactly like one that ran six days ago.
"""

from __future__ import annotations

import datetime
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.db import DatabaseError
from django.utils import timezone

from .models import BackupFailure, BackupRun

logger = logging.getLogger(__name__)

# Our archives, and ONLY ours. Retention deletes files, and it shares a directory with the
# operator's own `backup-YYYY-MM-DD.bak` (the runbook's manual name) and the entrypoint's
# `preflight-*.dump`. A prefix plus a strict name pattern means a file this module did not
# write is never a deletion candidate, which is a property worth having by construction
# rather than by being careful.
ARCHIVE_PREFIX = "scheduled-"
ARCHIVE_SUFFIX = ".bak"
_ARCHIVE_NAME = re.compile(rf"^{ARCHIVE_PREFIX}(\d{{4}})-(\d{{2}})-(\d{{2}})\{ARCHIVE_SUFFIX}$")

# Grandfather-father-son retention. The weeklies are counted over every archive rather than
# over what the daily window leaves behind, so this is "14 days at full resolution, and
# roughly two months of Mondays", not "14 days plus a further eight weeks".
KEEP_DAILY = 14
KEEP_WEEKLY = 8

# Enough failures to see a pattern ("every night since Tuesday"), not so many that a broken
# instance grows an unbounded table. The health email reads only the newest one.
KEEP_FAILURES = 20

# Refuse a run that would fill the volume the family's photographs live on. Each archive is
# a FULL copy of the media tree plus the database, and up to KEEP_DAILY + KEEP_WEEKLY of
# them accumulate beside the originals: 10 GB of photos becomes ~200 GB of archives here.
# Writing until ENOSPC is the one failure this module must never cause -- a full /data stops
# uploads, and by default pgdata shares the same host filesystem, so it stops Postgres too.
# A refusal is recorded, mailed and visible at /healthz like any other failure, which makes
# it a loud "grow the disk", not a silent stop.
HEADROOM_MULTIPLE = 2  # room for tonight's archive and the staged copy the command makes


class ScheduledBackupFailed(Exception):
    """The daily backup produced no archive. Recorded first, then raised."""


@dataclass(frozen=True)
class ScheduledBackupResult:
    path: Path
    byte_count: int
    pruned: list[Path]


def archive_path(day: datetime.date) -> Path:
    """Today's archive. One file per day, so a re-run replaces rather than accumulates."""
    return Path(settings.BACKUP_ROOT) / f"{ARCHIVE_PREFIX}{day.isoformat()}{ARCHIVE_SUFFIX}"


def run(now: datetime.datetime | None = None) -> ScheduledBackupResult:
    """Take today's encrypted archive and prune the aged-out ones.

    Raises ScheduledBackupFailed, having first written the reason where the health email
    and the health surface can find it.
    """
    now = now or timezone.now()
    destination = archive_path(timezone.localtime(now).date())
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _require_headroom(destination.parent)
        options: dict[str, str] = {}
        if settings.BACKUP_PASSPHRASE_FILE:
            # The operator who followed the guide's tighter recommendation has no
            # BACKYARD_BACKUP_PASSPHRASE set at all; without this the nightly run refuses
            # every night on a correctly-configured instance.
            options["passphrase_file"] = settings.BACKUP_PASSPHRASE_FILE
        # No --no-encrypt, ever: the command refuses to write plaintext without it, and
        # that refusal is the control. It also verifies the archive decrypts before it
        # renames it into place, so what lands here is an archive that has been opened.
        call_command("backup_instance", str(destination), **options)
    except ScheduledBackupFailed as exc:
        # Our own refusal (the headroom guard). Its message is already the sentence the
        # operator should read, so it is recorded verbatim rather than wrapped in its own
        # class name by the broad handler below.
        _record_failure(str(exc))
        raise
    except Exception as exc:  # noqa: BLE001  # every failure must reach the email and /healthz
        # Deliberately broad, and this is the one place it is right. The point of this
        # module is that a night without an archive is LOUD and carries its REASON to the
        # weekly email and /healthz. An exception class nobody predicted -- a tarfile error
        # mid-archive, a bug in the command -- would otherwise leave "Scheduled backup: no
        # failures recorded" on the surface whose whole job is to contradict that, for the
        # eight days it takes "Last backup" to age out. The type name is kept so the email
        # says what happened rather than only that something did.
        _record_failure(f"{type(exc).__name__}: {exc}")
        raise ScheduledBackupFailed(str(exc)) from exc
    # Pruning is deliberately AFTER a successful write: a failing backup must never be the
    # thing that deletes the last good one.
    return ScheduledBackupResult(
        path=destination,
        byte_count=destination.stat().st_size,
        pruned=prune(destination.parent),
    )


def _require_headroom(directory: Path) -> None:
    """Raise unless tonight's archive fits without filling the volume.

    Sized from the LAST archive, which is the only honest estimate the instance has. On an
    instance that has never taken one there is nothing to measure and the run proceeds.
    """
    last = BackupRun.objects.order_by("-finished_at").first()
    expected = last.byte_count if last is not None else 0
    free = shutil.disk_usage(directory).free
    if expected and free < expected * HEADROOM_MULTIPLE:
        raise ScheduledBackupFailed(
            f"refusing tonight's backup: {free // 1024**3} GB free on the data volume and "
            f"the last archive was {expected // 1024**3} GB. Copy older archives off the box "
            "or grow the volume (docs/runbooks/backup-restore.md). Filling this volume would "
            "stop uploads and the database, which is worse than one missed night."
        )


def newest_archive_day(directory: Path | None = None) -> datetime.date | None:
    """The date of the newest archive the SCHEDULER wrote, or None.

    The health surface asks this rather than BackupRun, because a hand-run
    `backup_instance` writes a BackupRun row too -- so BackupRun cannot answer "is the
    NIGHTLY job working", which is the question the field exists for.
    """
    root = directory or Path(settings.BACKUP_ROOT)
    return max((day for day, _path in _archives(root)), default=None)


def prune(
    directory: Path, *, keep_daily: int = KEEP_DAILY, keep_weekly: int = KEEP_WEEKLY
) -> list[Path]:
    """Delete aged-out scheduled archives; return what was removed.

    Kept: the `keep_daily` most recent days, plus the newest archive of each of the
    `keep_weekly` most recent ISO weeks. Anything in the directory that this module did not
    name is invisible here — see ARCHIVE_PREFIX.
    """
    dated = sorted(_archives(directory), reverse=True)
    keep = {path for _, path in dated[:keep_daily]}
    newest_of_week: dict[tuple[int, int], Path] = {}
    for day, path in dated:
        calendar = day.isocalendar()
        newest_of_week.setdefault((calendar.year, calendar.week), path)
    for _week, path in sorted(newest_of_week.items(), reverse=True)[:keep_weekly]:
        keep.add(path)

    removed: list[Path] = []
    for _day, path in dated:
        if path in keep:
            continue
        try:
            path.unlink()
        except OSError:
            # A file we cannot delete is a disk to look at, not a reason to abandon the
            # backup that already succeeded.
            logger.exception("could not remove the aged-out backup %s", path.name)
            continue
        removed.append(path)
    return removed


def _archives(directory: Path) -> list[tuple[datetime.date, Path]]:
    """(day, path) for every archive this module wrote, by the date in its NAME.

    The name, not the mtime: a `docker compose cp` or a volume restore rewrites mtimes and
    would silently re-date the whole retention window.
    """
    found: list[tuple[datetime.date, Path]] = []
    for path in sorted(directory.glob(f"{ARCHIVE_PREFIX}*{ARCHIVE_SUFFIX}")):
        match = _ARCHIVE_NAME.match(path.name)
        if match is None:
            continue
        try:
            day = datetime.date(int(match[1]), int(match[2]), int(match[3]))
        except ValueError:
            continue  # `scheduled-2026-02-31.bak` is not a date and is not ours to delete
        found.append((day, path))
    return found


def _record_failure(error: str) -> None:
    """Write the failure down. Never masks the backup failure with a database one."""
    try:
        BackupFailure.objects.create(error=error[:500])
        keep = list(
            BackupFailure.objects.order_by("-occurred_at").values_list("pk", flat=True)[
                :KEEP_FAILURES
            ]
        )
        BackupFailure.objects.exclude(pk__in=keep).delete()
    except DatabaseError:  # pragma: no cover - the raise below is what the caller sees
        logger.exception("the scheduled backup failed AND the failure could not be recorded")
