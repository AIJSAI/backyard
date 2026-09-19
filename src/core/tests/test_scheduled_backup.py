"""The nightly backup (S-802, S-806, threat row T-MON-1).

`backup_instance` existed and nothing ran it, which is the version of "a dead backup cron
goes unnoticed for months" where the cron was never born. These hold the three properties
that make the scheduled run trustworthy rather than merely present:

* it REFUSES to write plaintext — the encrypt-by-default rule is not relaxed for automation,
  which is exactly where a "just this once" would have become every night forever;
* a failure is RECORDED before it is raised, because the reason has to reach the weekly
  email; a log line on a box nobody logs into is not a notification;
* retention only ever deletes files the scheduler itself named. It shares a directory with
  the operator's own archives and the entrypoint's pre-flight dumps, and the whole point of
  a backup directory is that nothing surprising deletes anything in it.

The dump itself is stubbed here (no Postgres client on a bare test runner, and the real
round trip is CI's compose probe); what runs for real is the orchestration.
"""

from __future__ import annotations

import datetime
import subprocess
import tempfile
from collections import namedtuple
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.utils import timezone

from core import backup_passphrase, scheduled_backup
from core.models import BackupFailure, BackupRun

pytestmark = pytest.mark.django_db

_Usage = namedtuple("_Usage", "total used free")

# Reuses a value the credential guard and .gitleaks.toml already know is synthetic,
# rather than adding a new credential-shaped literal to this repository for a test.
_PASSPHRASE = "a-fine-passphrase-1234"


@pytest.fixture(autouse=True)
def _backup_environment(monkeypatch: Any, settings: Any, tmp_path: Path) -> None:
    """A passphrase, a migrator password and a stub pg_dump: the everyday healthy case."""
    monkeypatch.setenv(backup_passphrase.ENV_VAR, _PASSPHRASE)
    monkeypatch.delenv(backup_passphrase.FILE_ENV_VAR, raising=False)
    monkeypatch.setenv("POSTGRES_MIGRATOR_PASSWORD", "a-drill-migrator-passphrase-1")
    settings.MEDIA_ROOT = str(tmp_path / "media")

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[0] == "pg_dump":
            Path(argv[argv.index("-f") + 1]).write_bytes(b"PGDMP-stub-dump")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("core.backups.subprocess.run", fake_run)


def _touch(directory: Path, name: str, *, recorded: bool = True) -> Path:
    """An archive on disk, and by default the row saying this scheduler wrote it.

    Retention deletes the INTERSECTION of the two (#166 review): the name says which day an
    archive is for, and the row says whose it is. `recorded=False` is a file that merely
    looks like ours.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"an archive")
    if recorded:
        BackupRun.objects.create(
            byte_count=path.stat().st_size,
            encrypted=True,
            source=BackupRun.Source.SCHEDULED,
            archive_name=name,
        )
    return path


# ---------------------------------------------------------------- the nightly run


def test_the_nightly_run_writes_an_encrypted_archive_and_records_it() -> None:
    result = scheduled_backup.run()

    assert result.path.exists()
    assert result.path.name.startswith("scheduled-")
    # backup_crypto's magic: the archive on disk is ciphertext, not a tar anybody can open.
    assert result.path.read_bytes()[:14] == b"BACKYARD-ENC/1"
    # And the run is recorded, so "last backup age" can be answered at all.
    run = BackupRun.objects.get()
    assert run.encrypted
    # With its PROVENANCE, which is what lets the health surface tell this apart from a
    # backup somebody took by hand, and what lets retention know the file is its own.
    assert run.source == BackupRun.Source.SCHEDULED
    assert run.archive_name == result.path.name
    assert not BackupFailure.objects.exists()


def test_it_refuses_to_write_plaintext_when_the_passphrase_is_unset(monkeypatch: Any) -> None:
    """The automation does not get a relaxed version of the S-802 rule.

    Without this the nightly job is the one caller with a standing reason to fall back to
    plaintext, and it would write the entire family database in the clear onto the same
    volume every night, which is verbatim T-BACKUP-1.
    """
    monkeypatch.delenv("BACKYARD_BACKUP_PASSPHRASE", raising=False)

    with pytest.raises(scheduled_backup.ScheduledBackupFailed):
        scheduled_backup.run()

    day = timezone.localtime(timezone.now()).date()
    assert not scheduled_backup.archive_path(day).exists()  # nothing at all, not a plaintext one
    assert not BackupRun.objects.exists()


def test_the_nightly_run_reads_the_keyfile_both_guides_recommend(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """The RECOMMENDED configuration has to be one that works.

    Both runbooks tell the operator to mount a 0600 key and leave the env var unset, because
    the env value is visible to `docker inspect`. `backup_instance` takes a keyfile only as a
    command-line flag and a periodic task is nobody's command line, so the resolver
    (core/backup_passphrase) reads the configured path for every caller — see
    test_backup_passphrase.py for the rule, this for the nightly run using it.
    """
    monkeypatch.delenv(backup_passphrase.ENV_VAR, raising=False)
    keyfile = tmp_path / "backyard.key"
    keyfile.write_text(_PASSPHRASE, encoding="utf-8")
    keyfile.chmod(0o600)
    monkeypatch.setenv(backup_passphrase.FILE_ENV_VAR, str(keyfile))

    result = scheduled_backup.run()

    assert result.path.read_bytes()[:14] == b"BACKYARD-ENC/1"
    assert not BackupFailure.objects.exists()


def test_a_failure_is_recorded_with_its_reason_before_it_is_raised(monkeypatch: Any) -> None:
    def failing_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="connection refused")

    monkeypatch.setattr("core.backups.subprocess.run", failing_run)

    with pytest.raises(scheduled_backup.ScheduledBackupFailed):
        scheduled_backup.run()

    failure = BackupFailure.objects.get()
    assert "pg_dump failed" in failure.error  # the reason, not just the fact


def test_an_unforeseen_failure_is_recorded_too(monkeypatch: Any) -> None:
    """Not every failure is a CommandError or an OSError. One that is neither must still
    reach the weekly email, or the surface reports 'no failures recorded' for eight days."""

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("something nobody predicted")

    monkeypatch.setattr("core.scheduled_backup.call_command", boom)

    with pytest.raises(scheduled_backup.ScheduledBackupFailed):
        scheduled_backup.run()

    assert "something nobody predicted" in BackupFailure.objects.get().error


def test_it_refuses_a_night_that_would_fill_the_volume(monkeypatch: Any) -> None:
    """The archives sit on the same volume as the only copy of the family's photographs.

    Writing until ENOSPC there stops uploads and, by default, Postgres too — which is worse
    than one missed night. The refusal is recorded, mailed and visible at /healthz like any
    other failure, so it reads as "grow the disk" rather than as a silent stop.
    """
    scheduled_backup.run()  # tonight's estimate comes from the last archive, so make one
    last = BackupRun.objects.get()
    monkeypatch.setattr(
        "core.scheduled_backup.shutil.disk_usage",
        lambda path: _Usage(100, 99, last.byte_count),  # room for one, not for one plus staging
    )

    with pytest.raises(scheduled_backup.ScheduledBackupFailed, match="refusing tonight's backup"):
        scheduled_backup.run()

    # Recorded verbatim, not wrapped in its own class name: this sentence is written to be
    # read by the operator in the weekly email.
    assert BackupFailure.objects.get().error.startswith("refusing tonight's backup")


def test_every_staged_copy_lands_on_the_volume_the_guard_measured(monkeypatch: Any) -> None:
    """The guard measures BACKUP_ROOT; a run that stages elsewhere is measured nowhere.

    A run makes two more full copies of the instance before the archive exists — the
    pg_dump plus the media tar, and the single tar built from them — and both used to go to
    TMPDIR, which in the container is the image's writable layer rather than the mounted
    volume the operator grew. On the common single-disk host the numbers coincide and it
    reads fine; on the second-volume host settings.py explicitly contemplates, the guard
    reserved space on one disk while the run filled another.

    Probed by pointing TMPDIR at a directory that does not exist: staging there fails
    loudly, so a run that still succeeds is a run that staged beside the archive.
    """
    nowhere = Path(settings.MEDIA_ROOT).parent / "a-tmpdir-that-does-not-exist"
    monkeypatch.setattr(tempfile, "tempdir", str(nowhere))

    result = scheduled_backup.run()

    assert result.path.read_bytes()[:14] == b"BACKYARD-ENC/1"
    assert not nowhere.exists(), "something still staged in TMPDIR"


def test_the_headroom_guard_refuses_on_the_archives_own_volume(monkeypatch: Any) -> None:
    """The refusal, and the directory it asked about. Both halves matter: a guard that
    refuses using some OTHER filesystem's free space is a guard that fires on a healthy
    instance and stays quiet on the one that is about to ENOSPC mid-archive."""
    scheduled_backup.run()  # tonight's estimate comes from the last archive, so make one
    last = BackupRun.objects.get()
    measured: list[Path] = []

    def usage(path: Path) -> Any:
        measured.append(Path(path))
        return _Usage(100, 99, last.byte_count)  # room for one copy, not for two

    monkeypatch.setattr("core.scheduled_backup.shutil.disk_usage", usage)

    with pytest.raises(scheduled_backup.ScheduledBackupFailed, match="refusing tonight's backup"):
        scheduled_backup.run()

    assert measured == [Path(settings.BACKUP_ROOT)]


def test_the_headroom_guard_never_blocks_the_first_backup_an_instance_takes(
    monkeypatch: Any,
) -> None:
    """The dangerous direction. An instance that has never taken an archive has nothing to
    size one from, and a guard that guessed would refuse the backup that matters most."""
    monkeypatch.setattr("core.scheduled_backup.shutil.disk_usage", lambda path: _Usage(100, 99, 1))

    assert scheduled_backup.run().path.exists()


def test_recorded_failures_do_not_grow_without_bound(monkeypatch: Any) -> None:
    """An instance that has been failing for a year should not carry a year of rows."""
    for index in range(scheduled_backup.KEEP_FAILURES + 5):
        scheduled_backup._record_failure(f"failure {index}")

    assert BackupFailure.objects.count() == scheduled_backup.KEEP_FAILURES
    newest = BackupFailure.objects.order_by("-occurred_at").first()
    assert newest is not None and newest.error.startswith("failure ")


def test_a_rerun_on_the_same_day_replaces_rather_than_accumulates() -> None:
    first = scheduled_backup.run()
    second = scheduled_backup.run()

    assert first.path == second.path
    archives = list(Path(second.path.parent).glob("scheduled-*.bak"))
    assert len(archives) == 1


# ---------------------------------------------------------------- retention


def test_retention_keeps_the_recent_days_and_one_archive_per_older_week(tmp_path: Path) -> None:
    directory = tmp_path / "backups"
    # Ninety consecutive days, which is well past both windows.
    start = datetime.date(2026, 6, 1)
    for offset in range(90):
        day = start + datetime.timedelta(days=offset)
        _touch(directory, f"scheduled-{day.isoformat()}.bak")

    removed = scheduled_backup.prune(directory)

    kept = sorted(path.name for path in directory.glob("scheduled-*.bak"))
    assert removed, "ninety daily archives and nothing was aged out"
    # The 14 most recent days survive in full.
    newest = start + datetime.timedelta(days=89)
    for offset in range(scheduled_backup.KEEP_DAILY):
        day = newest - datetime.timedelta(days=offset)
        assert f"scheduled-{day.isoformat()}.bak" in kept
    # And the older survivors are one per ISO week, never two.
    weeks = [
        datetime.date.fromisoformat(name[len("scheduled-") : -len(".bak")]).isocalendar()[:2]
        for name in kept
    ]
    older_weeks = weeks[: -scheduled_backup.KEEP_DAILY]
    assert len(older_weeks) == len(set(older_weeks)), f"more than one archive kept per week: {kept}"
    # Two windows, one overlapping the other: fourteen days plus eight weekly slots.
    assert len(kept) <= scheduled_backup.KEEP_DAILY + scheduled_backup.KEEP_WEEKLY


def test_retention_never_touches_a_file_it_did_not_write(tmp_path: Path) -> None:
    """The dangerous half. This directory holds the operator's own archives (the runbook's
    `backup-YYYY-MM-DD.bak`) and the entrypoint's pre-flight dumps, and a retention sweep
    that treated the whole directory as its own would delete a backup somebody took by hand
    the day before they needed it."""
    directory = tmp_path / "backups"
    strangers = [
        _touch(directory, "backup-2020-01-01.bak", recorded=False),  # an operator's own
        _touch(directory, "preflight-20200101120000.dump.enc", recorded=False),  # entrypoint's
        _touch(directory, "scheduled-not-a-date.bak", recorded=False),  # prefix, not our shape
        _touch(directory, "scheduled-2026-02-31.bak", recorded=False),  # shape, not a real date
        # Our exact shape, a perfectly real date, aged well past both windows — and this
        # scheduler never wrote it (#166 review). An archive restored from another box, or
        # copied in to look at, is not a deletion candidate on the day it ages out.
        _touch(directory, "scheduled-2020-01-01.bak", recorded=False),
    ]
    for offset in range(40):
        day = datetime.date(2026, 6, 1) + datetime.timedelta(days=offset)
        _touch(directory, f"scheduled-{day.isoformat()}.bak")

    removed = scheduled_backup.prune(directory)

    assert removed, "the probe is vacuous if nothing was deleted at all"
    for stranger in strangers:
        assert stranger.exists(), f"retention deleted {stranger.name}, which it did not write"


def test_retention_is_quiet_on_a_directory_with_nothing_in_it(tmp_path: Path) -> None:
    assert scheduled_backup.prune(tmp_path / "never-created") == []
