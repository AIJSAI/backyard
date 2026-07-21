# Measuring transcode latency on target hardware (S-402, ADR-002 gate)

Wave 3's close depends on one measurement that cannot be faked on the dev machine:
how long the video transcode takes on the real self-hosted box (ADR-002's
carried-forward gate; S-402's "post-to-visible latency is minutes at most on
target hardware"). This is how to take it, honestly and repeatably.

## What counts as target hardware

Any always-on box a family would actually self-host Backyard on — a Beelink or
other N100/N-class mini-PC, a small NUC, a home server. Not a laptop you close,
not the dev machine, not an ephemeral CI runner. The committed encoder is
software libx264, so any such box produces a valid number; an Intel box can move
the encode onto Quick Sync (below) for a faster one.

## Run it

On the target box, with the image/venv that ships ffmpeg:

```sh
# In the compose stack (the worker image ships ffmpeg):
docker compose exec worker python manage.py measure_transcode

# …or directly in the app venv on the box:
python manage.py measure_transcode
```

It synthesizes representative 1080p sources (H.264 and HEVC, at 30s and 60s),
runs the exact production transcode on each, and prints wall-clock latency, speed
vs realtime, and a PASS/REVIEW verdict against the "minutes at most" bar.

## Optional: Intel Quick Sync

On an Intel N100/N305 box, hardware encode is a large speedup. Pass the render
node into the worker container and set the encoder:

```yaml
# docker-compose override on the box:
worker:
  devices: ["/dev/dri:/dev/dri"]
  environment:
    BACKYARD_FFMPEG_VCODEC: h264_qsv
```

The box also needs `intel-media-driver` (iHD) and a QSV-capable ffmpeg in the
image; verify the video engine actually engages with `vainfo` / `intel_gpu_top`
before trusting the number (a missing driver silently falls back to software).
Confirm "Intel Quick Sync Video: Yes" on Intel ARK for the exact SKU.

## Record the receipt

Paste the command's output into `docs/receipts/<date>-wave-3-close.md` alongside
the full-gate run and the compose live-repro, and note the box (CPU, RAM,
encoder). That receipt, plus flipping S-401/S-402/S-403/S-704/S-802 to `tested`
in `stories/stories.yaml`, closes wave 3. The number is measured, never claimed.
