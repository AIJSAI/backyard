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
    files = _read_zip(response.content)
    assert "manifest.json" in files and "posts.json" in files


def test_export_requires_login() -> None:
    assert Client().get(reverse("export_data")).status_code == 302
