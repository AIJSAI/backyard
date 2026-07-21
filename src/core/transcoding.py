"""Hardened ffmpeg/ffprobe for video ingest and transcode (S-402, TS-PP-1/2, TM-9).

A member-uploaded video is hostile bytes handed to a parser with a long CVE history
and, worse, demuxers that can turn a file into a local-read or fetch primitive. Every
ffmpeg and ffprobe invocation in the app goes through this module so the hardening is
in one place and cannot drift:

- **`-protocol_whitelist file`** drops http/tcp/rtp, closing the external-fetch half of
  TS-PP-1 (a crafted playlist or concat entry cannot make ffmpeg reach the network).
- **`-f mov,mp4,m4a,3gp,3g2,mj2`** forces the exact ISOBMFF demuxer, so the playlist and
  concat demuxers never engage on an upload that lies about being a video. We first
  reject anything whose magic bytes are not an `ftyp` box (`looks_like_isobmff`), so the
  forced demuxer only ever sees plausible input; forcing it on an m3u8 is a hard error.
- **`-enable_drefs` is never passed** (it stays off), so an MP4 `dref` external-data
  atom cannot read `/data/secret_key` off the box (the local-read half of TS-PP-1).
- **`-nostdin`** on every ffmpeg call so a byte in the stream can never be read as a key.
- **wall-clock timeout + CPU/output-size rlimits** (TS-PP-2) on the subprocess: a
  pathological clip fails the job with a clear message instead of wedging the worker, and
  cannot exhaust CPU time or disk. Physical memory is bounded by the container
  `mem_limit`/`pids_limit` (TS-CO-6) — deliberately not an RLIMIT_AS, which limits virtual
  address space and breaks legitimate multi-threaded HD encoding.

The re-encode is the TM-9 gate for video the same way Pillow's is for photos: the served
rendition is a fresh H.264 file, `-map_metadata -1` drops the container location atoms
(QuickTime/MP4 `com.apple.quicktime.location.ISO6709`), and the stored `source` is a
metadata-stripped remux, never the raw upload.
"""

from __future__ import annotations

import logging
import os
import subprocess  # noqa: S404  # every call site uses a fixed argv, never a shell
import tempfile
from pathlib import Path

from django.core.files import File

logger = logging.getLogger(__name__)

# The single ISOBMFF demuxer that handles MP4 and QuickTime/MOV. Forcing it means the
# playlist, concat, and every other demuxer never engage on an upload (TS-PP-1).
_CONTAINER_DEMUXER = "mov,mp4,m4a,3gp,3g2,mj2"

# Video policy caps, the documented "size and duration cap" of S-402. Sized for short
# family clips; a founder-tunable value like the other wave-boundary defaults.
MAX_VIDEO_BYTES = 100 * 1024 * 1024  # 100 MB upload ceiling (the Caddy body cap is TS-CA-4)
MAX_VIDEO_DURATION_S = 60  # a clip of the kids, not a movie

# The committed encoder is software libx264 (portable, runs in CI and on any box). On the
# target Intel N100/N305, BACKYARD_FFMPEG_VCODEC=h264_qsv moves the encode onto the Quick
# Sync fixed-function engine; the ADR-002 latency gate is measured there, not on the dev
# machine. The output is a 720p H.264 + AAC mp4 with faststart for progressive play.
_VCODEC = os.environ.get("BACKYARD_FFMPEG_VCODEC", "libx264")
_OUTPUT_HEIGHT = 720
_OUTPUT_WIDTH = 1280

# TS-PP-2 limits. The wall-clock timeout is the primary control; the rlimits bound CPU
# time and output size per process. Memory is deliberately NOT bounded by an RLIMIT_AS
# here: multi-threaded libx264 at HD reserves far more VIRTUAL address space (thread
# stacks + per-thread glibc arenas) than it ever touches physically, so a 2GB RLIMIT_AS
# fails a legitimate 1080p transcode at encoder-open ("Error while opening encoder") while
# a small clip passes — a real bug the latency harness caught. Physical memory (the metric
# that actually OOMs the box) is bounded by the container mem_limit (TS-CO-6), which is the
# correct control; RLIMIT_AS is redundant with it and harmful, so it is gone.
_TRANSCODE_TIMEOUT_S = 300
# The probe and the stream-copy strip run web-synchronously on upload, so their timeout is
# tighter: a valid short clip probes/remuxes in well under a second, and a shorter cap
# shrinks the window a crafted slow-to-demux upload can tie up a gunicorn worker for
# (security review MEDIUM-1). _MAX_VIDEOS caps how many run per request.
_PROBE_TIMEOUT_S = 20
_RLIMIT_CPU_S = 600
_RLIMIT_FSIZE = 600 * 1024 * 1024


class FfmpegError(Exception):
    """An ffmpeg/ffprobe step failed, timed out, or refused the input."""


def looks_like_isobmff(raw: bytes) -> bool:
    """True if the bytes begin with an ISOBMFF `ftyp` box (MP4/MOV). This is the magic
    check done before ffmpeg ever runs, so the forced demuxer only sees plausible input
    and a lying upload (an m3u8, an AVI, HTML) is rejected upfront (TS-PP-1, S-402)."""
    return len(raw) >= 12 and raw[4:8] == b"ftyp"


def _rlimits() -> None:  # pragma: no cover - runs only in the forked child
    """Applied in the child before exec (POSIX). Bounds CPU time and output file size
    (TS-PP-2); physical memory is bounded by the container mem_limit (TS-CO-6), not an
    RLIMIT_AS, which would break multi-threaded HD encoding — see the constants above."""
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (_RLIMIT_CPU_S, _RLIMIT_CPU_S))
    resource.setrlimit(resource.RLIMIT_FSIZE, (_RLIMIT_FSIZE, _RLIMIT_FSIZE))


def _run(argv: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    """Run a fixed ffmpeg/ffprobe argv with the wall-clock timeout and rlimits. Never a
    shell; raises FfmpegError on timeout so a hang becomes a failed job, not a wedge."""
    try:
        return subprocess.run(  # noqa: S603  # fixed argv, shell=False, hardened flags
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            preexec_fn=_rlimits,  # noqa: PLW1509  # intentional child rlimits (TS-PP-2)
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise FfmpegError(f"timed out after {timeout}s") from exc


def probe_duration_seconds(src: str) -> float:
    """Duration of an ISOBMFF file in seconds, via ffprobe with the hardened input flags.
    Raises FfmpegError if the file will not probe as the forced container."""
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-f",
            _CONTAINER_DEMUXER,
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            src,
        ],
        timeout=_PROBE_TIMEOUT_S,
    )
    if result.returncode != 0:
        raise FfmpegError(f"ffprobe rejected the file: {result.stderr.strip()[:200]}")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise FfmpegError("ffprobe returned no duration") from exc


def _input_flags(src: str) -> list[str]:
    """The hardened input half every ffmpeg call shares: no stdin, only the file
    protocol, the forced ISOBMFF demuxer, and (by omission) no dref following."""
    return [
        "-nostdin",
        "-v",
        "error",
        "-protocol_whitelist",
        "file",
        "-f",
        _CONTAINER_DEMUXER,
        "-i",
        src,
    ]


def strip_metadata(src: str, dst: str) -> None:
    """Remux to `dst` dropping all container/stream metadata (`-map_metadata -1`) with a
    stream copy, no re-encode. This is the ingest strip: the retained source is clean of
    the QuickTime/MP4 location atoms before any transcode or poster runs (S-402, TM-9)."""
    result = _run(
        [
            "ffmpeg",
            *_input_flags(src),
            "-map_metadata",
            "-1",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            "-y",
            dst,
        ],
        timeout=_PROBE_TIMEOUT_S,
    )
    if result.returncode != 0:
        raise FfmpegError(f"metadata strip failed: {result.stderr.strip()[:200]}")


def transcode(src: str, video_dst: str, poster_dst: str) -> None:
    """Re-encode `src` to a 720p H.264/AAC rendition at `video_dst` and a poster frame at
    `poster_dst`, both metadata-stripped. Duration is hard-capped with `-t` so even a
    source that slipped a longer duration past ingest cannot produce a long rendition."""
    scale = (
        f"scale='min({_OUTPUT_WIDTH},iw)':'min({_OUTPUT_HEIGHT},ih)'"
        ":force_original_aspect_ratio=decrease"
    )
    rendition = _run(
        [
            "ffmpeg",
            *_input_flags(src),
            "-map_metadata",
            "-1",
            "-t",
            str(MAX_VIDEO_DURATION_S),
            "-vf",
            scale,
            "-c:v",
            _VCODEC,
            "-preset",
            "fast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            "-y",
            video_dst,
        ],
        timeout=_TRANSCODE_TIMEOUT_S,
    )
    if rendition.returncode != 0:
        raise FfmpegError(f"transcode failed: {rendition.stderr.strip()[:200]}")
    poster = _run(
        [
            "ffmpeg",
            *_input_flags(src),
            "-map_metadata",
            "-1",
            "-frames:v",
            "1",
            "-q:v",
            "3",
            "-y",
            poster_dst,
        ],
        timeout=_PROBE_TIMEOUT_S,
    )
    if poster.returncode != 0:
        raise FfmpegError(f"poster frame failed: {poster.stderr.strip()[:200]}")


def transcode_asset(asset_id: int) -> None:
    """Transcode one pending video asset and flip it to DONE, or FAILED if the hardened
    ffmpeg refuses the clip (S-402's "never a silent failure"). Re-resolves the asset
    live from its id (TS-DJ-11 shape): a deleted or already-processed asset no-ops."""
    from .models import MediaAsset

    asset = MediaAsset.objects.filter(
        pk=asset_id, media_kind=MediaAsset.VIDEO, deleted_at__isnull=True
    ).first()
    if asset is None or not asset.source:
        return
    src_path = asset.source.path
    with tempfile.TemporaryDirectory() as workdir:
        video_dst = str(Path(workdir) / "rendition.mp4")
        poster_dst = str(Path(workdir) / "poster.jpg")
        try:
            transcode(src_path, video_dst, poster_dst)
        except FfmpegError as exc:
            asset.transcode_status = MediaAsset.FAILED
            asset.save(update_fields=["transcode_status"])
            logger.warning("transcode failed for media asset %s: %s", asset_id, exc)
            return
        # A post-delete may have landed while we transcoded (seconds). Re-check before
        # writing the rendition/poster so we do not leave orphan files for a post whose
        # purge already ran and saw these fields empty (T-MEDIA-6 race, review LOW-1).
        if not MediaAsset.objects.filter(pk=asset_id, deleted_at__isnull=True).exists():
            return
        with open(video_dst, "rb") as rendition:
            asset.video.save(f"{asset.token}.mp4", File(rendition), save=False)
        with open(poster_dst, "rb") as poster:
            asset.thumbnail.save(f"{asset.thumbnail_token}.jpg", File(poster), save=False)
        asset.transcode_status = MediaAsset.DONE
        asset.save(update_fields=["video", "thumbnail", "transcode_status"])
