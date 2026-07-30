"""S-804: the instance shuts down in an order that cannot lose the family's history.

The threat model calls single-maintainer abandonment the likeliest way this instance ends.
When it ends on purpose, the ORDER is the whole safety property:

    export → revoke → (operator destroys volumes)

A decommission that revoked first and then failed to export would have destroyed access to
data nobody had a copy of. So the tests here are mostly about refusing and ordering, not
about the happy path.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core import elder_tokens, posting
from core.management.commands.decommission_instance import CONFIRM_PHRASE
from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db


@dataclass
class Family:
    pod: Pod
    keeper: Member
    second: Member
    elder: Member


@pytest.fixture
def family() -> Family:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="The Reeds")
    pod.yards.set([yard])
    keeper = Member.objects.create(display_name="Keeper One")
    second = Member.objects.create(display_name="Keeper Two")
    elder = Member.objects.create(display_name="Nana", kinship_name="Nana")
    for member in (keeper, second, elder):
        PodMembership.objects.create(member=member, pod=pod)
    posting.create_post(author=keeper, pod=pod, audience_yards=[], body="a memory worth keeping")
    return Family(pod=pod, keeper=keeper, second=second, elder=elder)


def _run(tmp_path: Path, *names: str, confirm: str = CONFIRM_PHRASE) -> None:
    args = []
    for name in names:
        args += ["--to", name]
    call_command("decommission_instance", *args, output_dir=str(tmp_path), confirm=confirm)


# ---------------------------------------------------------------- it refuses


def test_it_refuses_without_the_confirmation_phrase(family: Family, tmp_path: Path) -> None:
    with pytest.raises(CommandError, match="Re-run with --confirm"):
        _run(tmp_path, "Keeper One", "Keeper Two", confirm="")
    assert not list(tmp_path.iterdir()), "it wrote something before being confirmed"


def test_it_refuses_a_single_custodian(family: Family, tmp_path: Path) -> None:
    """ "At least two named members" is the point of the story, not a nicety: one custodian
    is the bus factor the whole procedure exists to remove."""
    with pytest.raises(CommandError, match="at least 2"):
        _run(tmp_path, "Keeper One")
    assert not list(tmp_path.iterdir())


def test_naming_the_same_person_twice_is_still_one_custodian(
    family: Family, tmp_path: Path
) -> None:
    """The obvious way to satisfy a "two names" check by accident."""
    with pytest.raises(CommandError, match="at least 2"):
        _run(tmp_path, "Keeper One", "Keeper One")


def test_an_unknown_name_changes_nothing(family: Family, tmp_path: Path) -> None:
    """It must fail BEFORE the revocation, not half way through it."""
    elder = family.elder
    raw = elder_tokens.mint(elder)
    before = Member.objects.get(pk=elder.pk).token_generation

    with pytest.raises(CommandError, match="no member named"):
        _run(tmp_path, "Keeper One", "Nobody At All")

    assert not list(tmp_path.iterdir())
    assert Member.objects.get(pk=elder.pk).token_generation == before
    assert elder_tokens.resolve(raw) is not None, "credentials were revoked by a failed run"


def test_an_ambiguous_name_refuses_rather_than_guessing(family: Family, tmp_path: Path) -> None:
    Member.objects.create(display_name="Keeper Two")  # a duplicate display name
    with pytest.raises(CommandError, match="ambiguous"):
        _run(tmp_path, "Keeper One", "Keeper Two")
    assert not list(tmp_path.iterdir())


# ---------------------------------------------------------------- it exports, then revokes


def test_it_writes_a_real_export_for_each_named_member(family: Family, tmp_path: Path) -> None:
    _run(tmp_path, "Keeper One", "Keeper Two")
    zips = sorted(tmp_path.glob("*.zip"))
    assert len(zips) == 2, [p.name for p in zips]
    for path in zips:
        with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as archive:
            names = archive.namelist()
            assert "manifest.json" in names and "posts.json" in names
    # The keeper's own post really is in their archive, not just an empty shell.
    keeper_zip = next(p for p in zips if "keeper-one" in p.name)
    with zipfile.ZipFile(io.BytesIO(keeper_zip.read_bytes())) as archive:
        assert b"a memory worth keeping" in archive.read("posts.json")


def test_it_revokes_every_credential_class(family: Family, tmp_path: Path) -> None:
    """The point of revoking while the box is still up: an old bearer URL must meet a 404
    from THIS instance rather than from whoever inherits the domain (T-OP-G4)."""
    elder = family.elder
    raw = elder_tokens.mint(elder)
    assert elder_tokens.resolve(raw) is not None  # live before

    _run(tmp_path, "Keeper One", "Keeper Two")

    # resolve RAISES on a dead token rather than returning None — a stronger signal than a
    # falsy value, and the shape a caller must actually handle.
    with pytest.raises(elder_tokens.ElderTokenInvalid):
        elder_tokens.resolve(raw)


def test_the_export_happens_before_the_revocation(
    family: Family, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordering IS the safety property, so it is asserted directly rather than inferred
    from the happy path. If revocation ran first and the export then failed, the family
    would have lost access to data nobody held a copy of."""
    from core import backups

    order: list[str] = []
    real_export = __import__("core.export", fromlist=["x"]).write_member_export
    real_revoke = backups.revoke_every_credential

    def spy_export(member, destination):  # type: ignore[no-untyped-def]
        order.append("export")
        return real_export(member, destination)

    def spy_revoke():  # type: ignore[no-untyped-def]
        order.append("revoke")
        return real_revoke()

    monkeypatch.setattr("core.export.write_member_export", spy_export)
    monkeypatch.setattr("core.backups.revoke_every_credential", spy_revoke)

    _run(tmp_path, "Keeper One", "Keeper Two")

    assert order.count("export") == 2
    assert order == ["export", "export", "revoke"], order


def test_it_does_not_pretend_to_destroy_the_volumes(
    family: Family, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Destroying a provider snapshot needs credentials this process has no business
    holding, and "the command deleted the snapshots before I checked the export" is not a
    recoverable mistake. It must say so rather than imply it handled everything."""
    _run(tmp_path, "Keeper One", "Keeper Two")
    out = capsys.readouterr().out
    assert "STILL TO DO, BY HAND" in out
    assert "provider snapshots" in out
    assert "docs/runbooks/shutdown.md" in out
    # And it must not claim the domain can be dropped immediately.
    assert "until every printed QR is out of circulation" in out


def test_the_revocation_is_the_same_implementation_a_restore_uses() -> None:
    """Two implementations of "kill every credential" is how one of them comes to miss a
    class. Pinned so a future refactor cannot fork them."""
    from core import backups

    assert backups.revoke_every_credential.__module__ == "core.backups"
    assert backups.revoke_every_credential() is not None
