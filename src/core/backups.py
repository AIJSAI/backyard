"""Whole-instance backup and restore (S-704 instance half, S-802).

One archive captures the two stateful things: the database (a `pg_dump -Fc`
custom-format dump) and the media tree (MEDIA_ROOT). The backup is taken as the
migrator role, the only one that can read every table, with the version-matched
client the image already ships for the pre-flight backup (TS-PG-6). Restore is
the inverse and is deliberately destructive, so it refuses to run against a
database that still has family data unless forced: a restore is for a fresh box
or a drill, never a casual overwrite.

The archive is a plain tar of two members plus a manifest, so an operator can
open it, verify it, and encrypt or ship it with their own tools. Nothing here
holds a key; at-rest encryption is the operator's storage layer (documented in
the runbook), kept out of the app so the app never holds long-lived key
material (the T-EMAIL-5 spirit: the fewer secrets the app custodies, the better).

TRUST BOUNDARY (#47 review MEDIUM): a restore archive is executed against the
database as the migrator (DDL) role, so restoring one is equivalent to handing
its author a shell on the box. Only ever restore an archive you produced and
kept custody of; never a third-party archive. The manifest is a shape check,
not authentication, so it does not make an untrusted archive safe.
"""

from __future__ import annotations

import datetime
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

from .models import Invite, Member

MANIFEST_NAME = "backup-manifest.json"
DB_DUMP_NAME = "database.dump"
MEDIA_TAR_NAME = "media.tar.gz"
BACKUP_FORMAT = "backyard-instance-backup/1"


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
    """pg_dump/pg_restore run as the migrator (reads every table). The password
    comes from the environment the operator runs the command in; it is never
    stored or logged."""
    password = os.environ.get("POSTGRES_MIGRATOR_PASSWORD")
    if not password:
        raise BackupError(
            "POSTGRES_MIGRATOR_PASSWORD is not set; run backup/restore in the "
            "migrator's environment (the documented runbook does)."
        )
    env = dict(os.environ)
    env["PGPASSWORD"] = password
    return env


def write_backup(destination: IO[bytes]) -> None:
    """Write a whole-instance backup archive into `destination`."""
    dsn = _dsn()
    with tempfile.TemporaryDirectory() as workdir:
        dump_path = Path(workdir) / DB_DUMP_NAME
        result = subprocess.run(  # noqa: S603  # fixed argv, never a shell
            [
                "pg_dump",
                "-h",
                dsn["host"],
                "-p",
                dsn["port"],
                "-U",
                "backyard_migrator",
                "-Fc",
                "-f",
                str(dump_path),
                dsn["name"],
            ],
            env=_migrator_env(),
            capture_output=True,
            text=True,
        )
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
    with tempfile.TemporaryDirectory() as workdir:
        with tarfile.open(fileobj=source, mode="r") as archive:
            _verify_manifest(archive)
            archive.extract(DB_DUMP_NAME, path=workdir, filter="data")
            archive.extract(MEDIA_TAR_NAME, path=workdir, filter="data")

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
    # replay a credential the family already revoked (TM-7 / T-OP-G5).
    return _forced_security_replay()


def _forced_security_replay() -> dict[str, int]:
    """The TM-7 / T-OP-G5 forced security-replay: a restore ends here so it can never
    silently resurrect a revoked token or an expelled ex-partner's live link.

    It rotates the token-signing material — bumps Member.token_generation for EVERY member,
    which invalidates every generation-anchored bearer credential the backup carried at
    once (elder token links, digest deep-links, reply-by-email addresses; each resolve
    checks minted_generation == member.token_generation, so one bump kills them all) —
    flushes every session (the elder and web sessions that carry no generation-checked
    row), and voids every outstanding invite (a restored /join link is a replayable bearer
    credential too). All of it is re-issuable: the admin re-provisions only the members who
    should still have access and re-issues invites as needed. One transaction, so a partial
    restore never leaves some credentials live.

    Residual (named in the operator checklist, T-OP-G5): a restore cannot know what happened
    AFTER the backup, so member removals and content deletions that postdate it still come
    back. The checklist is the only control there and depends on the admin reading it.
    """
    with transaction.atomic():
        members = Member.objects.update(token_generation=models.F("token_generation") + 1)
        sessions = Session.objects.all().delete()[0]
        invites = Invite.objects.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
    return {"members_rotated": members, "sessions_flushed": sessions, "invites_voided": invites}


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
    with tarfile.open(media_tar_path, "r:gz") as media_tar:
        for member in media_tar.getmembers():
            top = Path(member.name).parts[0] if member.name else ""
            if top != "media":
                raise BackupError(f"unexpected member in media archive: {member.name!r}")
        media_tar.extractall(path=staging, filter="data")  # destination is the throwaway staging
    restored = staging / "media"
    if not restored.exists():
        # An empty media tree is legal (a new instance has no photos yet).
        media_root.mkdir(parents=True, exist_ok=True)
        return
    if media_root.exists():
        shutil.rmtree(media_root)
    media_root.parent.mkdir(parents=True, exist_ok=True)
    restored.replace(media_root)  # only the media/ subtree lands in place


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
