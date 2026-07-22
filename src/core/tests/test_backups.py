"""Whole-instance backup and restore (S-704 instance half, S-802).

The real pg_dump/pg_restore round-trip is the live drill on the compose stack
(where the postgres client ships); these unit tests hold the orchestration and
the safety guards without depending on the host having pg tools: the archive
carries the manifest plus the db dump plus the media tree, restore verifies the
manifest and refuses a non-Backyard archive, and the destructive restore refuses
a database that still has members unless forced.
"""

from __future__ import annotations

import io
import json
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session

from core import backups, elder_tokens, invites
from core.models import Invite, Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db

_MIGRATOR_PW = "a-drill-migrator-passphrase-1"


@pytest.fixture(autouse=True)
def _migrator_env(monkeypatch: Any) -> None:
    monkeypatch.setenv("POSTGRES_MIGRATOR_PASSWORD", _MIGRATOR_PW)


@pytest.fixture
def fake_pg(monkeypatch: Any) -> None:
    """Replace pg_dump/pg_restore with a stub: pg_dump writes a placeholder dump
    file, pg_restore is a no-op success. The tar assembly and guards run for
    real."""

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[0] == "pg_dump":
            out_path = Path(argv[argv.index("-f") + 1])
            out_path.write_bytes(b"PGDMP-stub-dump")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("core.backups.subprocess.run", fake_run)


def test_backup_archive_has_manifest_db_and_media(
    fake_pg: None, settings: Any, tmp_path: Path
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    (media / "photo.jpg").write_bytes(b"a photo")
    settings.MEDIA_ROOT = str(media)

    buffer = io.BytesIO()
    backups.write_backup(buffer)
    buffer.seek(0)

    with tarfile.open(fileobj=buffer, mode="r") as archive:
        names = set(archive.getnames())
        assert {"backup-manifest.json", "database.dump", "media.tar.gz"} <= names
        manifest_member = archive.extractfile("backup-manifest.json")
        assert manifest_member is not None
        manifest = json.loads(manifest_member.read())
        assert manifest["format"] == backups.BACKUP_FORMAT
        # The media tree is really inside the media tar.
        media_member = archive.extractfile("media.tar.gz")
        assert media_member is not None
        with tarfile.open(fileobj=io.BytesIO(media_member.read()), mode="r:gz") as media_tar:
            assert any(name.endswith("photo.jpg") for name in media_tar.getnames())


def test_backup_fails_loudly_when_pg_dump_fails(
    monkeypatch: Any, settings: Any, tmp_path: Path
) -> None:
    settings.MEDIA_ROOT = str(tmp_path / "media")

    def failing_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="connection refused")

    monkeypatch.setattr("core.backups.subprocess.run", failing_run)
    with pytest.raises(backups.BackupError, match="pg_dump failed"):
        backups.write_backup(io.BytesIO())


def test_backup_requires_the_migrator_password(
    monkeypatch: Any, settings: Any, tmp_path: Path
) -> None:
    settings.MEDIA_ROOT = str(tmp_path / "media")
    monkeypatch.delenv("POSTGRES_MIGRATOR_PASSWORD", raising=False)
    with pytest.raises(backups.BackupError, match="POSTGRES_MIGRATOR_PASSWORD"):
        backups.write_backup(io.BytesIO())


def test_restore_rejects_a_non_backyard_archive(fake_pg: None) -> None:
    bogus = io.BytesIO()
    with tarfile.open(fileobj=bogus, mode="w") as archive:
        data = b"not a backup"
        info = tarfile.TarInfo("random.txt")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    bogus.seek(0)
    with pytest.raises(backups.BackupError, match="no backup manifest"):
        backups.restore_backup(bogus, force=True)


def test_restore_refuses_a_populated_database_without_force(
    fake_pg: None, settings: Any, tmp_path: Path
) -> None:
    settings.MEDIA_ROOT = str(tmp_path / "media")
    Member.objects.create(display_name="Someone")  # the DB has members
    archive = _a_valid_archive()
    with pytest.raises(backups.BackupError, match="still has members"):
        backups.restore_backup(archive, force=False)


def test_restore_proceeds_with_force_over_a_populated_database(
    fake_pg: None, settings: Any, tmp_path: Path
) -> None:
    media_root = tmp_path / "media"
    settings.MEDIA_ROOT = str(media_root)
    Member.objects.create(display_name="Someone")
    archive = _a_valid_archive()
    backups.restore_backup(archive, force=True)  # must not raise
    # The media tar in the archive is empty; restore recreates the media root.
    assert media_root.exists()


def _member_with_a_live_elder_link() -> tuple[Member, str, Invite]:
    yard = Yard.objects.create(name="Y", slug="y")
    pod = Pod.objects.create(name="P")
    pod.yards.set([yard])
    member = Member.objects.create(display_name="Nana")
    PodMembership.objects.create(member=member, pod=pod)
    raw = elder_tokens.mint(member)  # a no-login elder link, live
    invite, _ = invites.mint_invite(pod, created_by=None)  # an outstanding /join credential
    return member, raw, invite


def test_forced_security_replay_kills_every_restored_bearer_credential() -> None:
    """TM-7 / T-OP-G5: the replay rotates the generation (killing the generation-anchored
    elder/digest/reply tokens), flushes sessions, and voids outstanding invites."""
    member, raw, invite = _member_with_a_live_elder_link()
    assert elder_tokens.resolve(raw)  # live before
    session = SessionStore()
    session["k"] = 1
    session.create()
    before_gen = member.token_generation

    summary = backups._forced_security_replay()

    member.refresh_from_db()
    assert member.token_generation == before_gen + 1
    with pytest.raises(elder_tokens.ElderTokenInvalid):
        elder_tokens.resolve(raw)  # the restored elder link is DEAD
    assert not Session.objects.filter(session_key=session.session_key).exists()  # flushed
    invite.refresh_from_db()
    assert invite.revoked_at is not None  # voided
    assert summary == {
        "members_rotated": 1,
        "sessions_flushed": 1,
        "invites_voided": 1,
        "digest_tokens_cleared": 0,  # no digest subscription seeded here (see drift-guard)
    }


def test_restore_runs_the_security_replay_so_an_expelled_link_cannot_be_resurrected(
    fake_pg: None, settings: Any, tmp_path: Path
) -> None:
    """The load-bearing property (the retro's gap): a full restore ends with the replay, so
    an ex-partner's elder link that the backup carried is dead after the restore, not live."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    _, raw, _ = _member_with_a_live_elder_link()
    assert elder_tokens.resolve(raw)  # the backup carries a live link

    summary = backups.restore_backup(_a_valid_archive(), force=True)

    with pytest.raises(elder_tokens.ElderTokenInvalid):
        elder_tokens.resolve(raw)  # the restore's forced replay killed it
    assert summary["members_rotated"] >= 1


def _a_valid_archive() -> io.BytesIO:
    """A structurally valid, minimal backup archive (empty db dump + media)."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        manifest = json.dumps({"format": backups.BACKUP_FORMAT, "members": []}).encode()
        info = tarfile.TarInfo("backup-manifest.json")
        info.size = len(manifest)
        archive.addfile(info, io.BytesIO(manifest))
        for name in ("database.dump", "media.tar.gz"):
            if name == "media.tar.gz":
                inner = io.BytesIO()
                with tarfile.open(fileobj=inner, mode="w:gz"):
                    pass
                payload = inner.getvalue()
            else:
                payload = b"PGDMP-stub"
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    buffer.seek(0)
    return buffer


def test_restore_rejects_a_media_tar_that_escapes_the_media_subtree(
    fake_pg: None, settings: Any, tmp_path: Path
) -> None:
    """#47 review HIGH: a crafted archive whose media tar carries a sibling
    member (e.g. `secret_key`) must be REJECTED, never written next to
    MEDIA_ROOT where /data/secret_key (the Django key) lives."""
    media_root = tmp_path / "data" / "media"
    settings.MEDIA_ROOT = str(media_root)
    sentinel = tmp_path / "data" / "secret_key"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("REAL-KEY")

    # Build an archive whose media.tar.gz sneaks a `secret_key` sibling in.
    poisoned = io.BytesIO()
    inner = io.BytesIO()
    with tarfile.open(fileobj=inner, mode="w:gz") as media_tar:
        for name, data in (("media/photo.jpg", b"ok"), ("secret_key", b"ATTACKER-KEY")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            media_tar.addfile(info, io.BytesIO(data))
    media_bytes = inner.getvalue()
    with tarfile.open(fileobj=poisoned, mode="w") as archive:
        manifest = json.dumps({"format": backups.BACKUP_FORMAT, "members": []}).encode()
        for name, payload in (
            ("backup-manifest.json", manifest),
            ("database.dump", b"PGDMP-stub"),
            ("media.tar.gz", media_bytes),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    poisoned.seek(0)

    with pytest.raises(backups.BackupError, match="unexpected member in media archive"):
        backups.restore_backup(poisoned, force=True)
    assert sentinel.read_text() == "REAL-KEY"  # the Django key was NEVER overwritten


def test_restore_promotes_only_the_media_subtree(
    fake_pg: None, settings: Any, tmp_path: Path
) -> None:
    """A well-formed media tar restores under MEDIA_ROOT, and nothing lands in
    MEDIA_ROOT.parent."""
    media_root = tmp_path / "data" / "media"
    settings.MEDIA_ROOT = str(media_root)
    archive = io.BytesIO()
    inner = io.BytesIO()
    with tarfile.open(fileobj=inner, mode="w:gz") as media_tar:
        info = tarfile.TarInfo("media/2026/photo.jpg")
        data = b"a photo"
        info.size = len(data)
        media_tar.addfile(info, io.BytesIO(data))
    with tarfile.open(fileobj=archive, mode="w") as outer:
        manifest = json.dumps({"format": backups.BACKUP_FORMAT}).encode()
        for name, payload in (
            ("backup-manifest.json", manifest),
            ("database.dump", b"PGDMP"),
            ("media.tar.gz", inner.getvalue()),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            outer.addfile(info, io.BytesIO(payload))
    archive.seek(0)

    backups.restore_backup(archive, force=True)
    assert (media_root / "2026" / "photo.jpg").read_bytes() == b"a photo"
    # Nothing leaked into /data (MEDIA_ROOT.parent) beyond the media tree itself.
    assert sorted(p.name for p in media_root.parent.iterdir()) == ["media"]
