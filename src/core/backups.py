"""Whole-instance backup and restore (S-704 instance half, S-802).

One archive captures the two stateful things: the database (a `pg_dump -Fc`
custom-format dump) and the media tree (MEDIA_ROOT). The dump runs with the
version-matched client the image already ships for the pre-flight backup
(TS-PG-6), as the migrator where that role's password is present (the operator's
documented command, in the web container) and otherwise as the runtime app role,
which ADR-004 already grants SELECT on every table — see `_dump_credentials`,
which exists so the worker can take the scheduled daily backup without being
handed DDL credentials it must never hold (TS-CO-3). Restore is
the inverse and is deliberately destructive, so it refuses to run against a
database that still has family data unless forced: a restore is for a fresh box
or a drill, never a casual overwrite.

Inside, the archive is a tar of two members plus a manifest — but it is
ENCRYPTED AT REST BY DEFAULT (S-802): `backup_instance` refuses to write
plaintext unless `--no-encrypt` is passed explicitly, and takes the passphrase
from `BACKYARD_BACKUP_PASSPHRASE` or `--passphrase-file`, never from argv. See
`backup_crypto.py` for the AES-256-GCM + scrypt construction.

This docstring used to say "Nothing here holds a key; at-rest encryption is the
operator's storage layer." Do not restore that sentence. It outlived the design
it described, and it is the precise claim a prior audit found a plaintext family
archive shipping under — a stale comment that reads as a deliberate decision is
how the wrong thing keeps getting justified.

TRUST BOUNDARY (#47 review MEDIUM): a restore archive is executed against the
database as the migrator (DDL) role, so restoring one is equivalent to handing
its author a shell on the box. Only ever restore an archive you produced and
kept custody of; never a third-party archive. The manifest is a shape check,
not authentication, so it does not make an untrusted archive safe.
"""

from __future__ import annotations

import datetime
import errno
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import IO

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import connection, models, transaction
from django.utils import timezone

from . import backup_passphrase
from .models import DigestSubscription, Invite, Member

MANIFEST_NAME = "backup-manifest.json"
DB_DUMP_NAME = "database.dump"
MEDIA_TAR_NAME = "media.tar.gz"
BACKUP_FORMAT = "backyard-instance-backup/1"

# The absolute ceiling on an extracted media tree, and the headroom kept free on the volume
# it lands on (S20). `filter="data"` covers path traversal; it says nothing about VOLUME, so
# a 40 GB tree inside a 40 MB gzip filled the disk of a box whose operator was already in
# trouble — a restore is the one command somebody runs when things have gone wrong, and the
# failure mode was a full /data with the old media tree already deleted.
#
# 200 GB is far above any real family archive (the small VM class this ships on tops out
# around 40 GB, issue 176) and far below a decompression bomb, so it is the backstop for the
# case where free space cannot be measured rather than the working limit. The working limit
# is free space minus the reserve: the restore also needs room for the database dump beside
# it, and a volume with literally zero bytes left is its own outage.
MAX_RESTORED_MEDIA_BYTES = 200 * 1024**3
RESTORE_FREE_SPACE_RESERVE_BYTES = 1024**3
# One member's ceiling. A single file larger than this is not a family photograph or a
# two-minute clip; it is either corruption or a bomb, and naming it separately means the
# refusal can say WHICH file rather than only "too big in total".
MAX_RESTORED_MEMBER_BYTES = 16 * 1024**3

# A nightly, unattended dump on a single-slot worker needs a wall-clock bound. Without one
# a hung pg_dump (a stalled connection, a partition mid-stream) holds the worker's ONE
# concurrency slot forever, which silently stops the digest, the health email, every
# transcode and every later backup -- the T-MON-1 silence the scheduler exists to break,
# caused by the scheduler. Generous enough for a real family archive on slow disks; the
# timeout is recorded and mailed like any other failure.
DUMP_TIMEOUT_SECONDS = 6 * 60 * 60


class BackupError(Exception):
    """A backup or restore step failed; the caller should surface it loudly."""


def _dsn() -> dict[str, str]:
    db = settings.DATABASES["default"]
    return {
        "host": str(db["HOST"]),
        "port": str(db["PORT"]),
        "name": str(db["NAME"]),
    }


def _migrator_env() -> dict[str, str]:
    """pg_restore runs as the migrator: a restore is DDL, and only that role has it.
    The password comes from the environment the operator runs the command in; it is
    never stored or logged."""
    password = os.environ.get("POSTGRES_MIGRATOR_PASSWORD")
    if not password:
        raise BackupError(
            "POSTGRES_MIGRATOR_PASSWORD is not set; run backup/restore in the "
            "migrator's environment (the documented runbook does)."
        )
    return _with_password(password)


def _dump_credentials() -> tuple[str, dict[str, str]]:
    """The role `pg_dump` connects as, and its environment. One function, two callers.

    The operator's documented backup runs in the WEB container, whose compose environment
    carries the migrator password, and it keeps using the migrator: it owns every table, so
    "can it read all of this" is not a question anyone has to re-answer.

    The scheduled daily backup (S-806, NB-1) runs on the WORKER, which deliberately holds no
    DDL credentials at all — compose never passes them and the entrypoint unsets them for
    every non-web role (TS-CO-3), because the worker is where ffmpeg runs on member-uploaded
    video and is therefore the last container that should hold a key to the schema. Handing
    it the migrator password to make a backup possible would trade the container-hardening
    story for a cron job.

    It does not need to. ADR-004's default privileges grant backyard_app SELECT on every
    table and sequence the migrator creates, which is the whole database, so the credential
    the worker ALREADY has can read everything pg_dump must read. The only thing in the way
    is the app role's 15s statement_timeout (TS-PG-5) — a guard for request-path queries that
    would kill a dump of any real archive — so the dump session lifts it explicitly rather
    than relying on pg_dump happening to set it for us.

    A role that cannot read something does not produce a quiet partial dump: pg_dump fails on
    "permission denied", the command raises, and the failure is recorded and mailed.
    """
    migrator = os.environ.get("POSTGRES_MIGRATOR_PASSWORD")
    if migrator:
        return "backyard_migrator", _with_password(migrator)
    app_user = os.environ.get("POSTGRES_USER")
    app_password = os.environ.get("POSTGRES_PASSWORD")
    if not app_user or not app_password:
        raise BackupError(
            "no database credentials in the environment: set POSTGRES_MIGRATOR_PASSWORD "
            "(the operator path, in the web container) or POSTGRES_USER/POSTGRES_PASSWORD "
            "(the runtime role, which is what the worker's scheduled backup uses)."
        )
    env = _with_password(app_password)
    env["PGOPTIONS"] = f"{env.get('PGOPTIONS', '')} -c statement_timeout=0".strip()
    return app_user, env


def _with_password(password: str) -> dict[str, str]:
    env = dict(os.environ)
    # The backup passphrase is not the database's business. Inheriting it widened its blast
    # radius to any child core dump or /proc/<pid>/environ read for no benefit at all. The
    # keyfile PATH goes too: it is not the secret, but it is a signpost to it, and pg_dump
    # has no more use for one than for the other.
    env.pop(backup_passphrase.ENV_VAR, None)
    env.pop(backup_passphrase.FILE_ENV_VAR, None)
    env["PGPASSWORD"] = password
    return env


def write_backup(destination: IO[bytes], *, staging_dir: Path | None = None) -> None:
    """Write a whole-instance backup archive into `destination`.

    `staging_dir` is where the pg_dump and the media tar are built — a full copy of the
    instance, twice over, before either reaches `destination`. The caller passes the
    directory the archive itself lands in, because that is the volume whose free space was
    measured; the default (TMPDIR) is the container's writable layer, which the nightly
    run's headroom guard does not look at and which is not where the operator grew the disk.
    """
    dsn = _dsn()
    dump_user, dump_env = _dump_credentials()
    with tempfile.TemporaryDirectory(dir=staging_dir) as workdir:
        dump_path = Path(workdir) / DB_DUMP_NAME
        try:
            result = subprocess.run(  # noqa: S603  # fixed argv, never a shell
                [
                    "pg_dump",
                    "-h",
                    dsn["host"],
                    "-p",
                    dsn["port"],
                    "-U",
                    dump_user,
                    "-Fc",
                    "-f",
                    str(dump_path),
                    dsn["name"],
                ],
                env=dump_env,
                capture_output=True,
                text=True,
                timeout=DUMP_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise BackupError(
                f"pg_dump did not finish within {DUMP_TIMEOUT_SECONDS // 3600} hours and was "
                "killed. The worker runs one job at a time, so a dump that hangs takes the "
                "digest, the health email and every transcode down with it."
            ) from exc
        if result.returncode != 0:
            raise BackupError(f"pg_dump failed: {result.stderr.strip()[:300]}")

        media_root = Path(settings.MEDIA_ROOT)
        media_path = Path(workdir) / MEDIA_TAR_NAME
        with tarfile.open(media_path, "w:gz") as media_tar:
            if media_root.exists():
                media_tar.add(media_root, arcname="media")

        manifest = {
            "format": BACKUP_FORMAT,
            "created_at": _now_iso(),
            "database": dsn["name"],
            "members": [DB_DUMP_NAME, MEDIA_TAR_NAME],
        }
        with tarfile.open(fileobj=destination, mode="w") as archive:
            _add_bytes(archive, MANIFEST_NAME, json.dumps(manifest, indent=2).encode())
            archive.add(dump_path, arcname=DB_DUMP_NAME)
            archive.add(media_path, arcname=MEDIA_TAR_NAME)


def _restore_workdir() -> tempfile.TemporaryDirectory[str]:
    """A scratch directory on the SAME filesystem as MEDIA_ROOT where possible.

    The media tree is promoted into place with rename(2), which cannot cross a filesystem
    boundary — and in the container the default temp dir is on the image root while
    MEDIA_ROOT is a mounted volume. Staging beside MEDIA_ROOT keeps the promote atomic and
    avoids copying a family's entire media library twice.
    """
    parent = Path(settings.MEDIA_ROOT).parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=parent, prefix=".restore-")
    except OSError:
        # Unwritable or missing: fall back to the default location. The cross-device
        # fallback in _restore_media covers the promote.
        return tempfile.TemporaryDirectory()


def restore_backup(source: IO[bytes], *, force: bool) -> dict[str, int]:
    """Restore an instance from a backup archive. DESTRUCTIVE: it clean-restores
    the database (dropping existing objects) and replaces the media tree. Refuses
    a database that still holds members unless `force` is set (a fresh box or a
    drill scratch DB has none). Ends with a forced security-replay (TM-7) and returns
    its summary, so the restore can never silently resurrect a revoked bearer credential."""
    if not force and _has_members():
        raise BackupError(
            "Refusing to restore over a database that still has members. This is "
            "for a fresh instance or a drill; pass force=True to override."
        )
    dsn = _dsn()
    with _restore_workdir() as workdir:
        with tarfile.open(fileobj=source, mode="r") as archive:
            _verify_manifest(archive)
            archive.extract(DB_DUMP_NAME, path=workdir, filter="data")
            archive.extract(MEDIA_TAR_NAME, path=workdir, filter="data")

        # The media ceilings are checked HERE, before pg_restore, and the order is the
        # whole point (Copilot review of the hardening PR). `pg_restore --clean` drops and
        # rebuilds every table, so a refusal raised from inside `_restore_media` would have
        # come AFTER the family's database had already been replaced — while saying
        # "Nothing has been written", which would be false at the moment it matters most.
        # Reading the tar's headers costs nothing and answers before anything is destroyed.
        _refuse_an_oversized_media_archive(Path(workdir) / MEDIA_TAR_NAME, Path(workdir))

        result = subprocess.run(  # noqa: S603  # fixed argv, never a shell
            [
                "pg_restore",
                "-h",
                dsn["host"],
                "-p",
                dsn["port"],
                "-U",
                "backyard_migrator",
                "--clean",
                "--if-exists",
                "--no-owner",
                "-d",
                dsn["name"],
                str(Path(workdir) / DB_DUMP_NAME),
            ],
            env=_migrator_env(),
            capture_output=True,
            text=True,
        )
        # pg_restore --clean warns on objects that did not pre-exist; those are
        # not failures. Only a nonzero exit with a real error stops the restore.
        if result.returncode != 0 and "error:" in result.stderr.lower():
            raise BackupError(f"pg_restore failed: {result.stderr.strip()[:300]}")

        _restore_media(Path(workdir) / MEDIA_TAR_NAME, Path(workdir))
    # The DB and media are back; now the security half, so a restore is never a way to
    # replay a credential the family already revoked (TM-7 / T-OP-G5). A failure here leaves
    # a fully-restored DB with LIVE credentials, so it is surfaced loudly, not swallowed.
    try:
        return _forced_security_replay()
    except Exception as exc:  # noqa: BLE001  # any replay failure must be loud + actionable
        raise BackupError(
            "DATABASE RESTORED, but the forced security-replay did NOT complete: "
            f"{exc}. Bearer credentials from the backup may be LIVE — rotate them now by "
            "hand (regenerate elder links, flush sessions, revoke invites)."
        ) from exc


def revoke_every_credential() -> dict[str, int]:
    """Kill every bearer credential on the instance. ONE implementation, two callers.

    A restore calls it so it cannot resurrect a revoked token (TM-7 / T-OP-G5); a
    decommission calls it so a shut-down instance's printed QRs and bookmarked elder links
    stop working before the volumes go (S-804). A second implementation for the second
    caller is exactly how one of them would come to miss a credential class.
    """
    return _forced_security_replay()


def _forced_security_replay() -> dict[str, int]:
    """The TM-7 / T-OP-G5 forced security-replay: a restore ends here so it can never
    silently resurrect a revoked token or an expelled ex-partner's live link. It kills every
    bearer-credential class the revocation drill enforces (test_revocation_drill's
    _ALL_CAPABILITY_CLASSES), by the same mechanisms the per-member revocation registry uses:

    - Rotates the token-signing material — bumps Member.token_generation for EVERY member —
      which invalidates every generation-anchored credential the backup carried at once
      (elder token links, digest deep-links, reply-by-email addresses; each resolve checks
      minted_generation == member.token_generation, so one bump kills them all).
    - Flushes every session (the elder and web sessions carry no generation-checked row).
    - Clears the digest confirm/unsubscribe tokens — the ONE bearer class that is not
      generation-anchored (digesting._by_token matches the digest only, so the bump would
      miss them); the columns are cleared like revocation._cancel_digest_subscription, but
      WITHOUT disabling the subscription (a preference, not a bearer credential — a confirmed
      member's opt-in survives a restore; a removed member's return is the checklist's job).
    - Voids every outstanding invite (a restored /join link is a replayable bearer credential).

    All of it is re-issuable: the admin re-provisions only members who should still have
    access and re-issues invites as needed. One transaction, so a partial restore never
    leaves some credentials live. The drift-guard test asserts this kills every registered
    class, so a new credential class cannot be forgotten here.

    Residual (named in the operator checklist, T-OP-G5): a restore cannot know what happened
    AFTER the backup, so member removals and content deletions that postdate it still come
    back. The checklist is the only control there and depends on the admin reading it.
    """
    with transaction.atomic():
        members = Member.objects.update(token_generation=models.F("token_generation") + 1)
        sessions = Session.objects.all().delete()[0]
        invites = Invite.objects.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        # nosec B106 on both calls: an empty-string digest is the ABSENCE of a credential.
        # This clears the emailed capabilities, it does not hardcode one. Scoped to B106 so
        # it suppresses one rule rather than everything on the line.
        digest_tokens = DigestSubscription.objects.exclude(  # nosec B106
            confirm_token_digest="", unsubscribe_token_digest=""
        ).update(confirm_token_digest="", unsubscribe_token_digest="")  # nosec B106
    return {
        "members_rotated": members,
        "sessions_flushed": sessions,
        "invites_voided": invites,
        "digest_tokens_cleared": digest_tokens,
    }


def _refuse_an_oversized_media_archive(media_tar_path: Path, destination: Path) -> None:
    """Read the media archive's headers and refuse it if it will not fit (S20).

    Split from the extraction so it can run BEFORE `pg_restore`, which is the only
    ordering under which its refusal can honestly say nothing has been written: the
    restore's first destructive act is `pg_restore --clean`, not the extraction.

    The archive's shape is checked here too — every member must be under `media/` — so the
    traversal refusal (#47 review HIGH) also lands before the database is touched.
    """
    with tarfile.open(media_tar_path, "r:gz") as media_tar:
        members = media_tar.getmembers()
    for member in members:
        top = Path(member.name).parts[0] if member.name else ""
        if top != "media":
            raise BackupError(f"unexpected member in media archive: {member.name!r}")
    _refuse_an_oversized_extraction(members, destination)


def _refuse_an_oversized_extraction(members: list[tarfile.TarInfo], destination: Path) -> None:
    """Refuse, BEFORE a byte is written, a media archive that will not fit (S20).

    Three ceilings, and the loud refusal happens before `extractall` rather than after,
    because the only thing worse than a restore that fails is one that fails halfway
    across a volume that now holds neither the old media tree nor a whole new one.

    1. FREE SPACE on the volume the tree actually lands on, minus a reserve. This is the
       real limit: on the VM class this product ships on, the disk is the constraint long
       before any absolute number is.
    2. An absolute total (`MAX_RESTORED_MEDIA_BYTES`), which is the backstop for a box
       whose free space cannot be measured at all.
    3. A PER-MEMBER ceiling, so the refusal can name the one file that is wrong instead of
       reporting a total that tells the operator nothing about what to look at.

    `TarInfo.size` is the header's claim, not a measurement, and a crafted header could
    understate it. That is bounded rather than trusted: the archive is the operator's own
    (the module docstring's trust boundary — restoring one is equivalent to handing its
    author a shell), and the free-space check means an understated header fails on write
    with ENOSPC exactly as it would today. What this closes is the honest-header case,
    which is the one that actually happens: a real family archive that has outgrown the
    box it is being restored onto, and a gzip bomb, both of which announce their size.
    """
    total = 0
    for member in members:
        if not member.isreg():
            continue
        if member.size > MAX_RESTORED_MEMBER_BYTES:
            raise BackupError(
                f"refusing to restore: {member.name!r} claims "
                f"{member.size / 1024**3:.1f} GB, over the "
                f"{MAX_RESTORED_MEMBER_BYTES / 1024**3:.0f} GB per-file ceiling. "
                "Nothing has been written."
            )
        total += member.size

    if total > MAX_RESTORED_MEDIA_BYTES:
        raise BackupError(
            f"refusing to restore: the media archive expands to "
            f"{total / 1024**3:.1f} GB, over the "
            f"{MAX_RESTORED_MEDIA_BYTES / 1024**3:.0f} GB ceiling. Nothing has been written."
        )

    try:
        usage = shutil.disk_usage(destination)
    except OSError:  # pragma: no cover - the staging dir was just created
        return
    headroom = usage.free - RESTORE_FREE_SPACE_RESERVE_BYTES
    if total > headroom:
        raise BackupError(
            f"refusing to restore: the media archive expands to "
            f"{total / 1024**3:.1f} GB and only {max(headroom, 0) / 1024**3:.1f} GB is "
            f"usable on this volume (keeping {RESTORE_FREE_SPACE_RESERVE_BYTES / 1024**3:.0f} "
            "GB free). Nothing has been written; make room, or restore onto a bigger disk."
        )


def _restore_media(media_tar_path: Path, workdir: Path) -> None:
    """Replace the media tree from the backup's media.tar.gz.

    Extraction is bounded to a throwaway staging dir inside `workdir`, and only
    the archive's own `media/` subtree is promoted into MEDIA_ROOT (#47 review
    HIGH). Extracting straight into MEDIA_ROOT.parent (/data) would let a member
    literally named `secret_key` land at /data/secret_key and silently overwrite
    the Django SECRET_KEY: filter="data" blocks ../ traversal but not a legal
    sibling child of the destination, and /data holds the master key next door.
    """
    media_root = Path(settings.MEDIA_ROOT)
    staging = workdir / "media_staging"
    staging.mkdir()
    # Re-asked immediately before the extraction as well as before pg_restore. Not
    # belt-and-braces for its own sake: this function is reachable on its own, and the
    # check that protects the volume belongs next to the write that fills it.
    _refuse_an_oversized_media_archive(media_tar_path, workdir)
    with tarfile.open(media_tar_path, "r:gz") as media_tar:
        media_tar.extractall(path=staging, filter="data")  # destination is the throwaway staging
    restored = staging / "media"
    if not restored.exists():
        # An empty media tree is legal (a new instance has no photos yet).
        media_root.mkdir(parents=True, exist_ok=True)
        return
    if media_root.exists():
        shutil.rmtree(media_root)
    media_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        restored.replace(media_root)  # only the media/ subtree lands in place
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        # The staging dir landed on a different filesystem from MEDIA_ROOT, which is the
        # NORMAL case in the container: the default temp dir is on the image's root fs
        # while MEDIA_ROOT is a mounted volume, and rename(2) cannot cross that boundary.
        # This failed every containerised restore with "Invalid cross-device link" AFTER
        # the old media tree had already been removed. restore_backup now stages beside
        # MEDIA_ROOT so the atomic path is the one normally taken; this is the fallback
        # for an operator who has pointed TMPDIR somewhere else again.
        shutil.move(str(restored), str(media_root))


def _has_members() -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'core_member')"
        )
        if not cursor.fetchone()[0]:
            return False
        cursor.execute("SELECT EXISTS (SELECT 1 FROM core_member)")
        return bool(cursor.fetchone()[0])


def _verify_manifest(archive: tarfile.TarFile) -> None:
    try:
        member = archive.extractfile(MANIFEST_NAME)
    except KeyError as exc:
        raise BackupError("archive has no backup manifest; not a Backyard backup") from exc
    if member is None:
        raise BackupError("archive manifest is unreadable")
    try:
        manifest = json.loads(member.read())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BackupError("archive manifest is not valid JSON") from exc
    if manifest.get("format") != BACKUP_FORMAT:
        raise BackupError(f"unexpected backup format: {manifest.get('format')!r}")


def _add_bytes(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    import io

    archive.addfile(info, io.BytesIO(data))


def _now_iso() -> str:
    # Backups are operator-run, not request-scoped; a wall-clock stamp is correct.
    return datetime.datetime.now(tz=datetime.UTC).isoformat()
