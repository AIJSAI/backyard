"""At-rest encryption for instance backups (S-802).

S-802's acceptance is explicit: *"The one backup command encrypts by default with a
wizard-established passphrase or keyfile and a printable recovery sheet; plaintext output
requires an explicit ``--no-encrypt`` flag with a loud warning."* The shipped backup was a
plain tar and the module said so in its own docstring — so the story was `passing` against
a bar it did not meet, and a family's entire database and media sat in the clear on the
same volume as the running instance. Anyone who reached `/data` — a stolen disk, a
mis-scoped bind mount, a borrowed VPS snapshot — had every photograph of every child.

Design, and why each part is the way it is:

* **scrypt, not a bare hash.** The key comes from a human passphrase, so the KDF is the
  only thing standing between a leaked archive and an offline guessing attack. Parameters
  are stored in the header, so raising them later does not strand old archives.
* **AES-256-GCM, chunked.** A family instance's media can be gigabytes; one-shot
  encryption would mean holding it all in memory. Each chunk is sealed independently.
* **The chunk index and the end-of-stream marker are authenticated.** Per-chunk GCM alone
  would let an attacker reorder, drop or truncate chunks — every individual chunk would
  still verify. Binding the index and a final-chunk flag into the AAD makes the ORDER and
  the COMPLETENESS part of what the tag covers, so a truncated archive fails loudly
  instead of restoring a plausible-looking half of a family's history.

There is deliberately no key escrow and no key stored anywhere in the app: lose the
passphrase and the archive is gone. That is the honest trade for the app never custodying
long-lived key material (the T-EMAIL-5 spirit), and it is why the runbook's recovery sheet
matters.
"""

from __future__ import annotations

import os
import struct
from typing import IO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"BACKYARD-ENC/1\n"
_SALT_BYTES = 16
_NONCE_PREFIX_BYTES = 8
_KEY_BYTES = 32
# 128 MiB and well under a second: OWASP's current scrypt floor (n=2**17, r=8, p=1). These
# archives are long-lived and the asset is photographs of children — one stolen today is
# attacked for years, so the cost is set for then, not for now. Old archives still restore:
# the parameters travel in the header, which is exactly why they are there.
_SCRYPT_N = 2**17
_SCRYPT_R = 8
_SCRYPT_P = 1
# Accepted range when READING a header. Wide enough for archives written by other versions,
# narrow enough that the KDF cannot be turned into a denial-of-service.
_MIN_SCRYPT_N = 2**14
_MAX_SCRYPT_N = 2**20
_GCM_TAG_BYTES = 16
# Plaintext chunk size. Bounds peak memory during both directions.
CHUNK_BYTES = 4 * 1024 * 1024


class BackupCryptoError(Exception):
    """Wrong passphrase, truncated archive, or a stream that is not one of ours."""


def _derive(passphrase: str, salt: bytes, *, n: int, r: int, p: int) -> bytes:
    kdf = Scrypt(salt=salt, length=_KEY_BYTES, n=n, r=r, p=p)
    return kdf.derive(passphrase.encode("utf-8"))


def _aad(index: int, *, final: bool) -> bytes:
    """What the tag covers besides the ciphertext: WHERE this chunk sits and whether the
    stream ends here. Without this, chunks could be reordered or the tail dropped and
    every remaining chunk would still authenticate."""
    return b"backyard-enc/1|%d|%s" % (index, b"final" if final else b"cont")


def is_encrypted(head: bytes) -> bool:
    """Whether a stream begins with our magic. Lets restore accept either shape and tell
    the operator which one they handed it, rather than failing with a tar error."""
    return head.startswith(MAGIC)


def encrypt(plain: IO[bytes], out: IO[bytes], passphrase: str) -> None:
    """Encrypt `plain` into `out`. Streamed: never more than one chunk is resident."""
    if not passphrase:
        raise BackupCryptoError("a passphrase is required to encrypt a backup")
    salt = os.urandom(_SALT_BYTES)
    nonce_prefix = os.urandom(_NONCE_PREFIX_BYTES)
    key = _derive(passphrase, salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    aes = AESGCM(key)

    out.write(MAGIC)
    out.write(struct.pack(">III", _SCRYPT_N, _SCRYPT_R, _SCRYPT_P))
    out.write(salt)
    out.write(nonce_prefix)

    index = 0
    pending = plain.read(CHUNK_BYTES)
    while True:
        lookahead = plain.read(CHUNK_BYTES)
        final = not lookahead
        nonce = nonce_prefix + struct.pack(">I", index)
        sealed = aes.encrypt(nonce, pending, _aad(index, final=final))
        out.write(struct.pack(">I", len(sealed)))
        out.write(sealed)
        if final:
            break
        pending = lookahead
        index += 1


def decrypt(source: IO[bytes], out: IO[bytes], passphrase: str) -> None:
    """Decrypt `source` into `out`, refusing anything that fails its tag.

    A wrong passphrase, a flipped byte, a reordered chunk and a truncated archive all end
    here as the same loud failure. That is the point: a backup that restores *most* of a
    family's history without saying so is worse than one that refuses.
    """
    if source.read(len(MAGIC)) != MAGIC:
        raise BackupCryptoError("not a Backyard encrypted backup")
    header = source.read(12)
    if len(header) != 12:
        raise BackupCryptoError("truncated backup header")
    n, r, p = struct.unpack(">III", header)
    # The header is UNAUTHENTICATED — it has to be, the key comes from it — so every value
    # in it is attacker-controlled until a tag verifies. Unbounded scrypt parameters are a
    # memory bomb: a hand-written 91-byte "archive" declaring n=2**24 allocates 16 GiB, and
    # the documented restore runs inside the live instance's container, so that OOM-kills
    # the family's server. Invalid values (n=0, n=3, r=0) also escaped as a raw ValueError
    # rather than this module's error type. Bounded to what this format actually produces.
    if not (_MIN_SCRYPT_N <= n <= _MAX_SCRYPT_N and n & (n - 1) == 0):
        raise BackupCryptoError(
            f"refusing a backup header with an unreasonable scrypt cost (n={n}); "
            "this is not an archive Backyard produced"
        )
    if not (1 <= r <= 32) or not (1 <= p <= 16):
        raise BackupCryptoError(
            f"refusing a backup header with unreasonable scrypt parameters (r={r}, p={p})"
        )
    salt = source.read(_SALT_BYTES)
    nonce_prefix = source.read(_NONCE_PREFIX_BYTES)
    if len(salt) != _SALT_BYTES or len(nonce_prefix) != _NONCE_PREFIX_BYTES:
        raise BackupCryptoError("truncated backup header")
    aes = AESGCM(_derive(passphrase, salt, n=n, r=r, p=p))

    index = 0
    while True:
        raw_len = source.read(4)
        if not raw_len:
            # Ran out of chunks without ever seeing the final marker: the archive was
            # truncated. Refuse rather than hand back a partial restore.
            raise BackupCryptoError("truncated backup: the end-of-stream chunk is missing")
        if len(raw_len) != 4:
            raise BackupCryptoError("truncated backup: incomplete chunk length")
        (size,) = struct.unpack(">I", raw_len)
        if size > CHUNK_BYTES + _GCM_TAG_BYTES:
            # Without this the chunk size bounds memory on the ENCRYPT side only: a crafted
            # archive declaring one enormous chunk is read whole before its tag is checked.
            raise BackupCryptoError("refusing a backup chunk larger than this format writes")
        sealed = source.read(size)
        if len(sealed) != size:
            raise BackupCryptoError("truncated backup: incomplete chunk")
        nonce = nonce_prefix + struct.pack(">I", index)
        try:
            out.write(aes.decrypt(nonce, sealed, _aad(index, final=True)))
            return  # the final chunk verified under the final-marker AAD: stream complete
        except InvalidTag:
            pass
        try:
            out.write(aes.decrypt(nonce, sealed, _aad(index, final=False)))
        except InvalidTag as exc:
            raise BackupCryptoError(
                "could not decrypt the backup: wrong passphrase, or the archive has been "
                "altered or truncated"
            ) from exc
        index += 1
