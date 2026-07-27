"""Uploads held across the TM-3 confirmation hop, so a wide post never loses its photos.

The bug this exists to close: composing with photos AND a yard audience returned the
confirmation page *before* the media was attached, and that page is an ordinary form with
no ``enctype="multipart/form-data"`` and no file inputs. The re-POST therefore arrived with
an empty ``request.FILES`` and the post was created with zero media and no error — the
single most valuable post type in the product ("Camp dump, finally", aimed at one whole
side of the family) silently became a caption. Nothing told the poster.

Files cannot survive a round trip through a browser form, so the bytes are staged
server-side and the member carries only an opaque handle.

Security posture:

* **Names are ours, never the client's.** Every staged file is written under a
  ``secrets.token_urlsafe`` name inside ``MEDIA_ROOT/staging``; the uploaded filename is
  never used for anything, so there is no path traversal to reason about.
* **The handle is meaningless outside its own session.** The manifest lives in the
  server-side (database-backed) session, so a handle stolen from one member's form does
  not name anything in another member's session and claims nothing. The handle is looked
  up in the session, never trusted from the POST body on its own.
* **Bytes do not linger.** A claim deletes the files it hands back, and an abandoned
  confirmation is swept after ``STAGING_TTL``: an unfinished post must not leave family
  photographs sitting on disk indefinitely.

What validation has run by staging time differs by kind, and the difference is worth
being exact about: a VIDEO is fully validated first (size, ISOBMFF magic, duration), while
a PHOTO has only had its size bounded — the format allowlist and decompression-bomb guard
live in ``media.ingest_photo``, which runs at attach. So a staged photo is
size-bounded-but-undecoded bytes on disk. That is acceptable because nothing serves this
directory (there is no static route to MEDIA_ROOT and ``serve_media`` resolves strictly
through ``MediaAsset`` rows), but it is not the same as "validated", and the sweep plus
the per-session budget below are what bound it.
"""

from __future__ import annotations

import datetime
import secrets
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone

_SESSION_KEY = "staged_uploads"
# An abandoned confirmation should not keep a family's photographs on disk. Long enough
# that a member can hesitate over "post to the whole Whitfield side?" and still finish.
STAGING_TTL = datetime.timedelta(hours=6)
# What one session may hold at once. Comfortably above a legitimate wide post (20 photos
# at the 15 MB ceiling, or 4 clips at 100 MB) and far below anything that threatens the
# data volume the served media, the backups and the persisted secret key all share.
MAX_SESSION_STAGED_BYTES = 500 * 1024 * 1024


def _staging_dir() -> Path:
    path = Path(settings.MEDIA_ROOT) / "staging"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write(raw: bytes) -> str:
    name = secrets.token_urlsafe(24)
    (_staging_dir() / name).write_bytes(raw)
    return name


def _read_and_remove(name: str) -> bytes | None:
    """Read one staged file and delete it. Returns None if it is already gone (a double
    submit, or a sweep that ran between render and confirm)."""
    # Re-derive the path from the staging dir and reject anything that escapes it. The
    # names here are ours, so this cannot fire today; it is the guard that keeps it true
    # if a future caller ever passes a name through from a request.
    path = (_staging_dir() / name).resolve()
    if path.parent != _staging_dir().resolve() or not path.is_file():
        return None
    raw = path.read_bytes()
    path.unlink(missing_ok=True)
    return raw


def _prune(manifest: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    """Drop manifest entries past the TTL, so one long-lived session cannot accumulate
    handles for files the sweep has already collected.

    Without this the manifest only ever grew: nothing but an explicit claim removed an
    entry, and the cancel path is a plain GET that never claims. Every request then
    re-read and re-wrote a session row that never shrank.
    """
    cutoff = timezone.now() - STAGING_TTL
    kept: dict[str, dict[str, object]] = {}
    for handle, entry in manifest.items():
        stamp = entry.get("staged_at")
        if not isinstance(stamp, str):
            continue
        try:
            staged_at = datetime.datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if staged_at >= cutoff:
            kept[handle] = entry
    return kept


def stage(request: HttpRequest, *, photos: list[bytes], videos: list[bytes]) -> str | None:
    """Hold already-validated bytes for the confirmation hop. Returns the handle, or
    None when there is nothing to hold (so the caller renders an unchanged form).

    Bounded per session: an authenticated member can otherwise loop the composer's error
    path — which re-stages every time and never claims — and park hundreds of megabytes
    per request on the same volume that holds the served media and the persisted secret
    key. Past the budget the OLDEST staged bytes are evicted rather than refusing the
    upload, so the member's most recent intent is the one that survives.
    """
    if not photos and not videos:
        return None
    manifest = _prune(request.session.get(_SESSION_KEY, {}))

    incoming = sum(len(raw) for raw in photos) + sum(len(raw) for raw in videos)
    budget = MAX_SESSION_STAGED_BYTES - incoming
    for handle in list(manifest):  # oldest first: dicts preserve insertion order
        if _manifest_bytes(manifest) <= max(budget, 0):
            break
        entry = manifest.pop(handle)
        _release(entry)

    handle = secrets.token_urlsafe(16)
    manifest[handle] = {
        "photos": [_write(raw) for raw in photos],
        "videos": [_write(raw) for raw in videos],
        "bytes": incoming,
        "staged_at": timezone.now().isoformat(),
    }
    request.session[_SESSION_KEY] = manifest
    return handle


def _manifest_bytes(manifest: dict[str, dict[str, object]]) -> int:
    total = 0
    for entry in manifest.values():
        size = entry.get("bytes")
        if isinstance(size, int):
            total += size
    return total


def _release(entry: dict[str, object]) -> None:
    """Unlink an entry's files without reading them back into memory."""
    for key in ("photos", "videos"):
        names = entry.get(key)
        if not isinstance(names, list):
            continue
        for name in names:
            if isinstance(name, str):
                (_staging_dir() / name).unlink(missing_ok=True)


@dataclass(frozen=True)
class Claim:
    """What a claim actually recovered, and what it could not.

    ``missing`` is the whole point. A staged file can be gone by confirm time — the sweep
    crossed the TTL while the member hesitated, a double submit consumed it, a session and
    the disk fell out of step. Returning only the survivors would silently recreate the
    very defect this module exists to close, one boundary further along, so the shortfall
    is a first-class part of the result and the caller must speak it.
    """

    photos: list[bytes]
    videos: list[bytes]
    missing: int


def claim(request: HttpRequest, handle: str | None) -> Claim:
    """Take the staged bytes back for a handle, removing them from disk and session.

    An unknown handle yields an empty claim rather than an error: the post still goes out.
    """
    if not handle:
        return Claim([], [], 0)
    manifest = request.session.get(_SESSION_KEY, {})
    entry = manifest.pop(handle, None)
    if entry is None:
        return Claim([], [], 0)
    request.session[_SESSION_KEY] = manifest
    expected = len(entry["photos"]) + len(entry["videos"])
    photos = [raw for raw in (_read_and_remove(n) for n in entry["photos"]) if raw is not None]
    videos = [raw for raw in (_read_and_remove(n) for n in entry["videos"]) if raw is not None]
    return Claim(photos, videos, expected - len(photos) - len(videos))


def discard(request: HttpRequest, handle: str | None) -> None:
    """Drop staged bytes without using them (the member cancelled the wide send)."""
    claim(request, handle)


def sweep(older_than: datetime.timedelta = STAGING_TTL) -> int:
    """Delete staged files older than the TTL. Returns how many were removed.

    Orphan-safe by design: it walks the DIRECTORY by mtime rather than the sessions, so a
    file whose session expired — the common way staging is abandoned — is still collected.
    """
    cutoff = timezone.now() - older_than
    removed = 0
    for path in _staging_dir().iterdir():
        if not path.is_file():
            continue
        mtime = datetime.datetime.fromtimestamp(path.stat().st_mtime, tz=datetime.UTC)
        if mtime < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed
