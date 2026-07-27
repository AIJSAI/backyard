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

Bytes are staged only *after* the same validation the direct path applies, so nothing
reaches disk that would have been rejected anyway.
"""

from __future__ import annotations

import datetime
import secrets
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone

_SESSION_KEY = "staged_uploads"
# An abandoned confirmation should not keep a family's photographs on disk. Long enough
# that a member can hesitate over "post to the whole Whitfield side?" and still finish.
STAGING_TTL = datetime.timedelta(hours=6)


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


def stage(request: HttpRequest, *, photos: list[bytes], videos: list[bytes]) -> str | None:
    """Hold already-validated bytes for the confirmation hop. Returns the handle, or
    None when there is nothing to hold (so the caller renders an unchanged form)."""
    if not photos and not videos:
        return None
    handle = secrets.token_urlsafe(16)
    manifest = request.session.get(_SESSION_KEY, {})
    manifest[handle] = {
        "photos": [_write(raw) for raw in photos],
        "videos": [_write(raw) for raw in videos],
        "staged_at": timezone.now().isoformat(),
    }
    request.session[_SESSION_KEY] = manifest
    return handle


def claim(request: HttpRequest, handle: str | None) -> tuple[list[bytes], list[bytes]]:
    """Take the staged bytes back for a handle, removing them from disk and session.

    An unknown handle yields empty lists rather than an error: the post still goes out.
    The caller compares what it staged with what it got back, so a claim that came up
    short is reported to the member instead of vanishing.
    """
    if not handle:
        return [], []
    manifest = request.session.get(_SESSION_KEY, {})
    entry = manifest.pop(handle, None)
    if entry is None:
        return [], []
    request.session[_SESSION_KEY] = manifest
    photos = [raw for raw in (_read_and_remove(n) for n in entry["photos"]) if raw is not None]
    videos = [raw for raw in (_read_and_remove(n) for n in entry["videos"]) if raw is not None]
    return photos, videos


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
