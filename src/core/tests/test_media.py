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
from core.models import MediaAsset, Member, Pod, PodMembership, Post, Yard

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


def _jpeg_with_comment(comment: bytes = b"SECRET-COMMENT-METADATA") -> bytes:
    """A JPEG carrying a COM marker, the one field Pillow's encoder back-fills from
    the source (security review MEDIUM-1)."""
    img = Image.new("RGB", (50, 50), (10, 10, 10))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", comment=comment)
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


def test_ingest_strips_the_jpeg_comment(world: dict[str, object]) -> None:
    """The JPEG COM marker is the one field Pillow's encoder back-fills from the source
    (security review MEDIUM-1); the re-encode must drop it too, not only EXIF."""
    post = world["post"]
    assert isinstance(post, Post)
    asset = media.ingest_photo(post=post, raw=_jpeg_with_comment())
    assert b"SECRET-COMMENT-METADATA" not in asset.image.read()


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


# --- hard purge on delete (T-MEDIA-6) ---


def test_purge_removes_files_and_rows(
    world: dict[str, object], django_capture_on_commit_callbacks: object
) -> None:
    post = world["post"]
    assert isinstance(post, Post)
    asset = media.ingest_photo(post=post, raw=_jpeg_with_exif())
    storage = asset.image.storage
    full_name, thumb_name = asset.image.name, asset.thumbnail.name
    assert storage.exists(full_name) and storage.exists(thumb_name)

    # File removal is scheduled on transaction commit; run the callbacks so the test,
    # which never really commits, still exercises the deletion.
    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        purged = media.purge_post_media(post)
    assert purged == 1
    assert not MediaAsset.objects.filter(post=post).exists()  # row gone
    assert not storage.exists(full_name)  # file gone from disk (T-MEDIA-6)
    assert not storage.exists(thumb_name)


def test_delete_post_purges_its_photos(
    world: dict[str, object], django_capture_on_commit_callbacks: object
) -> None:
    author = world["author"]
    m_pod = world["m_pod"]
    assert isinstance(author, Member)
    assert isinstance(m_pod, Pod)
    post = Post.objects.create(author=author, pod=m_pod, body="photo to delete")
    asset = media.ingest_photo(post=post, raw=_jpeg_with_exif())
    storage = asset.image.storage
    full_name = asset.image.name

    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        response = _client_for(author).post(reverse("delete_post", args=[post.id]))
    assert response.status_code == 302
    assert not MediaAsset.objects.filter(post=post).exists()
    assert not storage.exists(full_name)  # the file is hard-deleted, not just hidden


# --- re-hosted link-preview image (S-301) ---


def test_ingest_link_preview_image_reencodes_to_a_link_asset(world: dict[str, object]) -> None:
    post = world["post"]
    assert isinstance(post, Post)
    asset = media.ingest_link_preview_image(post=post, raw=_png())  # a PNG in
    assert asset is not None
    assert asset.media_kind == MediaAsset.LINK_PREVIEW
    assert asset.content_type == "image/jpeg"  # pinned from the re-encode, not the origin
    assert Image.open(io.BytesIO(asset.image.read())).format == "JPEG"  # inert re-encoded raster


def test_ingest_link_preview_image_strips_remote_metadata(world: dict[str, object]) -> None:
    """The whole point of re-hosting: the remote image's EXIF/GPS never reaches a family
    member (TM-9), exactly like an uploaded photo."""
    post = world["post"]
    assert isinstance(post, Post)
    asset = media.ingest_link_preview_image(post=post, raw=_jpeg_with_exif())
    assert asset is not None
    exif = Image.open(io.BytesIO(asset.image.read())).getexif()
    assert _ORIENTATION not in exif and _IMAGE_DESCRIPTION not in exif
    assert dict(exif) == {}


def test_ingest_link_preview_image_rejects_oversize_dimensions(world: dict[str, object]) -> None:
    """Security review of S-301: a preview image is held to a tighter decoded-pixel
    budget than an uploaded photo (a small file can inflate to tens of megapixels in
    the web tier), and one whose header declares more pixels than the budget is rejected
    before the bitmap is allocated (graceful: the card just shows no image)."""
    post = world["post"]
    assert isinstance(post, Post)
    over = media._LINK_PREVIEW_MAX_PIXELS
    side = int(over**0.5) + 50  # comfortably over the budget
    buf = io.BytesIO()
    Image.new("RGB", (side, side)).save(buf, format="PNG")
    assert media.ingest_link_preview_image(post=post, raw=buf.getvalue()) is None
    # A card-sized image is well under the budget and re-hosts fine.
    assert media.ingest_link_preview_image(post=post, raw=_png(size=(300, 200))) is not None


def test_ingest_link_preview_image_rejects_undecodable(world: dict[str, object]) -> None:
    post = world["post"]
    assert isinstance(post, Post)
    # A hostile or broken og:image returns None (graceful: the card shows no image),
    # never a MediaRejected propagating into the compose path.
    assert media.ingest_link_preview_image(post=post, raw=b"not an image at all") is None
    assert (
        media.ingest_link_preview_image(
            post=post, raw=b"<svg xmlns='x'><script>alert(1)</script></svg>"
        )
        is None
    )


def test_rehosted_preview_image_is_served_with_the_post_access_check(
    world: dict[str, object],
) -> None:
    """The re-hosted image rides the ONE access-checked media path (TM-9): an in-yard
    member sees it, a cross-yard member gets the same 404 as an unknown token (S-202)."""
    post, pod_mate, other = world["post"], world["pod_mate"], world["other"]
    assert isinstance(post, Post)
    assert isinstance(pod_mate, Member)
    assert isinstance(other, Member)
    asset = media.ingest_link_preview_image(post=post, raw=_png())
    assert asset is not None
    assert _client_for(pod_mate).get(reverse("serve_media", args=[asset.token])).status_code == 200
    assert _client_for(other).get(reverse("serve_media", args=[asset.token])).status_code == 404


def test_rehosted_preview_image_is_not_in_the_post_gallery(world: dict[str, object]) -> None:
    """A LINK_PREVIEW asset is the card's image, not an uploaded photo, so it is absent
    from the post's own media gallery (a real photo on the same post still shows)."""
    post, author = world["post"], world["author"]
    assert isinstance(post, Post)
    assert isinstance(author, Member)
    photo = media.ingest_photo(post=post, raw=_jpeg_with_exif())
    link_image = media.ingest_link_preview_image(post=post, raw=_png())
    assert link_image is not None
    body = _client_for(author).get(reverse("post_detail", args=[post.id])).content.decode()
    # The uploaded photo's thumbnail is in the gallery; the link-preview asset (with no
    # LinkPreview row pointing at it here) appears nowhere on the page.
    assert reverse("serve_media", args=[photo.thumbnail_token]) in body
    assert reverse("serve_media", args=[link_image.token]) not in body


def test_deleting_the_post_purges_the_rehosted_preview_image(
    world: dict[str, object], django_capture_on_commit_callbacks: object
) -> None:
    post = world["post"]
    assert isinstance(post, Post)
    asset = media.ingest_link_preview_image(post=post, raw=_png())
    assert asset is not None
    storage = asset.image.storage
    name = asset.image.name
    assert storage.exists(name)
    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        media.purge_post_media(post)
    assert not MediaAsset.objects.filter(post=post).exists()
    assert not storage.exists(name)  # the re-hosted image leaves the disk too (T-MEDIA-6)
