"""Video ingest, transcode, and access-checked serving (S-402, TS-PP-1/2, TM-9).

The security core mirrors the photo path: an uploaded video is validated and rejected
upfront if it is over the size/duration cap or not an ISOBMFF container; its location
atoms are stripped at ingest; it is re-encoded on the worker to the one served rendition;
and every derivative (rendition and poster) is reachable only through the access-checked
path, so a cross-yard member gets the same 404 as an unknown token.

The tests that need the real ffmpeg binary are marked `requires_ffmpeg` and run in CI and
the container (where ffmpeg is installed); the isolation, reject-upfront, pending, and
purge tests are deliberately ffmpeg-free so the security invariants are exercised
everywhere, including a dev machine without ffmpeg.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import media, transcoding
from core.models import MediaAsset, Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_TEST_PW = "a-Strong-passphrase-9"

_HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
requires_ffmpeg = pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg/ffprobe not installed")

# A minimal ISOBMFF header: an `ftyp` box with the mp42 brand. Enough to pass the magic
# check, not a decodable movie, so ffmpeg refuses it (used for the FAILED path).
_FTYP_ONLY = bytes([0, 0, 0, 0x18]) + b"ftypmp42" + bytes(12)


@dataclass
class World:
    maternal: Yard
    m_pod: Pod
    author: Member
    pod_mate: Member
    other: Member
    post: Post


def _member_with_user(pod: Pod, name: str) -> Member:
    user = User.objects.create_user(username=name.lower(), password=_TEST_PW)
    member = Member.objects.create(display_name=name, user=user)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _client_for(member: Member) -> Client:
    assert member.user is not None
    c = Client()
    c.force_login(member.user, backend=_BACKEND)
    return c


def _make_video(path: Path, *, duration: float = 1.0, with_location: bool = True) -> bytes:
    """Synthesize a small MP4 with (by default) an iPhone-style location atom, a faithful
    reproducible stand-in for a real device clip with known location (S-402 corpus)."""
    args = [
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size=320x240:rate=10",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration}",
    ]
    if with_location:
        args += [
            "-metadata",
            "location=+40.7128-074.0060/",
            "-metadata",
            "location-eng=+40.7128-074.0060/",
        ]
    args += [
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        "-y",
        str(path),
    ]
    subprocess.run(args, check=True, capture_output=True)
    return path.read_bytes()


def _format_tags(data: bytes, tmp_path: Path) -> str:
    """The container metadata tags of some MP4 bytes, lowercased, for a location check."""
    probe = tmp_path / "probe.mp4"
    probe.write_bytes(data)
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-f",
            "mov,mp4,m4a,3gp,3g2,mj2",
            "-show_entries",
            "format_tags",
            "-of",
            "default=noprint_wrappers=1",
            str(probe),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.lower()


@pytest.fixture
def world() -> World:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    m_pod = Pod.objects.create(name="Maternal cousins")
    m_pod.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal cousins")
    p_pod.yards.set([paternal])
    author = _member_with_user(m_pod, "Author")
    post = Post.objects.create(author=author, pod=m_pod, body="a maternal post")
    post.audience_yards.set([maternal])
    return World(
        maternal=maternal,
        m_pod=m_pod,
        author=author,
        pod_mate=_member_with_user(m_pod, "PodMate"),
        other=_member_with_user(p_pod, "Other"),
        post=post,
    )


def _done_video_asset(post: Post) -> MediaAsset:
    """A DONE video asset with placeholder rendition/poster/source files. Content is
    irrelevant to the isolation and purge invariants (they act before the file is read),
    so this keeps those tests ffmpeg-free."""
    asset = MediaAsset(
        post=post,
        media_kind=MediaAsset.VIDEO,
        content_type="video/mp4",
        transcode_status=MediaAsset.DONE,
    )
    asset.source.save(f"{asset.token}.mp4", ContentFile(b"source-bytes"), save=False)
    asset.video.save(f"{asset.token}.mp4", ContentFile(_FTYP_ONLY), save=False)
    asset.thumbnail.save(
        f"{asset.thumbnail_token}.jpg", ContentFile(b"\xff\xd8\xff\xd9"), save=False
    )
    asset.save()
    return asset


# --- validation: reject upfront, never silent (ffmpeg-free) ---


def test_validate_rejects_oversize(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transcoding, "MAX_VIDEO_BYTES", 100)
    with pytest.raises(media.MediaRejected, match="too large"):
        media.validate_video(b"\x00" * 200)


def test_validate_rejects_non_isobmff() -> None:
    with pytest.raises(media.MediaRejected, match="not a video"):
        media.validate_video(b"this is plainly not a video file, no ftyp box here at all")


@requires_ffmpeg
def test_validate_rejects_overlong(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transcoding, "MAX_VIDEO_DURATION_S", 0.5)
    raw = _make_video(tmp_path / "long.mp4", duration=2.0, with_location=False)
    with pytest.raises(media.MediaRejected, match="too long"):
        media.validate_video(raw)


@requires_ffmpeg
def test_validate_accepts_a_normal_clip(tmp_path: Path) -> None:
    raw = _make_video(tmp_path / "ok.mp4", duration=1.0, with_location=False)
    assert media.validate_video(raw) == pytest.approx(1.0, abs=0.3)


# --- ingest: metadata strip (the S-402 corpus assertion) ---


@requires_ffmpeg
def test_ingest_strips_location_from_stored_source(world: World, tmp_path: Path) -> None:
    raw = _make_video(tmp_path / "loc.mp4", with_location=True)
    # The synthesized upload really does carry a location tag before ingest.
    assert "location" in _format_tags(raw, tmp_path)

    asset = media.ingest_video(post=world.post, raw=raw)
    assert asset.media_kind == MediaAsset.VIDEO
    assert asset.transcode_status == MediaAsset.PENDING

    stored = Path(asset.source.path).read_bytes()
    tags = _format_tags(stored, tmp_path)
    assert "location" not in tags
    assert "40.7128" not in tags


# --- transcode: rendition + poster, clean, FAILED on refusal ---


@requires_ffmpeg
def test_transcode_produces_clean_rendition_and_poster(world: World, tmp_path: Path) -> None:
    raw = _make_video(tmp_path / "loc.mp4", with_location=True)
    asset = media.ingest_video(post=world.post, raw=raw)

    transcoding.transcode_asset(asset.id)

    asset.refresh_from_db()
    assert asset.transcode_status == MediaAsset.DONE
    assert asset.video.name and asset.thumbnail.name
    rendition = Path(asset.video.path).read_bytes()
    assert rendition[4:8] == b"ftyp"  # a real mp4
    assert "location" not in _format_tags(rendition, tmp_path)


@requires_ffmpeg
def test_transcode_marks_failed_on_a_clip_ffmpeg_refuses(world: World) -> None:
    # A source that passes the magic check but is not a decodable movie: ffmpeg refuses,
    # and the asset flips to FAILED rather than wedging or silently vanishing (S-402).
    asset = MediaAsset(
        post=world.post,
        media_kind=MediaAsset.VIDEO,
        content_type="video/mp4",
        transcode_status=MediaAsset.PENDING,
    )
    asset.source.save(f"{asset.token}.mp4", ContentFile(_FTYP_ONLY), save=False)
    asset.save()

    transcoding.transcode_asset(asset.id)

    asset.refresh_from_db()
    assert asset.transcode_status == MediaAsset.FAILED
    assert not asset.video.name


def test_transcode_skips_writing_if_deleted_mid_transcode(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # LOW-1: a delete landing while the worker transcodes must not leave orphan files.
    # Simulate the race — transcode "succeeds" but the row is soft-deleted before we save.
    asset = MediaAsset(
        post=world.post,
        media_kind=MediaAsset.VIDEO,
        content_type="video/mp4",
        transcode_status=MediaAsset.PENDING,
    )
    asset.source.save(f"{asset.token}.mp4", ContentFile(_FTYP_ONLY), save=False)
    asset.save()

    def _delete_during(src: str, video_dst: str, poster_dst: str) -> None:
        Path(video_dst).write_bytes(_FTYP_ONLY)
        Path(poster_dst).write_bytes(b"\xff\xd8\xff\xd9")
        MediaAsset.objects.filter(pk=asset.pk).update(deleted_at=timezone.now())

    monkeypatch.setattr(transcoding, "transcode", _delete_during)
    transcoding.transcode_asset(asset.id)

    asset.refresh_from_db()
    assert asset.transcode_status == MediaAsset.PENDING  # not flipped to DONE
    assert not asset.video.name  # no rendition file moved into storage — no orphan


def test_transcode_asset_noops_on_deleted_asset(world: World) -> None:
    # Re-resolves live (TS-DJ-11 shape): a soft-deleted asset's job does nothing, no raise.
    asset = _done_video_asset(world.post)
    asset.transcode_status = MediaAsset.PENDING
    asset.deleted_at = timezone.now()
    asset.save()
    transcoding.transcode_asset(asset.id)  # must not raise
    asset.refresh_from_db()
    assert asset.transcode_status == MediaAsset.PENDING  # untouched


# --- serving: access-checked, per-derivative isolation (ffmpeg-free) ---


def test_video_cross_yard_is_404_for_both_tokens(world: World) -> None:
    asset = _done_video_asset(world.post)  # maternal post
    other = _client_for(world.other)  # paternal member
    for token in (asset.token, asset.thumbnail_token):
        assert other.get(reverse("serve_media", args=[token])).status_code == 404


def test_video_rendition_and_poster_serve_to_an_in_yard_member(world: World) -> None:
    asset = _done_video_asset(world.post)
    mate = _client_for(world.pod_mate)
    rendition = mate.get(reverse("serve_media", args=[asset.token]))
    poster = mate.get(reverse("serve_media", args=[asset.thumbnail_token]))
    assert rendition.status_code == 200
    assert rendition["Content-Type"] == "video/mp4"
    assert rendition["X-Content-Type-Options"] == "nosniff"
    assert poster.status_code == 200
    assert poster["Content-Type"] == "image/jpeg"


def test_pending_video_token_404s(world: World) -> None:
    # A video still transcoding has no rendition file; fetching its token fails closed to
    # 404, never a 500 (the empty FileField raises ValueError, caught in the view).
    asset = MediaAsset(
        post=world.post,
        media_kind=MediaAsset.VIDEO,
        content_type="video/mp4",
        transcode_status=MediaAsset.PENDING,
    )
    asset.source.save(f"{asset.token}.mp4", ContentFile(b"src"), save=False)
    asset.save()
    owner = _client_for(world.author)
    assert owner.get(reverse("serve_media", args=[asset.token])).status_code == 404


# --- composer: attach + enqueue; reject upfront ---


@requires_ffmpeg
def test_compose_attaches_a_video_and_enqueues_transcode(world: World, tmp_path: Path) -> None:
    raw = _make_video(tmp_path / "clip.mp4", with_location=True)
    upload = SimpleUploadedFile("clip.mp4", raw, content_type="video/mp4")
    client = _client_for(world.author)
    with mock.patch("core.tasks.transcode_video.defer") as defer:
        resp = client.post(
            reverse("compose"),
            {"body": "a clip of the kids", "pod_id": world.m_pod.id, "videos": upload},
        )
    assert resp.status_code == 302
    asset = MediaAsset.objects.get(media_kind=MediaAsset.VIDEO)
    assert asset.transcode_status == MediaAsset.PENDING
    defer.assert_called_once_with(asset_id=asset.id)


def test_compose_rejects_oversize_video_upfront_with_no_post(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(transcoding, "MAX_VIDEO_BYTES", 100)
    before = Post.objects.count()
    upload = SimpleUploadedFile("big.mp4", b"\x00" * 500, content_type="video/mp4")
    client = _client_for(world.author)
    resp = client.post(
        reverse("compose"),
        {"body": "too big", "pod_id": world.m_pod.id, "videos": upload},
    )
    assert resp.status_code == 200  # re-rendered feed with the error, not a redirect
    assert b"too large" in resp.content
    assert Post.objects.count() == before  # the post was never created
    assert not MediaAsset.objects.filter(media_kind=MediaAsset.VIDEO).exists()


# --- purge: every derivative leaves the disk (T-MEDIA-6, ffmpeg-free) ---


def test_delete_post_purges_all_video_files(
    world: World,
    django_capture_on_commit_callbacks: Callable[..., AbstractContextManager[list[object]]],
) -> None:
    asset = _done_video_asset(world.post)
    paths = [Path(asset.source.path), Path(asset.video.path), Path(asset.thumbnail.path)]
    assert all(p.exists() for p in paths)
    with django_capture_on_commit_callbacks(execute=True):
        media.purge_post_media(world.post)
    assert not any(p.exists() for p in paths)
    assert not MediaAsset.objects.filter(pk=asset.pk).exists()
