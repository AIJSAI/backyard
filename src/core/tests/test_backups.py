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
from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session

from core import backups, elder_tokens, invites
from core.models import Invite, Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db

_MIGRATOR_PW = "a-drill-migrator-passphrase-1"
# The runtime role's password, for the worker-path test below. Both values are ones the
# credential guard and .gitleaks.toml already carry as synthetic.
_APP_PW = "a-fine-passphrase-1234"


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


def test_a_hung_pg_dump_is_killed_rather_than_held_forever(
    monkeypatch: Any, settings: Any, tmp_path: Path
) -> None:
    """The nightly dump runs unattended on a worker with ONE concurrency slot.

    An unbounded pg_dump does not merely fail the backup: it holds that slot, so the digest,
    the weekly health email and every transcode stop with it — the T-MON-1 silence the
    scheduler exists to break, caused by the scheduler. A killed dump is recorded and mailed
    like any other failure.
    """
    settings.MEDIA_ROOT = str(tmp_path / "media")
    bounds: list[float] = []

    def hanging_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        # KeyError, deliberately, if the call goes back to having no bound: a test that
        # reads `kwargs.get("timeout")` would pass just as happily against an unbounded run.
        bounds.append(kwargs["timeout"])
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr("core.backups.subprocess.run", hanging_run)

    with pytest.raises(backups.BackupError, match="did not finish within"):
        backups.write_backup(io.BytesIO())

    assert bounds == [backups.DUMP_TIMEOUT_SECONDS]


def _recording_pg(monkeypatch: Any) -> list[tuple[list[str], dict[str, str]]]:
    """Stub pg_dump, keeping the argv and environment it would have been run with."""
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((argv, dict(kwargs.get("env") or {})))
        if argv[0] == "pg_dump":
            Path(argv[argv.index("-f") + 1]).write_bytes(b"PGDMP-stub-dump")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("core.backups.subprocess.run", fake_run)
    return calls


def test_the_operator_path_dumps_as_the_migrator(
    monkeypatch: Any, settings: Any, tmp_path: Path
) -> None:
    """The documented backup runs in the web container, whose environment carries the
    migrator password; it owns every table, so nothing has to be re-argued about coverage."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    calls = _recording_pg(monkeypatch)

    backups.write_backup(io.BytesIO())

    argv, env = calls[0]
    assert argv[argv.index("-U") + 1] == "backyard_migrator"
    assert env["PGPASSWORD"] == _MIGRATOR_PW


def test_the_worker_path_dumps_as_the_app_role_with_the_timeout_lifted(
    monkeypatch: Any, settings: Any, tmp_path: Path
) -> None:
    """The scheduled backup runs on the worker, which holds NO DDL credentials by design
    (TS-CO-3) — and must not be handed them to make a cron job possible.

    ADR-004's default privileges already grant the app role SELECT on every table the
    migrator creates, so the credential the worker has can read what pg_dump must read. The
    one thing in the way is that role's 15s statement_timeout (TS-PG-5), a request-path
    guard that would kill the dump of any real archive partway through.
    """
    settings.MEDIA_ROOT = str(tmp_path / "media")
    monkeypatch.delenv("POSTGRES_MIGRATOR_PASSWORD", raising=False)
    monkeypatch.setenv("POSTGRES_USER", "backyard_app")
    monkeypatch.setenv("POSTGRES_PASSWORD", _APP_PW)
    calls = _recording_pg(monkeypatch)

    backups.write_backup(io.BytesIO())

    argv, env = calls[0]
    assert argv[argv.index("-U") + 1] == "backyard_app"
    assert env["PGPASSWORD"] == _APP_PW
    assert "statement_timeout=0" in env["PGOPTIONS"]


def test_a_backup_with_no_database_credentials_at_all_refuses(
    monkeypatch: Any, settings: Any, tmp_path: Path
) -> None:
    settings.MEDIA_ROOT = str(tmp_path / "media")
    monkeypatch.delenv("POSTGRES_MIGRATOR_PASSWORD", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    with pytest.raises(backups.BackupError, match="no database credentials"):
        backups.write_backup(io.BytesIO())


def test_restore_still_requires_the_migrator_password(
    monkeypatch: Any, settings: Any, tmp_path: Path
) -> None:
    """The app-role fallback is for DUMPS only. A restore is DDL — it clean-restores the
    schema — so the role that cannot run DDL must not be able to start one and fail halfway
    through, having already dropped objects."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    monkeypatch.delenv("POSTGRES_MIGRATOR_PASSWORD", raising=False)
    _recording_pg(monkeypatch)
    with pytest.raises(backups.BackupError, match="POSTGRES_MIGRATOR_PASSWORD"):
        backups.restore_backup(_a_valid_archive(), force=True)


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


# --- S20: the extraction is bounded before a byte is written -----------------


def _media_archive(files: dict[str, bytes]) -> io.BytesIO:
    """A well-formed backup whose media tar really carries `files`."""
    inner = io.BytesIO()
    with tarfile.open(fileobj=inner, mode="w:gz") as media_tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            media_tar.addfile(info, io.BytesIO(data))
    archive = io.BytesIO()
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
    return archive


def _free_space(monkeypatch: Any, free: int) -> None:
    """Report a fixed amount of free space on whatever volume is asked about.

    The ceilings are read from the module rather than written into the test, and the
    volume reading is faked rather than the SIZES: a tar header's declared size is what
    `addfile` copies, so an archive cannot claim gigabytes it does not carry, and a test
    that shrank the ceiling instead would still exercise the same comparison.
    """
    monkeypatch.setattr(
        "core.backups.shutil.disk_usage",
        lambda path: SimpleNamespace(total=free * 2, used=free, free=free),
    )


def test_restore_refuses_a_media_tree_that_will_not_fit_on_the_volume(
    fake_pg: None, settings: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """A restore is the command somebody runs when things have ALREADY gone wrong, and it
    deletes the old media tree before promoting the new one. So filling the disk halfway
    through leaves a box with neither.

    Fails without `_refuse_an_oversized_extraction`: `extractall` runs, the refusal never
    happens, and the existing tree is gone.
    """
    media_root = tmp_path / "data" / "media"
    settings.MEDIA_ROOT = str(media_root)
    media_root.mkdir(parents=True)
    (media_root / "existing.jpg").write_bytes(b"the family's photos")

    # A volume with a little less room than the reserve plus the incoming tree.
    _free_space(monkeypatch, backups.RESTORE_FREE_SPACE_RESERVE_BYTES + 100)
    archive = _media_archive({"media/new.jpg": b"x" * 500})

    with pytest.raises(backups.BackupError) as caught:
        backups.restore_backup(archive, force=True)
    message = str(caught.value)
    assert "Nothing has been written" in message, message
    assert "usable on this volume" in message, message
    # The loud refusal has to come BEFORE the destructive half, or the sentence is a lie.
    assert (media_root / "existing.jpg").read_bytes() == b"the family's photos"


def test_restore_refuses_a_media_tree_over_the_absolute_ceiling(
    fake_pg: None, settings: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """The backstop for a box whose free space says there is plenty: the absolute total
    still refuses, before anything is written."""
    settings.MEDIA_ROOT = str(tmp_path / "data" / "media")
    _free_space(monkeypatch, 10**15)
    monkeypatch.setattr(backups, "MAX_RESTORED_MEDIA_BYTES", 1000)
    archive = _media_archive({f"media/part-{i}.bin": b"x" * 400 for i in range(4)})

    with pytest.raises(backups.BackupError) as caught:
        backups.restore_backup(archive, force=True)
    assert "ceiling" in str(caught.value) and "Nothing has been written" in str(caught.value)


def test_the_refusal_happens_before_pg_restore_has_touched_the_database(
    settings: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """The sentence has to be true at the moment it is read (Copilot review).

    `pg_restore --clean` drops and rebuilds every table, and it runs BEFORE the media
    tree is extracted. A refusal raised from inside `_restore_media` therefore arrived
    after the family's database had already been replaced — while saying "Nothing has
    been written", which is exactly the kind of false sentence somebody acts on at the
    worst possible moment.

    Fails without the `_refuse_an_oversized_media_archive` call ahead of `pg_restore`:
    pg_restore is invoked, and then the refusal claims nothing happened.
    """
    settings.MEDIA_ROOT = str(tmp_path / "data" / "media")
    invoked: list[str] = []

    def recording_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        invoked.append(argv[0])
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("core.backups.subprocess.run", recording_run)
    _free_space(monkeypatch, 10**15)
    monkeypatch.setattr(backups, "MAX_RESTORED_MEDIA_BYTES", 1000)
    archive = _media_archive({f"media/part-{i}.bin": b"x" * 400 for i in range(4)})

    with pytest.raises(backups.BackupError) as caught:
        backups.restore_backup(archive, force=True)

    assert "Nothing has been written" in str(caught.value)
    assert "pg_restore" not in invoked, (
        "the database was cleaned and restored before the refusal that says nothing was"
    )


def test_a_traversing_media_archive_is_also_refused_before_pg_restore(
    settings: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """The #47 traversal refusal moved forward with the size one, for the same reason:
    a crafted archive should not cost the family their database on the way to being
    rejected."""
    settings.MEDIA_ROOT = str(tmp_path / "data" / "media")
    invoked: list[str] = []

    def recording_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        invoked.append(argv[0])
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("core.backups.subprocess.run", recording_run)
    archive = _media_archive({"media/photo.jpg": b"ok", "secret_key": b"ATTACKER-KEY"})

    with pytest.raises(backups.BackupError, match="unexpected member in media archive"):
        backups.restore_backup(archive, force=True)
    assert "pg_restore" not in invoked


def test_the_outer_members_are_capped_before_either_is_written(
    fake_pg: None, settings: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """Review M3. The ceilings read the MEDIA tar's own headers, which means the media tar
    itself — and `database.dump`, which had no ceiling of any kind — were already extracted
    onto the data volume before anything was consulted. A 200 GB dump filled the disk
    before the guard that exists to stop exactly that had run.

    Red without the `_refuse_an_oversized_extraction` call on the outer members: both
    files land in the staging directory and pg_restore is invoked.
    """
    settings.MEDIA_ROOT = str(tmp_path / "data" / "media")
    _free_space(monkeypatch, 10**15)
    monkeypatch.setattr(backups, "MAX_RESTORED_MEMBER_BYTES", 50)
    invoked: list[str] = []

    def recording_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        invoked.append(argv[0])
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("core.backups.subprocess.run", recording_run)
    # The MEDIA tar is tiny; the DATABASE DUMP is what is over the ceiling, which is the
    # member the old check could not see at all.
    archive = io.BytesIO()
    inner = io.BytesIO()
    with tarfile.open(fileobj=inner, mode="w:gz") as media_tar:
        info = tarfile.TarInfo("media/photo.jpg")
        info.size = 2
        media_tar.addfile(info, io.BytesIO(b"ok"))
    with tarfile.open(fileobj=archive, mode="w") as outer:
        manifest = json.dumps({"format": backups.BACKUP_FORMAT}).encode()
        for name, payload in (
            ("backup-manifest.json", manifest),
            ("database.dump", b"PGDMP" + b"x" * 500),
            ("media.tar.gz", inner.getvalue()),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            outer.addfile(info, io.BytesIO(payload))
    archive.seek(0)

    with pytest.raises(backups.BackupError) as caught:
        backups.restore_backup(archive, force=True)

    assert "database.dump" in str(caught.value), caught.value
    assert "Nothing has been written" in str(caught.value)
    assert "pg_restore" not in invoked


def test_restore_names_the_one_oversized_file(
    fake_pg: None, settings: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """A total tells an operator nothing about what to look at; the per-member ceiling
    names the file."""
    settings.MEDIA_ROOT = str(tmp_path / "data" / "media")
    _free_space(monkeypatch, 10**15)
    monkeypatch.setattr(backups, "MAX_RESTORED_MEMBER_BYTES", 1000)
    archive = _media_archive({"media/ok.jpg": b"x" * 10, "media/bomb.bin": b"x" * 2000})

    with pytest.raises(backups.BackupError) as caught:
        backups.restore_backup(archive, force=True)
    assert "media/bomb.bin" in str(caught.value), caught.value


def test_an_ordinary_family_archive_still_restores(
    fake_pg: None, settings: Any, tmp_path: Path
) -> None:
    """Guard the guard: the ceilings must not refuse the case they exist to protect."""
    media_root = tmp_path / "data" / "media"
    settings.MEDIA_ROOT = str(media_root)
    archive = io.BytesIO()
    inner = io.BytesIO()
    with tarfile.open(fileobj=inner, mode="w:gz") as media_tar:
        data = b"a photo" * 1000
        info = tarfile.TarInfo("media/2026/photo.jpg")
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
    assert (media_root / "2026" / "photo.jpg").read_bytes() == b"a photo" * 1000


# --- S-802: the ENCRYPTED path, end to end through the real commands ---------
#
# The security review found this had zero coverage: every crypto test drove
# backup_crypto directly, and the only command-level test was a refusal. S-802's own
# acceptance requires the restore drill to exercise the encrypted path, so the wiring
# between the two commands — not just the primitive — needs a guard.


def test_the_encrypted_path_round_trips_through_both_commands(
    fake_pg: None, settings: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    from django.core.management import call_command

    from core import backup_crypto

    media = tmp_path / "media"
    media.mkdir()
    (media / "photo.jpg").write_bytes(b"a family photograph")
    settings.MEDIA_ROOT = str(media)
    monkeypatch.setenv("BACKYARD_BACKUP_PASSPHRASE", "a four word diceware phrase")
    archive = tmp_path / "out.bak"

    call_command("backup_instance", str(archive))

    body = archive.read_bytes()
    assert backup_crypto.is_encrypted(body), "the default path must produce an ENCRYPTED archive"
    assert b"a family photograph" not in body, "the photo bytes must not be readable"
    assert not archive.with_name(archive.name + ".partial").exists(), "sidecar not cleaned up"
    assert archive.stat().st_mode & 0o077 == 0, "the archive must not be group/world readable"

    call_command("restore_instance", str(archive), "--force")
    assert (Path(settings.MEDIA_ROOT) / "photo.jpg").read_bytes() == b"a family photograph"


def test_restore_refuses_a_plaintext_archive_when_a_passphrase_is_configured(
    fake_pg: None, settings: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """The downgrade the review found: the backup side refuses to WRITE plaintext without
    an explicit flag, and the restore side used to happily READ it. An attacker who can
    write to the backup directory could swap in their own tar, whose dump is then executed
    against the database as the migrator (DDL) role."""
    from django.core.management import call_command
    from django.core.management.base import CommandError

    media = tmp_path / "media"
    media.mkdir()
    settings.MEDIA_ROOT = str(media)
    archive = tmp_path / "plain.tar"
    call_command("backup_instance", str(archive), "--no-encrypt")
    assert archive.exists()

    monkeypatch.setenv("BACKYARD_BACKUP_PASSPHRASE", "a four word diceware phrase")
    with pytest.raises(CommandError, match="NOT encrypted"):
        call_command("restore_instance", str(archive), "--force")
    # ...and the operator can still override deliberately.
    call_command("restore_instance", str(archive), "--force", "--allow-plaintext")


def test_a_too_short_passphrase_is_refused(tmp_path: Path, monkeypatch: Any) -> None:
    """No escrow means the passphrase is the only thing between a stolen archive and every
    photo of the family; `hunter2` used to be accepted in silence."""
    from django.core.management import call_command
    from django.core.management.base import CommandError

    monkeypatch.setenv("BACKYARD_BACKUP_PASSPHRASE", "hunter2")
    with pytest.raises(CommandError, match="too short"):
        call_command("backup_instance", str(tmp_path / "out.bak"))


def test_env_and_keyfile_passphrases_normalise_identically(tmp_path: Path) -> None:
    """They did not: the env path stripped and the keyfile path did not, so the same
    secret produced two different keys. With no escrow that is permanent data loss —
    back up with one source, restore with the other, and the archive is gone."""
    from core.management.commands.backup_instance import resolve_passphrase

    keyfile = tmp_path / "key"
    keyfile.write_text("a four word diceware phrase\n", encoding="utf-8")
    keyfile.chmod(0o600)

    from_file = resolve_passphrase({"passphrase_file": str(keyfile)})
    import os as _os

    _os.environ["BACKYARD_BACKUP_PASSPHRASE"] = "a four word diceware phrase\n"
    try:
        from_env = resolve_passphrase({})
    finally:
        del _os.environ["BACKYARD_BACKUP_PASSPHRASE"]
    assert from_file == from_env == "a four word diceware phrase"


def test_a_group_readable_keyfile_is_refused(tmp_path: Path) -> None:
    from django.core.management.base import CommandError

    from core.management.commands.backup_instance import resolve_passphrase

    keyfile = tmp_path / "key"
    keyfile.write_text("a four word diceware phrase", encoding="utf-8")
    keyfile.chmod(0o644)
    with pytest.raises(CommandError, match="readable by other users"):
        resolve_passphrase({"passphrase_file": str(keyfile)})


def test_a_binary_keyfile_fails_cleanly_without_disclosing_key_bytes(tmp_path: Path) -> None:
    """`head -c 32 /dev/urandom > keyfile` is the obvious way to make a *keyfile*; it used
    to die with a UnicodeDecodeError whose message printed a byte of the key."""
    from django.core.management.base import CommandError

    from core.management.commands.backup_instance import resolve_passphrase

    keyfile = tmp_path / "key"
    keyfile.write_bytes(bytes([0xFF, 0xFE, 0x00, 0x81]) * 8)
    keyfile.chmod(0o600)
    with pytest.raises(CommandError, match="not UTF-8 text") as caught:
        resolve_passphrase({"passphrase_file": str(keyfile)})
    assert "0x81" not in str(caught.value)
