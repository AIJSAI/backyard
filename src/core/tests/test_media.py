"""Photo ingest and access-checked media (S-401, S-403, TM-9, TS-PP-3/4).

The security core: every uploaded image is re-encoded at ingest so no EXIF, GPS, or
XMP survives; a file that will not decode to an allowed format is rejected, not passed
through; and every stored byte is served only through the one access-checked path that
inherits the owning post's audience, so a cross-yard member gets the same 404 as an
unknown token.
"""

from __future__ import annotations

import io

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from core import media, scoping
from core.models import Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_TEST_PW = "a-Strong-passphrase-9"

_ORIENTATION = 0x0112
_IMAGE_DESCRIPTION = 0x010E


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


def _jpeg_with_exif(size: tuple[int, int] = (120, 80), orientation: int = 1) -> bytes:
    """A JPEG carrying EXIF: an orientation tag and a description standing in for the
    location/identity metadata TM-9 must strip."""
    img = Image.new("RGB", size, (200, 40, 40))
    exif = img.getexif()
    exif[_ORIENTATION] = orientation
    exif[_IMAGE_DESCRIPTION] = "shot at home, 41.25 N 96.0 W"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _png(size: tuple[int, int] = (60, 60)) -> bytes:
    img = Image.new("RGBA", size, (0, 128, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def world() -> dict[str, object]:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    m_pod = Pod.objects.create(name="Maternal cousins")
    m_pod.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal cousins")
    p_pod.yards.set([paternal])
    author = _member_with_user(m_pod, "Author")
    post = Post.objects.create(author=author, pod=m_pod, body="a maternal post")
    post.audience_yards.set([maternal])
    return {
        "maternal": maternal,
        "m_pod": m_pod,
        "author": author,
        "pod_mate": _member_with_user(m_pod, "PodMate"),
        "other": _member_with_user(p_pod, "Other"),
        "post": post,
    }


# --- ingest: strip, reject, pin ---


def test_ingest_strips_all_exif(world: dict[str, object]) -> None:
    post = world["post"]
    assert isinstance(post, Post)
    asset = media.ingest_photo(post=post, raw=_jpeg_with_exif(orientation=1))
    out = Image.open(io.BytesIO(asset.image.read()))
    exif = out.getexif()
    assert _ORIENTATION not in exif  # the orientation tag is gone (baked in, then dropped)
    assert _IMAGE_DESCRIPTION not in exif  # the location-bearing description is stripped
    assert dict(exif) == {}  # nothing at all carries over


def test_ingest_applies_orientation_then_drops_the_tag(world: dict[str, object]) -> None:
    post = world["post"]
    assert isinstance(post, Post)
    # Orientation 6 = rotate 90; a 120x80 input becomes 80x120 after transpose.
    asset = media.ingest_photo(post=post, raw=_jpeg_with_exif(size=(120, 80), orientation=6))
    out = Image.open(io.BytesIO(asset.image.read()))
    assert out.size == (80, 120)  # pixels rotated upright
    assert _ORIENTATION not in out.getexif()


def test_ingest_pins_content_type_to_jpeg_regardless_of_input(world: dict[str, object]) -> None:
    post = world["post"]
    assert isinstance(post, Post)
    asset = media.ingest_photo(post=post, raw=_png())  # a PNG in
    assert asset.content_type == "image/jpeg"  # re-encoded; content type is the output
    assert Image.open(io.BytesIO(asset.image.read())).format == "JPEG"


def test_ingest_rejects_a_non_image(world: dict[str, object]) -> None:
    post = world["post"]
    assert isinstance(post, Post)
    with pytest.raises(media.MediaRejected):
        media.ingest_photo(post=post, raw=b"<svg xmlns='...'><script>alert(1)</script></svg>")
    with pytest.raises(media.MediaRejected):
        media.ingest_photo(post=post, raw=b"not an image at all")


def test_thumbnail_token_is_independent(world: dict[str, object]) -> None:
    post = world["post"]
    assert isinstance(post, Post)
    asset = media.ingest_photo(post=post, raw=_jpeg_with_exif())
    assert asset.token and asset.thumbnail_token
    assert asset.token != asset.thumbnail_token  # not derivable from the source (TM-9)


# --- serving: access-checked ---


def test_media_served_to_a_yard_member(world: dict[str, object]) -> None:
    post = world["post"]
    pod_mate = world["pod_mate"]
    assert isinstance(post, Post)
    assert isinstance(pod_mate, Member)
    asset = media.ingest_photo(post=post, raw=_jpeg_with_exif())
    response = _client_for(pod_mate).get(reverse("serve_media", args=[asset.token]))
    assert response.status_code == 200
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in response["Cache-Control"]


def test_media_cross_yard_is_404_for_both_tokens(world: dict[str, object]) -> None:
    post = world["post"]
    other = world["other"]
    assert isinstance(post, Post)
    assert isinstance(other, Member)
    asset = media.ingest_photo(post=post, raw=_jpeg_with_exif())
    client = _client_for(other)  # paternal
    assert client.get(reverse("serve_media", args=[asset.token])).status_code == 404
    assert client.get(reverse("serve_media", args=[asset.thumbnail_token])).status_code == 404


def test_deleted_media_404s(world: dict[str, object]) -> None:
    post = world["post"]
    author = world["author"]
    assert isinstance(post, Post)
    assert isinstance(author, Member)
    asset = media.ingest_photo(post=post, raw=_jpeg_with_exif())
    asset.deleted_at = timezone.now()
    asset.save(update_fields=["deleted_at"])
    assert _client_for(author).get(reverse("serve_media", args=[asset.token])).status_code == 404


def test_media_on_a_deleted_post_404s(world: dict[str, object]) -> None:
    post = world["post"]
    author = world["author"]
    assert isinstance(post, Post)
    assert isinstance(author, Member)
    asset = media.ingest_photo(post=post, raw=_jpeg_with_exif())
    post.deleted_at = timezone.now()
    post.save(update_fields=["deleted_at"])
    assert _client_for(author).get(reverse("serve_media", args=[asset.token])).status_code == 404


def test_media_requires_login(world: dict[str, object]) -> None:
    post = world["post"]
    assert isinstance(post, Post)
    asset = media.ingest_photo(post=post, raw=_jpeg_with_exif())
    assert Client().get(reverse("serve_media", args=[asset.token])).status_code == 302


def test_visible_media_scoping(world: dict[str, object]) -> None:
    post = world["post"]
    pod_mate = world["pod_mate"]
    other = world["other"]
    assert isinstance(post, Post)
    assert isinstance(pod_mate, Member)
    assert isinstance(other, Member)
    asset = media.ingest_photo(post=post, raw=_jpeg_with_exif())
    assert asset.id in set(scoping.visible_media(pod_mate).values_list("id", flat=True))
    assert asset.id not in set(scoping.visible_media(other).values_list("id", flat=True))


# --- composer attaches photos ---


def test_compose_attaches_a_photo(world: dict[str, object]) -> None:
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    upload = SimpleUploadedFile("holiday.jpg", _jpeg_with_exif(), content_type="image/jpeg")
    response = _client_for(author).post(
        reverse("compose"), {"body": "with a photo", "pod_id": m_pod.id, "photos": upload}
    )
    assert response.status_code == 302
    new_post = Post.objects.get(body="with a photo")
    assert new_post.media.count() == 1
    first_media = new_post.media.first()
    assert first_media is not None
    assert first_media.content_type == "image/jpeg"
