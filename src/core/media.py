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
import tempfile
import warnings
from pathlib import Path

from django.core.files import File
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError

from . import transcoding
from .models import MediaAsset, Post

# Formats accepted at open. HEIC is deliberately absent (the wave-3 pillow-heif decision):
# the composer's client-side resize (feed.html) converts HEIC to JPEG in browsers that can
# decode it (Safari/iOS) before upload, and a HEIC that reaches here undecoded — from a
# browser that could not convert it — is rejected rather than passed through. v1 relies on
# that client conversion and does NOT ship the pillow-heif dependency; revisit only if the
# seed pod hits raw-HEIC rejections in practice.
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
_VIDEO_OUTPUT_CONTENT_TYPE = "video/mp4"
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


def validate_video(raw: bytes) -> float:
    """Reject an upload over the size or duration cap, or not an ISOBMFF container, with
    a clear member-facing MediaRejected message; return its duration in seconds (S-402).

    The single video validation gate. The composer calls it upfront so a bad clip fails
    before the post is created ("rejected upfront, never a silent failure"), and
    ingest_video calls it again so the stored path is never reachable without it. The
    magic-byte check happens before ffprobe runs, so the hardened forced-demuxer probe
    only ever sees a plausible ISOBMFF file (TS-PP-1).
    """
    if len(raw) > transcoding.MAX_VIDEO_BYTES:
        cap_mb = transcoding.MAX_VIDEO_BYTES // (1024 * 1024)
        raise MediaRejected(f"That clip is too large. Keep it under {cap_mb} MB.")
    if not transcoding.looks_like_isobmff(raw):
        raise MediaRejected("That file is not a video we can play. Try an MP4 or a phone clip.")
    with tempfile.TemporaryDirectory() as workdir:
        raw_path = Path(workdir) / "upload"
        raw_path.write_bytes(raw)
        try:
            duration = transcoding.probe_duration_seconds(str(raw_path))
        except transcoding.FfmpegError as exc:
            raise MediaRejected("That file is not a video we can play.") from exc
    if duration > transcoding.MAX_VIDEO_DURATION_S:
        cap_s = transcoding.MAX_VIDEO_DURATION_S
        raise MediaRejected(f"That clip is too long. Keep it under {cap_s} seconds.")
    return duration


def ingest_video(*, post: Post, raw: bytes, alt_text: str = "") -> MediaAsset:
    """Validate and store one uploaded video as a PENDING asset on the post (S-402).

    The stored source is metadata-stripped at ingest (TM-9), before any transcode or
    poster runs, so the retained original carries no QuickTime/MP4 location atom; the
    worker later produces the served H.264 rendition and a poster. content_type is pinned
    to the eventual rendition, never the client's claim.
    """
    validate_video(raw)
    with tempfile.TemporaryDirectory() as workdir:
        raw_path = Path(workdir) / "upload"
        raw_path.write_bytes(raw)
        clean_path = Path(workdir) / "clean.mp4"
        try:
            transcoding.strip_metadata(str(raw_path), str(clean_path))
        except transcoding.FfmpegError as exc:
            raise MediaRejected("That video could not be processed.") from exc
        asset = MediaAsset(
            post=post,
            media_kind=MediaAsset.VIDEO,
            content_type=_VIDEO_OUTPUT_CONTENT_TYPE,
            transcode_status=MediaAsset.PENDING,
            alt_text=alt_text.strip()[:_MAX_ALT],
        )
        with open(clean_path, "rb") as clean:
            # Named by the token but stored under media/source/, which no route serves;
            # only the rendition (token) and poster (thumbnail_token) are ever reachable.
            asset.source.save(f"{asset.token}.mp4", File(clean), save=False)
        asset.save()
    return asset


def purge_post_media(post: Post) -> int:
    """Hard-delete a post's media and every derivative from storage (T-MEDIA-6).

    Called when the post is deleted. Soft-delete alone stops the serving path (the view
    re-checks the post), but the files themselves must leave the disk so deleted media
    does not linger on the volume or behind a stale cached URL. Removes every stored file
    a photo or video carries (image, thumbnail, video source, and rendition), then drops
    the row. Returns the count purged.
    """
    to_remove: list[tuple[Storage, str]] = []
    count = 0
    for asset in post.media.all():
        for field in (asset.image, asset.thumbnail, asset.source, asset.video):
            if field.name:
                to_remove.append((field.storage, field.name))
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
