"""ONE picker, and a server that accepts what phones actually send (owner direction 4).

The composer offered two stacked native "Choose Files / No file chosen" controls, which
made the place a family says something read as an upload form, and asked which KIND of
thing you were about to share before you had chosen it. It is one control now, and these
pin the three things that has to be true of:

  ROUTING   both kinds arrive under one field and reach the right gate. The signals are
            client-controlled, so the split is routing and never validation — a file that
            lies about itself must still be rejected by the gate it lands in.
  HEIC      a HEIC still is accepted, because that is what an iPhone photograph IS. It
            used to be rejected outright from any browser that could not convert it in
            JavaScript first, which is every browser except Safari (BY-14).
  LIMITS    the size and count ceilings are unchanged and are still said in plain words.

The `capture` attribute is asserted ABSENT: it forces the camera open and hides the photo
library, which is the wrong default for a family posting the picture they already took,
and it is the one thing in the design report the owner explicitly rejected.
"""

from __future__ import annotations

import io
import re

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from django.test import Client
from django.urls import reverse
from PIL import Image

from core.feed_views import _MAX_PHOTO_BYTES, _MAX_PHOTOS, _split_media
from core.models import MediaAsset, Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_PW = "a-Strong-passphrase-9"
_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _image_bytes(fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (30, 92, 70)).save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def world() -> dict[str, object]:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Cousins")
    pod.yards.set([yard])
    user = User.objects.create_user(username="poster", password=_PW)
    member = Member.objects.create(display_name="Ann Poster", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return {"client": client, "pod": pod, "member": member}


def _compose(world: dict[str, object], **extra: object) -> object:
    client, pod = world["client"], world["pod"]
    assert isinstance(client, Client) and isinstance(pod, Pod)
    return client.post(reverse("compose"), {"body": "hello", "pod_id": pod.id, **extra})


# --- the control itself ----------------------------------------------------------


def test_the_composer_offers_exactly_one_media_control(world: dict[str, object]) -> None:
    page = _page(world, reverse("feed"))
    assert page.count('type="file"') == 1, "two pickers is the control this replaced"
    assert 'name="media"' in page
    assert 'accept="image/*,video/*"' in page, "one native sheet, both kinds"
    assert "Add photos or a video" in page
    # REJECTED by the owner: it forces the camera open and hides the photo library.
    # Matched as the ATTRIBUTE, not the bare word: the design system explains the decision
    # in a CSS comment, and that comment ships inline on every page.
    assert "capture=" not in page


def test_the_reply_form_offers_the_same_one_control(world: dict[str, object]) -> None:
    pod, member = world["pod"], world["member"]
    assert isinstance(pod, Pod) and isinstance(member, Member)
    post = Post.objects.create(author=member, pod=pod, body="a thread")
    page = _page(world, reverse("post_detail", args=[post.id]))
    assert page.count('type="file"') == 1
    assert 'accept="image/*,video/*"' in page and "capture=" not in page


def test_it_degrades_to_a_plain_working_picker(world: dict[str, object]) -> None:
    """The thumbnails are an enhancement, so the page has to be right BEFORE the script
    runs: a real file input with its own native button and its own count, a label bound to
    it, and the limits in words. The `js` class that swaps in our label-button is set by
    the script and must not be in the served HTML."""
    page = _page(world, reverse("feed"))
    assert 'class="media-picker" data-media-picker' in page, "not enhanced until the script says"
    assert '<label class="picker-button" for="media">Add photos or a video</label>' in page
    assert '<ul class="media-previews" data-media-previews hidden>' in page
    # The script is same-origin inline and carries the request's CSP nonce, or the browser
    # refuses it and the fallback above is what everybody gets.
    assert "<script nonce=" in page
    assert re.search(r"<script(?![^>]*\bnonce=)[^>]*>", page) is None


def test_the_limits_are_said_in_words_beside_the_control(world: dict[str, object]) -> None:
    """With the enhancement script off there is no thumbnail strip to count, so the
    ceilings have to be readable on the page — and they have to come from the constants,
    not be typed into the template where they would drift the first time either moved."""
    page = _page(world, reverse("feed"))
    assert f"Up to {_MAX_PHOTOS} photos" in page


def _page(world: dict[str, object], url: str) -> str:
    client = world["client"]
    assert isinstance(client, Client)
    return client.get(url).content.decode()


# --- routing ---------------------------------------------------------------------


def test_split_routes_by_declared_type_then_by_name() -> None:
    files: list[UploadedFile] = [
        SimpleUploadedFile("a.jpg", b"x", content_type="image/jpeg"),
        SimpleUploadedFile("b.heic", b"x", content_type="image/heic"),
        SimpleUploadedFile("c.mov", b"x", content_type="video/quicktime"),
        # No usable content type (some Android pickers): the name is the only signal.
        SimpleUploadedFile("d.MOV", b"x", content_type="application/octet-stream"),
        SimpleUploadedFile("e.png", b"x", content_type="application/octet-stream"),
    ]
    photos, videos = _split_media(files)
    assert [f.name for f in photos] == ["a.jpg", "b.heic", "e.png"]
    assert [f.name for f in videos] == ["c.mov", "d.MOV"]


def test_a_photo_picked_through_the_one_control_lands_on_the_post(
    world: dict[str, object],
) -> None:
    _compose(
        world,
        media=SimpleUploadedFile("pie.jpg", _image_bytes("JPEG"), content_type="image/jpeg"),
    )
    post = Post.objects.get(body="hello")
    assert post.media.filter(media_kind=MediaAsset.PHOTO).count() == 1


def test_a_file_that_lies_about_itself_is_rejected_by_the_gate_it_lands_in(
    world: dict[str, object],
) -> None:
    """The split is a hint. An HTML polyglot named `.mov` reaches the VIDEO gate, whose
    magic-byte check (TS-PP-1) refuses it — the compose fails rather than storing it."""
    response = _compose(
        world,
        media=SimpleUploadedFile(
            "nope.mov", b"<html>not a movie at all</html>", content_type="video/quicktime"
        ),
    )
    assert not Post.objects.filter(body="hello").exists(), "a lying upload created a post"
    assert "not a video we can play" in response.content.decode()  # type: ignore[attr-defined]


# --- HEIC ------------------------------------------------------------------------


def test_a_heic_still_is_accepted_and_stored_as_a_jpeg(world: dict[str, object]) -> None:
    """BY-14. v1 relied on a browser-side canvas conversion that only Safari can do, so a
    HEIC from Chrome, Firefox or Android was rejected outright — a relative picking the
    picture their phone had just taken and being told Backyard could not read it."""
    _compose(
        world,
        media=SimpleUploadedFile("IMG_0001.HEIC", _image_bytes("HEIF"), content_type="image/heic"),
    )
    post = Post.objects.get(body="hello")
    asset = post.media.get(media_kind=MediaAsset.PHOTO)
    # Re-encoded like every other upload: the stored bytes are our JPEG, never the
    # original container, so the TM-9 metadata strip applies to a HEIC too.
    assert asset.content_type == "image/jpeg"
    assert asset.image.name.endswith(".jpg")


def test_heic_goes_through_the_same_gate_as_everything_else() -> None:
    """Registering a decoder must not open a side door: a truncated HEIC is still an
    undecodable image, and an unlisted format is still refused."""
    from core import media

    with pytest.raises(media.MediaRejected):
        media._decode(_image_bytes("HEIF")[:40])
    with pytest.raises(media.MediaRejected):
        media._decode(b"BM" + b"\x00" * 200)  # a BMP: decodable by Pillow, not allowlisted


# --- limits ----------------------------------------------------------------------


def _said(response: object) -> str:
    return " ".join(str(m) for m in response.wsgi_request._messages)  # type: ignore[attr-defined]


def test_the_count_ceiling_is_unchanged_and_spoken_plainly(world: dict[str, object]) -> None:
    small = _image_bytes("JPEG")
    response = _compose(
        world,
        media=[
            SimpleUploadedFile(f"p{i}.jpg", small, content_type="image/jpeg")
            for i in range(_MAX_PHOTOS + 3)
        ],
    )
    post = Post.objects.get(body="hello")
    assert post.media.filter(media_kind=MediaAsset.PHOTO).count() == _MAX_PHOTOS
    assert f"{_MAX_PHOTOS} is the limit for one post" in _said(response)


def test_the_size_ceiling_is_unchanged_and_spoken_plainly(world: dict[str, object]) -> None:
    response = _compose(
        world,
        media=SimpleUploadedFile(
            "huge.jpg", b"\xff\xd8" + b"\x00" * _MAX_PHOTO_BYTES, content_type="image/jpeg"
        ),
    )
    said = _said(response)
    assert "too large to add" in said and "MB is the limit each" in said
    # Plain words, never a machine phrase: no MIME types, no byte counts, no error codes,
    # no exception names. This is the sentence a relative reads when a photo did not make
    # it, and it is the only thing standing between them and silent data loss.
    for jargon in ("image/", "bytes", "MediaRejected", "400", "None"):
        assert jargon not in said
