"""Member data export (S-704): your own history, and only yours.

The export is strictly the acting member's authored content, read from their own
reverse relations, so it can never include another member's posts, comments, or
photos. It is a documented zip and is never gated.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from PIL import Image

from core import export, media
from core.models import Comment, Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_TEST_PW = "a-Strong-passphrase-9"


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


def _jpeg() -> bytes:
    img = Image.new("RGB", (30, 30), (1, 2, 3))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _read_zip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


@pytest.fixture
def world() -> dict[str, object]:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    m_pod = Pod.objects.create(name="Maternal cousins")
    m_pod.yards.set([maternal])
    return {
        "m_pod": m_pod,
        "author": _member_with_user(m_pod, "Author"),
        "mate": _member_with_user(m_pod, "Mate"),
    }


def test_member_export_contains_only_own_content(world: dict[str, object]) -> None:
    author = world["author"]
    mate = world["mate"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(mate, Member)
    assert isinstance(m_pod, Pod)

    mine = Post.objects.create(author=author, pod=m_pod, body="my post one")
    theirs = Post.objects.create(author=mate, pod=m_pod, body="someone elses post")
    Comment.objects.create(author=author, post=theirs, body="my comment on their post")
    Comment.objects.create(author=mate, post=mine, body="their comment on my post")
    media.ingest_photo(post=mine, raw=_jpeg())

    files = _read_zip(export.build_member_export(author))
    posts = json.loads(files["posts.json"])
    comments = json.loads(files["comments.json"])
    media_index = json.loads(files["media.json"])

    assert {p["body"] for p in posts} == {"my post one"}  # only the author's posts
    assert "someone elses post" not in files["posts.json"].decode()
    assert {c["body"] for c in comments} == {"my comment on their post"}  # only their comments
    assert "their comment on my post" not in files["comments.json"].decode()
    assert len(media_index) == 1
    assert media_index[0]["file"] in files  # the photo bytes are in the zip
    manifest = json.loads(files["manifest.json"])
    assert manifest["format"] == export.EXPORT_FORMAT
    assert manifest["member"]["display_name"] == "Author"


def test_export_excludes_deleted(world: dict[str, object]) -> None:
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    Post.objects.create(author=author, pod=m_pod, body="kept post")
    gone = Post.objects.create(author=author, pod=m_pod, body="deleted post")
    from django.utils import timezone

    gone.deleted_at = timezone.now()
    gone.save(update_fields=["deleted_at"])
    posts = json.loads(_read_zip(export.build_member_export(author))["posts.json"])
    assert {p["body"] for p in posts} == {"kept post"}


def test_export_view_returns_a_zip(world: dict[str, object]) -> None:
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    Post.objects.create(author=author, pod=m_pod, body="exported")
    response = _client_for(author).get(reverse("export_data"))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    assert "attachment" in response["Content-Disposition"]
    body = b"".join(response.streaming_content)  # type: ignore[attr-defined]  # FileResponse streams
    files = _read_zip(body)
    assert "manifest.json" in files and "posts.json" in files


def test_export_requires_login() -> None:
    assert Client().get(reverse("export_data")).status_code == 302


def test_export_skips_a_missing_media_file(world: dict[str, object]) -> None:
    """Security review of #32 (LOW): a media file missing from storage is skipped, so
    the export never 500s on storage drift."""
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    post = Post.objects.create(author=author, pod=m_pod, body="post with a lost photo")
    asset = media.ingest_photo(post=post, raw=_jpeg())
    asset.image.storage.delete(asset.image.name)  # remove the file, leave the DB row
    files = _read_zip(export.build_member_export(author))  # must not raise
    assert json.loads(files["media.json"]) == []  # the missing file was skipped


def test_export_includes_a_video_source(world: dict[str, object]) -> None:
    """S-704 regression (caught live on the persistent instance): a member who posted a
    VIDEO must get it in their export. A video exports its metadata-stripped SOURCE original
    (retained for export, T-MEDIA-6), never its `image` (empty by design). Before the fix
    the loop opened `image` for every asset, and a video's empty image raised ValueError
    (not the caught FileNotFoundError), 500-ing the whole export for any video-poster."""
    from django.core.files.base import ContentFile

    from core.models import MediaAsset

    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    post = Post.objects.create(author=author, pod=m_pod, body="a clip from the yard")
    asset = MediaAsset.objects.create(
        post=post, media_kind=MediaAsset.VIDEO, content_type="video/mp4"
    )
    asset.source.save(f"{asset.token}.mp4", ContentFile(b"stripped-source-bytes"), save=True)

    files = _read_zip(export.build_member_export(author))  # must not raise
    media_index = json.loads(files["media.json"])
    assert len(media_index) == 1
    assert media_index[0]["file"].endswith(".mp4")  # the video source, not a .jpg
    assert files[media_index[0]["file"]] == b"stripped-source-bytes"


def test_export_excludes_rehosted_link_preview_images(world: dict[str, object]) -> None:
    """A re-hosted link-preview og:image is a copy of a third party's image, not the
    member's own content, so it never appears in their personal data export (S-301)."""
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    post = Post.objects.create(author=author, pod=m_pod, body="a post with a link card")
    media.ingest_photo(post=post, raw=_jpeg())  # the member's own photo: exported
    link_asset = media.ingest_link_preview_image(post=post, raw=_jpeg())  # re-hosted: not
    assert link_asset is not None
    files = _read_zip(export.build_member_export(author))
    media_index = json.loads(files["media.json"])
    assert len(media_index) == 1  # only the member's own photo
    assert f"media/{link_asset.token}.jpg" not in files  # the re-hosted image is absent
