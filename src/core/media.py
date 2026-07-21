"""Photo ingest and re-encode (S-401, TM-9, TS-PP-3/4).

A member-uploaded image is hostile bytes. This module is the ingest gate. It opens
with Pillow under an error-not-warn decompression-bomb limit (TS-PP-3), accepts only
a small format allowlist, applies EXIF orientation, and re-encodes to a fixed raster
format. The re-encode is the whole point: it strips every EXIF, GPS, XMP, and IPTC
field (TM-9), pins the stored content type from the decoded format rather than the
client's claim, and turns an SVG or HTML polyglot into either a rejected upload or an
inert raster (TS-PP-4). The uploaded filename and content-type header are never
trusted. The access-checked serving of the result lives in media_views.
"""

from __future__ import annotations

import io
import warnings

from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import MediaAsset, Post

# Formats accepted at open. HEIC is deliberately absent: the pillow-heif question is a
# wave-3 measurement gate, so a HEIC phone photo is re-encoded client-side or rejected
# here, never passed through undecoded.
_ALLOWED_INPUT_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "GIF"})
# Error, not warn, above this bound (TS-PP-3). Sized above a normal phone photo but
# tight enough that the decoded RGB bitmap (~3 bytes/pixel, doubled by transpose and
# convert) cannot exhaust a small self-hosted VM across the three gunicorn workers
# (security review MEDIUM-2). A full-resolution multi-tens-of-megapixel shot should be
# resized client-side before upload (S-401), which the output box already forces anyway.
_MAX_PIXELS = 30_000_000
_FULL_MAX = (2048, 2048)
_THUMB_MAX = (400, 400)
_JPEG_QUALITY = 85
_OUTPUT_CONTENT_TYPE = "image/jpeg"
_MAX_ALT = 500

# Cap decoded pixels process-wide, set once at import (security review LOW-1). Doing it
# here instead of mutating the global per call removes the cross-request race a threaded
# worker would expose, and a lower bomb limit is only ever more protective for any decode.
Image.MAX_IMAGE_PIXELS = _MAX_PIXELS


class MediaRejected(Exception):
    """The upload could not be safely decoded and re-encoded."""


def _decode(raw: bytes) -> Image.Image:
    """Open and validate an uploaded image, or raise MediaRejected. Enforces the
    format allowlist and the error-not-warn decompression-bomb limit."""
    with warnings.catch_warnings():
        # A decompression-bomb warning becomes an error, so a bomb is a rejected upload
        # rather than a log line that decoded anyway (TS-PP-3).
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            img = Image.open(io.BytesIO(raw))
            img.load()  # force a full decode so a truncated or bomb file fails here
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise MediaRejected("image too large") from exc
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise MediaRejected("undecodable image") from exc
    if img.format not in _ALLOWED_INPUT_FORMATS:
        raise MediaRejected(f"format {img.format!r} not accepted")
    return img


def _reencode(img: Image.Image, max_size: tuple[int, int]) -> bytes:
    """Apply EXIF orientation, flatten, downscale within a box, and re-encode to JPEG.
    The output is a fresh file with no EXIF, GPS, or XMP metadata (TM-9)."""
    oriented = ImageOps.exif_transpose(img)  # bake orientation before it is discarded
    flattened = oriented.convert("RGB")  # JPEG has no alpha or palette
    flattened.thumbnail(max_size)  # in place, preserves aspect ratio
    # Pillow's JPEG encoder is the one path that back-fills a field from im.info: the
    # COM comment marker rides along from a JPEG or GIF source even though EXIF/XMP/ICC
    # do not (security review MEDIUM-1). Drop it so the re-encode strips it too (TM-9).
    flattened.info.pop("comment", None)
    out = io.BytesIO()
    flattened.save(out, format="JPEG", quality=_JPEG_QUALITY)
    return out.getvalue()


def ingest_photo(*, post: Post, raw: bytes, alt_text: str = "") -> MediaAsset:
    """Re-encode and store one uploaded photo as a media asset on the post. Raises
    MediaRejected on anything that does not decode to an allowed image format. The
    stored content type is always the re-encoded JPEG, never the client's claim."""
    img = _decode(raw)
    full_bytes = _reencode(img, _FULL_MAX)
    thumb_bytes = _reencode(img, _THUMB_MAX)
    asset = MediaAsset(
        post=post, content_type=_OUTPUT_CONTENT_TYPE, alt_text=alt_text.strip()[:_MAX_ALT]
    )
    asset.image.save(f"{asset.token}.jpg", ContentFile(full_bytes), save=False)
    asset.thumbnail.save(f"{asset.thumbnail_token}.jpg", ContentFile(thumb_bytes), save=False)
    asset.save()
    return asset


def purge_post_media(post: Post) -> int:
    """Hard-delete a post's photos and their derivatives from storage (T-MEDIA-6).

    Called when the post is deleted. Soft-delete alone stops the serving path (the view
    re-checks the post), but the files themselves must leave the disk so a deleted
    photo does not linger on the volume or behind a stale cached URL. Removes both the
    full image and the thumbnail file, then drops the row. Returns the count purged.
    """
    to_remove: list[tuple[Storage, str]] = []
    count = 0
    for asset in post.media.all():
        if asset.image.name:
            to_remove.append((asset.image.storage, asset.image.name))
        if asset.thumbnail.name:
            to_remove.append((asset.thumbnail.storage, asset.thumbnail.name))
        asset.delete()  # drop the row inside the request transaction
        count += 1

    def _remove_files() -> None:
        for storage, name in to_remove:
            storage.delete(name)  # idempotent; swallows an already-missing file

    # Remove the files only after the surrounding transaction commits (security review
    # of #31): a rollback then cannot leave a live row pointing at a deleted file, and a
    # concurrent serve that already resolved an asset never opens a file this request
    # just unlinked. on_commit runs immediately when there is no open transaction.
    transaction.on_commit(_remove_files)
    return count
