"""Measure ffmpeg transcode latency on THIS hardware (S-402, ADR-002 gate).

Run this on the real self-hosted target box (a Beelink/N100-class mini-PC or whatever
the instance runs on), NOT the dev machine: the ADR-002 gate and S-402's "post-to-visible
latency is minutes at most on target hardware" are measurements, and this command is how
they are measured, honestly and repeatably. It synthesizes representative 1080p sources
(H.264 like an Android clip, HEVC like an iPhone clip, at 30s and 60s), runs the exact
production transcode (core.transcoding.transcode), and reports wall-clock latency and the
speed relative to realtime. The output is the evidence for the wave-3 close receipt.

The encoder is whatever the box is configured for: software libx264 by default, or the
Intel Quick Sync path when BACKYARD_FFMPEG_VCODEC=h264_qsv (and /dev/dri is passed). The
command prints which is active so the receipt records the measured configuration.
"""

from __future__ import annotations

import os
import subprocess  # noqa: S404  # fixed argv, no shell, synthesizing local test sources
import tempfile
import time
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand

from core import transcoding

# (label, ffmpeg source video codec, duration seconds, frame size). HEVC is the iPhone
# default and the more expensive decode, so it is the realistic worst case.
_SOURCES: list[tuple[str, str, int, str]] = [
    ("h264-1080p-30s", "libx264", 30, "1920x1080"),
    ("hevc-1080p-30s", "libx265", 30, "1920x1080"),
    ("h264-1080p-60s", "libx264", 60, "1920x1080"),
    ("hevc-1080p-60s", "libx265", 60, "1920x1080"),
]


class Command(BaseCommand):
    help = "Measure ffmpeg transcode latency on this (target) hardware — the ADR-002/S-402 gate."

    def handle(self, *args: Any, **options: Any) -> None:
        encoder = os.environ.get("BACKYARD_FFMPEG_VCODEC", "libx264")
        self.stdout.write(f"encoder in use: {encoder}  (BACKYARD_FFMPEG_VCODEC)")
        self.stdout.write(
            f"cap: clips are hard-limited to {transcoding.MAX_VIDEO_DURATION_S}s at ingest"
        )
        self.stdout.write("-" * 64)
        worst = 0.0
        with tempfile.TemporaryDirectory() as workdir:
            wd = Path(workdir)
            for label, vcodec, duration, size in _SOURCES:
                src = wd / f"{label}.mp4"
                if not self._synth(src, vcodec, duration, size):
                    self.stdout.write(
                        f"{label:20s} SKIPPED (encoder {vcodec} unavailable in this ffmpeg)"
                    )
                    continue
                out = wd / f"{label}-out.mp4"
                poster = wd / f"{label}-poster.jpg"
                start = time.monotonic()
                try:
                    transcoding.transcode(str(src), str(out), str(poster))
                except transcoding.FfmpegError as exc:
                    self.stdout.write(f"{label:20s} FAILED: {exc}")
                    continue
                elapsed = time.monotonic() - start
                worst = max(worst, elapsed)
                ratio = duration / elapsed if elapsed else 0.0
                kib = out.stat().st_size // 1024
                self.stdout.write(
                    f"{label:20s} {elapsed:6.1f}s wall  {ratio:5.1f}x realtime  {kib} KiB"
                )
        self.stdout.write("-" * 64)
        self.stdout.write(f"worst-case latency this run: {worst:.1f}s")
        verdict = "PASS (minutes at most)" if worst <= 300 else "REVIEW (over 5 min — investigate)"
        self.stdout.write(f"S-402 latency gate: {verdict}")

    def _synth(self, dst: Path, vcodec: str, duration: int, size: str) -> bool:
        """Synthesize one representative source clip. Returns False if the box's ffmpeg
        lacks the encoder (e.g. libx265 absent), so the run degrades rather than aborts."""
        result = subprocess.run(  # noqa: S603  # fixed argv, no shell; ffmpeg by name (S607 per-file)
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"testsrc=duration={duration}:size={size}:rate=30",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:duration={duration}",
                "-c:v",
                vcodec,
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
                "-y",
                str(dst),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
