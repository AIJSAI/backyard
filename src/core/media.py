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
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import MediaAsset, Post

# Formats accepted at open. HEIC is deliberately absent: the pillow-heif question is a
# wave-3 measurement gate, so a HEIC phone photo is re-encoded client-side or rejected
# here, never passed through undecoded.
_ALLOWED_INPUT_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "GIF"})
# Error, not warn, above this bound (TS-PP-3). Sized well above a real phone photo.
_MAX_PIXELS = 50_000_000
_FULL_MAX = (2048, 2048)
_THUMB_MAX = (400, 400)
_JPEG_QUALITY = 85
_OUTPUT_CONTENT_TYPE = "image/jpeg"
_MAX_ALT = 500


class MediaRejected(Exception):
    """The upload could not be safely decoded and re-encoded."""


def _decode(raw: bytes) -> Image.Image:
    """Open and validate an uploaded image, or raise MediaRejected. Enforces the
    format allowlist and the error-not-warn decompression-bomb limit."""
    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = _MAX_PIXELS
    try:
        with warnings.catch_warnings():
            # A decompression-bomb warning becomes an error, so a bomb is a rejected
            # upload rather than a log line that decoded anyway (TS-PP-3).
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            try:
                img = Image.open(io.BytesIO(raw))
                img.load()  # force a full decode so a truncated or bomb file fails here
            except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
                raise MediaRejected("image too large") from exc
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                raise MediaRejected("undecodable image") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous
    if img.format not in _ALLOWED_INPUT_FORMATS:
        raise MediaRejected(f"format {img.format!r} not accepted")
    return img


def _reencode(img: Image.Image, max_size: tuple[int, int]) -> bytes:
    """Apply EXIF orientation, flatten, downscale within a box, and re-encode to JPEG.
    The output is a fresh file with no EXIF, GPS, or XMP metadata (TM-9)."""
    oriented = ImageOps.exif_transpose(img)  # bake orientation before it is discarded
    flattened = oriented.convert("RGB")  # JPEG has no alpha or palette
    flattened.thumbnail(max_size)  # in place, preserves aspect ratio
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
