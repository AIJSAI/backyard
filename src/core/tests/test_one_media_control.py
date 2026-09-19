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
import struct
from unittest import mock

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


def _heic_that_opens_and_fails_at_load() -> bytes:
    """A HEIC whose `ispe` box is rewritten to disagree with the coded size.

    It parses — `Image.open` cheerfully reports the box's 16x16 — and then libheif refuses
    the real bitstream from inside `load()`, as a **RuntimeError**. That is the shape the
    gate missed: not a Pillow exception at all.

    The frame is deliberately 640x480 and not the 64x48 the other fixtures use. libheif's
    refusal is a pixel-count SECURITY LIMIT (65536), so a small frame slips under it and
    comes back as a plain ValueError, which the gate always caught — a fixture that size
    made this test pass with the fix reverted. Measured before it was trusted.
    """
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (30, 92, 70)).save(buf, format="HEIF")
    raw = bytearray(buf.getvalue())
    box = raw.find(b"ispe")
    assert box != -1, "no ispe box: the fixture no longer builds a real HEIF container"
    struct.pack_into(">II", raw, box + 8, 16, 16)
    return bytes(raw)


def test_a_heic_that_dies_mid_decode_is_a_message_not_a_server_error(
    world: dict[str, object],
) -> None:
    """The failure this whole PR exists to end, one layer down.

    libheif does not confine itself to Pillow's exception vocabulary: a security-limit
    refusal comes out of `load()` as RuntimeError and a truncated HEVC bitstream as
    EOFError, and neither is an OSError, so neither was caught. `compose` is
    `@transaction.non_atomic_requests` and `posting.create_post` has already COMMITTED by
    the time the photos are attached — so before the fix a relative uploading a corrupt
    phone photo got a 500, and the post went live without its photographs and without a
    word about them. Driven through the real view, because the 500 is a property of where
    the decode sits, not of `_decode` alone.
    """
    response = _compose(
        world,
        media=SimpleUploadedFile(
            "IMG_0002.HEIC", _heic_that_opens_and_fails_at_load(), content_type="image/heic"
        ),
    )
    assert response.status_code == 302, "a corrupt photo must not be a server error"  # type: ignore[attr-defined]
    post = Post.objects.get(body="hello")
    assert post.media.count() == 0
    said = _said(response)
    assert "could not be added" in said and "not a picture Backyard could read" in said
    # Plain words, not the exception that caused it.
    for leak in ("RuntimeError", "EOFError", "libheif", "Traceback"):
        assert leak not in said


def test_the_same_cure_covers_the_reply_and_the_link_preview(world: dict[str, object]) -> None:
    """The other two callers of the decode gate, asserted where they actually differ.

    A reply attaches through the same `_attach_photos`, which catches MediaRejected only,
    so it had the identical 500-after-the-write shape. `ingest_link_preview_image` runs on
    the WORKER and swallows MediaRejected to fall back to a card with no image — so before
    the fix, an attacker-controlled `og:image` served as HEIF killed the job instead.
    """
    from core import media

    pod, member = world["pod"], world["member"]
    assert isinstance(pod, Pod) and isinstance(member, Member)
    corrupt = _heic_that_opens_and_fails_at_load()

    post = Post.objects.create(author=member, pod=pod, body="a thread")
    client = world["client"]
    assert isinstance(client, Client)
    reply = client.post(
        reverse("add_comment", args=[post.id]),
        {"body": "look", "media": SimpleUploadedFile("x.HEIC", corrupt, content_type="image/heic")},
    )
    assert reply.status_code == 302, "a corrupt reply photo must not be a server error"
    assert post.comments.count() == 1 and post.comments.get().media.count() == 0

    # The worker's path degrades to a card with no image rather than raising.
    assert media.ingest_link_preview_image(post=post, raw=corrupt) is None


def test_a_bomb_is_refused_before_its_bitmap_is_allocated() -> None:
    """TS-PP-3. The ceiling is ours, not a library default: assert it on a real decode so
    that raising, removing or shadowing _MAX_PIXELS reddens something.

    Nothing in the suite touched this before — removing the limit entirely left every test
    green — which matters more now that a second, container-shaped decoder is registered:
    pillow-heif reassigns the image size from the bitstream during `load()`, so Pillow's
    one bomb check, taken at `open()` against the declared `ispe` canvas, was measured
    passing on a lie.
    """
    from PIL import Image

    from core import media

    assert Image.MAX_IMAGE_PIXELS == media._MAX_PIXELS, "the process-wide cap is not ours"
    buf = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buf, format="PNG")
    original, Image.MAX_IMAGE_PIXELS = Image.MAX_IMAGE_PIXELS, 0
    try:
        with pytest.raises(media.MediaRejected, match="image too large"):
            media._decode(buf.getvalue())
    finally:
        Image.MAX_IMAGE_PIXELS = original


def test_the_ceiling_is_re_checked_after_the_decode_not_only_at_open() -> None:
    """The half of TS-PP-3 that a container format broke.

    Pillow runs its bomb check once, inside `Image.open`, against the size the header
    DECLARES. pillow-heif then reassigns that size from the bitstream during `load()` —
    its own source says "Size of Image can change during decoding" — and Pillow never
    looks again. Measured on this branch: an `ispe` box rewritten to 16x16 on a real
    640x480 HEIC made `Image.open` report 16x16, so the ceiling was cleared by a lie and
    held only because libheif's own security limit happened to refuse the mismatch first,
    which is a library default this repo does not own and can change under a patch bump.

    A stub, deliberately: the point under test is OUR re-check, and the only way to reach
    it is an image that grows across `load()` — which is exactly what the real decoder
    does, and what no honest fixture can produce once libheif refuses it first.
    """
    from core import media

    class _GrowsDuringLoad:
        format = "PNG"
        width = height = 4  # what the header claims; sails past the check at open

        def load(self) -> None:
            self.width = self.height = 40_000  # 1.6e9 pixels, ~53x the ceiling

    with mock.patch.object(Image, "open", return_value=_GrowsDuringLoad()):
        with pytest.raises(media.MediaRejected, match="image too large"):
            media._decode(b"whatever")


def test_only_the_iphone_heif_mimetypes_are_admitted() -> None:
    """`format` is the CONTAINER for pillow-heif — one name, "HEIF", for every brand its
    sniffer accepts — so the format allowlist alone cannot tell a phone's HEVC still from
    whatever else the bundled libheif was compiled to decode, a set the wheel decides and
    is free to widen under a patch bump. A real HEIC still passes; the narrowing is what
    keeps that true."""
    from core import media

    assert media._decode(_image_bytes("HEIF")).format == "HEIF"
    assert "image/heic" in media._ALLOWED_HEIF_MIME

    # The narrowing is live: a HEIF-format image reporting anything else is refused.
    class _Pretender:
        format = "HEIF"
        custom_mimetype = "image/avif"
        width = height = 1

        def load(self) -> None: ...

    with mock.patch.object(Image, "open", return_value=_Pretender()):
        with pytest.raises(media.MediaRejected, match="not accepted"):
            media._decode(b"whatever")


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
