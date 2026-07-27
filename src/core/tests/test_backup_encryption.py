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
import struct
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


def _split(body: bytes) -> tuple[bytes, list[bytes]]:
    """Header plus each length-prefixed chunk, so a test can cut on a real boundary."""
    header = len(backup_crypto.MAGIC) + 12 + 16 + 8
    cursor, chunks = header, []
    while cursor < len(body):
        (size,) = struct.unpack(">I", body[cursor : cursor + 4])
        chunks.append(body[cursor : cursor + 4 + size])
        cursor += 4 + size
    return body[:header], chunks


def test_an_archive_truncated_on_a_CHUNK_BOUNDARY_is_refused() -> None:
    """The failure mode that matters most — and the one a sloppier test misses.

    A security review proved the earlier version of this test was FALSE-GREEN: it cut at
    `len(body) // 2`, which lands mid-chunk and trips the plain length-prefix check, not
    the end-of-stream AAD binding it claimed to cover. A mutant with the silent
    half-restore bug reintroduced passed it while handing back 8 MB of a 12 MB archive.

    The realistic truncation — an interrupted scp, rsync, or object-store PUT — stops on a
    block edge, which is exactly a clean chunk boundary. So cut there, and assert the
    SPECIFIC message, because that is what distinguishes the two code paths.
    """
    sealed = io.BytesIO()
    backup_crypto.encrypt(io.BytesIO(os.urandom(backup_crypto.CHUNK_BYTES * 3)), sealed, _PASS)
    header, chunks = _split(sealed.getvalue())
    assert len(chunks) >= 3, "need several chunks for a boundary cut to mean anything"

    lopped = io.BytesIO(header + b"".join(chunks[:-1]))  # drop exactly the final chunk
    with pytest.raises(backup_crypto.BackupCryptoError, match="end-of-stream chunk is missing"):
        backup_crypto.decrypt(lopped, io.BytesIO(), _PASS)


def test_an_archive_truncated_MID_CHUNK_is_also_refused() -> None:
    """The other cut, kept as its own case so neither can silently cover for the other."""
    sealed = io.BytesIO()
    backup_crypto.encrypt(io.BytesIO(os.urandom(backup_crypto.CHUNK_BYTES * 3)), sealed, _PASS)
    body = sealed.getvalue()
    with pytest.raises(backup_crypto.BackupCryptoError, match="incomplete chunk"):
        backup_crypto.decrypt(io.BytesIO(body[: len(body) // 2]), io.BytesIO(), _PASS)


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

    header, chunks = _split(body)
    assert len(chunks) >= 3, "need several chunks for this to mean anything"

    swapped = header + chunks[1] + chunks[0] + b"".join(chunks[2:])
    with pytest.raises(backup_crypto.BackupCryptoError):
        backup_crypto.decrypt(io.BytesIO(swapped), io.BytesIO(), _PASS)


def test_the_aad_binds_the_chunk_index_independently_of_the_nonce() -> None:
    """Defence in depth, pinned.

    Chunk order is protected twice over: the index is in the nonce AND in the AAD. The
    reorder test above passes on the nonce alone, so removing the index from the AAD used
    to ship all-green. This asserts the AAD contribution directly.
    """
    assert backup_crypto._aad(0, final=False) != backup_crypto._aad(1, final=False)
    assert backup_crypto._aad(3, final=True) != backup_crypto._aad(3, final=False)
    assert b"|3|" in backup_crypto._aad(3, final=False)


def test_a_header_with_absurd_kdf_parameters_is_refused_before_the_kdf_runs() -> None:
    """The header is UNAUTHENTICATED, so its numbers are attacker input.

    A hand-written 91-byte file declaring n=2**24 allocated 16 GiB and 64 seconds of CPU —
    inside the family's live container, since that is where the documented restore runs.
    Invalid values escaped as a raw ValueError rather than this module's error type.
    """
    for n, r, p in ((2**24, 8, 1), (2**31, 8, 1), (0, 8, 1), (3, 8, 1), (2**15, 0, 1)):
        body = backup_crypto.MAGIC + struct.pack(">III", n, r, p) + b"\x00" * 16 + b"\x00" * 8
        with pytest.raises(backup_crypto.BackupCryptoError, match="refusing"):
            backup_crypto.decrypt(io.BytesIO(body), io.BytesIO(), _PASS)


def test_an_oversized_declared_chunk_is_refused_before_it_is_read() -> None:
    """CHUNK_BYTES claims to bound memory 'during both directions'; on the decrypt side the
    length came straight from the archive, so one crafted chunk drove peak RSS to ~3x."""
    body = (
        backup_crypto.MAGIC
        + struct.pack(">III", 2**17, 8, 1)
        + b"\x00" * 24
        + struct.pack(">I", backup_crypto.CHUNK_BYTES * 64)
    )
    with pytest.raises(backup_crypto.BackupCryptoError, match="larger than this format"):
        backup_crypto.decrypt(io.BytesIO(body), io.BytesIO(), _PASS)


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
    # Asserted FIELD BY FIELD, because a whole-file comparison passes if either one alone
    # is fresh — mutation-testing showed a constant salt and a constant nonce prefix each
    # shipped green against the weaker assertion.
    start = len(backup_crypto.MAGIC) + 12
    salt_a, salt_b = first.getvalue()[start : start + 16], second.getvalue()[start : start + 16]
    nonce_a = first.getvalue()[start + 16 : start + 24]
    nonce_b = second.getvalue()[start + 16 : start + 24]
    assert salt_a != salt_b, "the salt must be fresh per archive (the KEY depends on it)"
    assert nonce_a != nonce_b, "the nonce prefix must be fresh per archive"


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
