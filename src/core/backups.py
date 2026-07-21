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
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import IO

from django.conf import settings
from django.db import connection

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


def restore_backup(source: IO[bytes], *, force: bool) -> None:
    """Restore an instance from a backup archive. DESTRUCTIVE: it clean-restores
    the database (dropping existing objects) and replaces the media tree. Refuses
    a database that still holds members unless `force` is set (a fresh box or a
    drill scratch DB has none)."""
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

        media_root = Path(settings.MEDIA_ROOT)
        media_root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(Path(workdir) / MEDIA_TAR_NAME, "r:gz") as media_tar:
            extract_root = media_root.parent
            media_tar.extractall(path=extract_root, filter="data")


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
    manifest = json.loads(member.read())
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
