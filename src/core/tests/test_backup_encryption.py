"""S-802: backups are encrypted, and refuse to half-restore (BLOCKER from the audit).

S-802's acceptance says the backup command *"encrypts by default with a wizard-established
passphrase or keyfile … plaintext output requires an explicit --no-encrypt flag with a loud
warning."* The shipped backup was a plain tar — the module docstring said so — while the
story sat at `passing`. A family's entire database and every photograph of every child lay
in the clear on the same volume as the running instance.

These test the crypto layer directly (fast, and it is where the security properties live);
the command wiring is exercised by the round-trip and the refusal tests at the bottom.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from core import backup_crypto

_PASS = "correct horse battery staple"


def _roundtrip(plain: bytes, passphrase: str = _PASS) -> bytes:
    sealed = io.BytesIO()
    backup_crypto.encrypt(io.BytesIO(plain), sealed, passphrase)
    out = io.BytesIO()
    sealed.seek(0)
    backup_crypto.decrypt(sealed, out, passphrase)
    return out.getvalue()


def test_a_backup_round_trips_byte_for_byte() -> None:
    payload = os.urandom(1000)
    assert _roundtrip(payload) == payload


def test_a_multi_chunk_backup_round_trips() -> None:
    """A family instance's media is far larger than one chunk, so the chunked path is the
    real path, not an edge case."""
    payload = os.urandom(backup_crypto.CHUNK_BYTES * 2 + 1234)
    assert _roundtrip(payload) == payload


def test_an_empty_backup_round_trips() -> None:
    assert _roundtrip(b"") == b""


def test_the_ciphertext_does_not_contain_the_plaintext() -> None:
    """The point of the whole exercise, asserted rather than assumed."""
    secret = b"Priya's birthday party at 41.25 N 96.0 W"
    sealed = io.BytesIO()
    backup_crypto.encrypt(io.BytesIO(secret * 50), sealed, _PASS)
    assert secret not in sealed.getvalue()


def test_a_wrong_passphrase_is_refused_loudly() -> None:
    sealed = io.BytesIO()
    backup_crypto.encrypt(io.BytesIO(b"family history"), sealed, _PASS)
    sealed.seek(0)
    with pytest.raises(backup_crypto.BackupCryptoError, match="wrong passphrase"):
        backup_crypto.decrypt(sealed, io.BytesIO(), "not the passphrase")


def test_a_truncated_archive_is_refused_rather_than_half_restored() -> None:
    """The failure mode that matters most.

    Per-chunk authentication alone would happily decrypt the surviving chunks of a
    truncated archive — a restore that silently returns most of a family's history and
    says nothing. The end-of-stream marker is bound into the AAD so the missing tail is
    detected instead.
    """
    sealed = io.BytesIO()
    backup_crypto.encrypt(io.BytesIO(os.urandom(backup_crypto.CHUNK_BYTES * 3)), sealed, _PASS)
    body = sealed.getvalue()
    truncated = io.BytesIO(body[: len(body) // 2])
    with pytest.raises(backup_crypto.BackupCryptoError, match="truncat"):
        backup_crypto.decrypt(truncated, io.BytesIO(), _PASS)


def test_a_tampered_chunk_is_refused() -> None:
    sealed = io.BytesIO()
    backup_crypto.encrypt(io.BytesIO(os.urandom(4096)), sealed, _PASS)
    body = bytearray(sealed.getvalue())
    body[-1] ^= 0xFF  # flip a bit in the final chunk's tag
    with pytest.raises(backup_crypto.BackupCryptoError):
        backup_crypto.decrypt(io.BytesIO(bytes(body)), io.BytesIO(), _PASS)


def test_reordered_chunks_are_refused() -> None:
    """Chunk ORDER is authenticated. Without the index in the AAD an attacker could
    rearrange a family's archive and every chunk would still verify individually."""
    plain = os.urandom(backup_crypto.CHUNK_BYTES) + os.urandom(backup_crypto.CHUNK_BYTES) + b"x"
    sealed = io.BytesIO()
    backup_crypto.encrypt(io.BytesIO(plain), sealed, _PASS)
    body = sealed.getvalue()

    header = len(backup_crypto.MAGIC) + 12 + 16 + 8
    import struct

    cursor = header
    chunks = []
    while cursor < len(body):
        (size,) = struct.unpack(">I", body[cursor : cursor + 4])
        chunks.append(body[cursor : cursor + 4 + size])
        cursor += 4 + size
    assert len(chunks) >= 3, "need several chunks for this to mean anything"

    swapped = body[:header] + chunks[1] + chunks[0] + b"".join(chunks[2:])
    with pytest.raises(backup_crypto.BackupCryptoError):
        backup_crypto.decrypt(io.BytesIO(swapped), io.BytesIO(), _PASS)


def test_a_plaintext_archive_is_recognised_as_not_ours() -> None:
    """Restore must be able to tell the two shapes apart, so an operator handed the wrong
    file gets a sentence rather than a tar parse error."""
    assert not backup_crypto.is_encrypted(b"a plain tar starts otherwise")
    sealed = io.BytesIO()
    backup_crypto.encrypt(io.BytesIO(b"x"), sealed, _PASS)
    assert backup_crypto.is_encrypted(sealed.getvalue()[:32])


def test_encrypting_without_a_passphrase_is_refused() -> None:
    with pytest.raises(backup_crypto.BackupCryptoError):
        backup_crypto.encrypt(io.BytesIO(b"x"), io.BytesIO(), "")


def test_two_backups_of_the_same_bytes_differ() -> None:
    """Fresh salt and nonce every time: identical archives would leak that nothing
    changed between two backups, and would reuse a nonce under one derived key."""
    payload = b"the same family history"
    first, second = io.BytesIO(), io.BytesIO()
    backup_crypto.encrypt(io.BytesIO(payload), first, _PASS)
    backup_crypto.encrypt(io.BytesIO(payload), second, _PASS)
    assert first.getvalue() != second.getvalue()


def test_the_backup_command_refuses_to_write_plaintext_by_accident(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S-802's headline: encrypted BY DEFAULT. With no passphrase configured and no
    explicit --no-encrypt, the command must refuse rather than quietly ship a plain tar."""
    from django.core.management import call_command
    from django.core.management.base import CommandError

    monkeypatch.delenv("BACKYARD_BACKUP_PASSPHRASE", raising=False)
    with pytest.raises(CommandError, match="refusing to write an unencrypted backup"):
        call_command("backup_instance", str(tmp_path / "out.tar"))
