"""Photo ingest and access-checked media (S-401, S-403, TM-9, TS-PP-3/4).

The security core: every uploaded image is re-encoded at ingest so no EXIF, GPS, or
XMP survives; a file that will not decode to an allowed format is rejected, not passed
through; and every stored byte is served only through the one access-checked path that
inherits the owning post's audience, so a cross-yard member gets the same 404 as an
unknown token.
"""

from __future__ import annotations

import ast
import datetime
import io
import subprocess
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from core import digest_links, elder_tokens, media, scoping
from core.models import (
    DigestIssue,
    DigestToken,
    MediaAsset,
    Member,
    Pod,
    PodMembership,
    Post,
    Yard,
)

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


def test_media_requires_a_read_credential(world: dict[str, object]) -> None:
    """Anonymous gets nothing — and now gets the byte-identical 404 rather than a
    redirect to the login page.

    This asserted 302 while the view was `@login_required`. That gate had to go: a
    token-only elder has no Django user by design (TM-10), so it made every photo on
    every post she could already read return 404 — the product's central promise
    undelivered on the one surface it exists for. The security property is unchanged
    and the assertion now names it: no credential, no bytes. A 404 also leaks less
    than a login redirect, which confirms the URL pattern is real.
    """
    post = world["post"]
    assert isinstance(post, Post)
    asset = media.ingest_photo(post=post, raw=_jpeg_with_exif())
    assert Client().get(reverse("serve_media", args=[asset.token])).status_code == 404


def test_an_elder_session_can_fetch_media_it_can_see_and_nothing_else(
    world: dict[str, object],
) -> None:
    """The fix, and its ceiling, in one test.

    An elder session reaches the photos on posts inside her audience, and reaches
    nothing outside it — the audience query is untouched, only the authentication path
    widened.
    """
    post = world["post"]
    assert isinstance(post, Post)
    asset = media.ingest_photo(post=post, raw=_jpeg_with_exif())

    # An elder in the poster's pod: she can see the post, so she must get the bytes.
    elder = Member.objects.create(display_name="Gran")
    PodMembership.objects.create(member=elder, pod=post.pod)
    raw = elder_tokens.mint(elder)
    client = Client()
    client.get(reverse("elder_enter", args=[raw]))
    assert client.get(reverse("serve_media", args=[asset.token])).status_code == 200

    # An elder in a wholly separate yard: same credential shape, no overlap, no bytes.
    other_yard = Yard.objects.create(name="Other side", slug="other-side-media")
    other_pod = Pod.objects.create(name="Other house")
    other_pod.yards.set([other_yard])
    stranger = Member.objects.create(display_name="Stranger Gran")
    PodMembership.objects.create(member=stranger, pod=other_pod)
    raw2 = elder_tokens.mint(stranger)
    client2 = Client()
    client2.get(reverse("elder_enter", args=[raw2]))
    assert client2.get(reverse("serve_media", args=[asset.token])).status_code == 404


def test_revoking_an_elder_kills_her_media_access_mid_session(
    world: dict[str, object],
) -> None:
    """ADR-003: the generation check is what revokes, not the TTL. A live session must
    stop fetching bytes the moment the member's generation is bumped, or a revoked
    elder link would keep serving family photos from a warm cookie."""
    post = world["post"]
    assert isinstance(post, Post)
    asset = media.ingest_photo(post=post, raw=_jpeg_with_exif())
    elder = Member.objects.create(display_name="Revoked Gran")
    PodMembership.objects.create(member=elder, pod=post.pod)
    raw = elder_tokens.mint(elder)
    client = Client()
    client.get(reverse("elder_enter", args=[raw]))
    assert client.get(reverse("serve_media", args=[asset.token])).status_code == 200

    elder.token_generation += 1
    elder.save(update_fields=["token_generation"])
    assert client.get(reverse("serve_media", args=[asset.token])).status_code == 404


def _issue_for(member: Member, yard: Yard, *, days: int = 7) -> tuple[DigestIssue, str]:
    """A digest issue whose window ends an hour out, plus its minted raw token."""
    window_end = timezone.now() + datetime.timedelta(hours=1)
    issue = DigestIssue.objects.create(
        member=member,
        yard=yard,
        window_start=window_end - datetime.timedelta(days=days),
        window_end=window_end,
    )
    return issue, digest_links.mint(issue)


def test_a_digest_token_fetches_the_photos_its_own_issue_rendered(
    world: dict[str, object],
) -> None:
    """The emailed deep link opens a page with no session, so every image on it
    re-presents the capability as ?d=<token>. Without this the digest surfaces showed
    captions and a photo count over a grid of broken images."""
    post, maternal = world["post"], world["maternal"]
    assert isinstance(post, Post) and isinstance(maternal, Yard)
    pod_mate = world["pod_mate"]
    assert isinstance(pod_mate, Member)
    asset = media.ingest_photo(post=post, raw=_jpeg_with_exif())
    _, raw = _issue_for(pod_mate, maternal)

    url = reverse("serve_media", args=[asset.token])
    assert Client().get(f"{url}?d={raw}").status_code == 200
    # The token is the whole credential: without it the same URL is anonymous.
    assert Client().get(url).status_code == 404
    assert Client().get(f"{url}?d=never-was-a-token").status_code == 404


def test_a_digest_token_cannot_fetch_media_outside_its_own_issue(
    world: dict[str, object],
) -> None:
    """The capability ceiling, on the media path.

    A digest token authenticates its member but must never widen into a general read
    credential for that member's other yards and other weeks — digest_post_view has
    always enforced that with the issue-slice check. The first cut of this feature ran
    only `scoping.visible_media(member)` here, which is strictly wider than the page the
    token was minted to render: one leaked link would have reached every photo that
    member could see, ever. The narrowing now lives on Reader, so the ceiling travels
    with the credential instead of waiting on each caller to remember it.
    """
    maternal, m_pod = world["maternal"], world["m_pod"]
    author, pod_mate = world["author"], world["pod_mate"]
    assert isinstance(maternal, Yard) and isinstance(m_pod, Pod)
    assert isinstance(author, Member) and isinstance(pod_mate, Member)

    # A post from BEFORE the issue window: same yard, same audience, fully visible to
    # this member in the app — and deliberately outside what this token covers.
    old_post = Post.objects.create(author=author, pod=m_pod, body="last month")
    old_post.audience_yards.set([maternal])
    old_asset = media.ingest_photo(post=old_post, raw=_jpeg_with_exif())
    Post.objects.filter(pk=old_post.pk).update(
        created_at=timezone.now() - datetime.timedelta(days=40)
    )

    _, raw = _issue_for(pod_mate, maternal)
    url = reverse("serve_media", args=[old_asset.token])
    assert Client().get(f"{url}?d={raw}").status_code == 404
    # ...and the member's own session still reaches it, so this is the token's ceiling
    # and not a change to what the member may see.
    assert _client_for(pod_mate).get(url).status_code == 200


def test_an_expired_or_revoked_digest_token_fetches_nothing(
    world: dict[str, object],
) -> None:
    """Both failure shapes collapse to the same 404 as an unknown token: expiry and the
    ADR-003 generation bump each end the link's media reach, not just its page."""
    post, maternal = world["post"], world["maternal"]
    assert isinstance(post, Post) and isinstance(maternal, Yard)
    pod_mate = world["pod_mate"]
    assert isinstance(pod_mate, Member)
    asset = media.ingest_photo(post=post, raw=_jpeg_with_exif())
    url = reverse("serve_media", args=[asset.token])

    _, expiring = _issue_for(pod_mate, maternal)
    assert Client().get(f"{url}?d={expiring}").status_code == 200
    DigestToken.objects.all().update(expires_at=timezone.now() - datetime.timedelta(days=1))
    assert Client().get(f"{url}?d={expiring}").status_code == 404

    _, live = _issue_for(pod_mate, maternal)
    assert Client().get(f"{url}?d={live}").status_code == 200
    Member.objects.filter(pk=pod_mate.pk).update(token_generation=99)
    assert Client().get(f"{url}?d={live}").status_code == 404


def test_all_three_credential_free_surfaces_actually_render_the_photo(
    world: dict[str, object],
) -> None:
    """The headline fix, asserted end-to-end on the RENDERED pages.

    Every other test here proves `serve_media` will hand over the bytes when asked. None
    of them proved anything ASKS. A template regression — a renamed prefetch attribute, a
    dropped {% for %}, the wrong token — would leave the whole suite green while a
    grandparent again sees a post with no picture on it, which is the exact failure this
    wave exists to end.
    """
    post, maternal = world["post"], world["maternal"]
    author, pod_mate, other = world["author"], world["pod_mate"], world["other"]
    assert isinstance(post, Post) and isinstance(maternal, Yard)
    assert isinstance(author, Member) and isinstance(pod_mate, Member)
    assert isinstance(other, Member)
    asset = media.ingest_photo(post=post, raw=_jpeg_with_exif())
    media_url = reverse("serve_media", args=[asset.token])

    # 1. The elder page: a token-only elder, no Django user at all.
    elder = Member.objects.create(display_name="Elder Renderer")
    PodMembership.objects.create(member=elder, pod=post.pod)
    elder_client = Client()
    elder_client.get(reverse("elder_enter", args=[elder_tokens.mint(elder)]))
    elder_page = elder_client.get(reverse("elder_feed")).content.decode()
    assert media_url in elder_page

    # 2 and 3. Both digest surfaces, cookieless, each image re-presenting the capability.
    _, raw = _issue_for(pod_mate, maternal)
    for url in (
        reverse("digest_web", args=[raw]),
        reverse("digest_web_post", args=[raw, post.pk]),
    ):
        page = Client().get(url).content.decode()
        assert f"{media_url}?d={raw}" in page, url

    # The negative arm: a cross-yard elder's page must not carry that URL at all. Without
    # this the assertions above would also pass on a template that rendered every asset.
    stranger_yard = Yard.objects.create(name="Far side", slug="far-side-render")
    stranger_pod = Pod.objects.create(name="Far house")
    stranger_pod.yards.set([stranger_yard])
    stranger = Member.objects.create(display_name="Far Elder")
    PodMembership.objects.create(member=stranger, pod=stranger_pod)
    stranger_client = Client()
    stranger_client.get(reverse("elder_enter", args=[elder_tokens.mint(stranger)]))
    assert media_url not in stranger_client.get(reverse("elder_feed")).content.decode()


def test_serve_media_routes_every_audience_decision_through_reader() -> None:
    """Drift guard: `serve_media` must never reach for `scoping` itself.

    The ceiling a credential carries lives on `Reader.visible_media`. The first cut of
    this view called `scoping.visible_media(member)` directly and so silently dropped the
    digest issue-slice ceiling — the bug that mutation-testing caught. A future edit that
    reintroduces a direct scoping call would reintroduce exactly that class of hole, and
    this fails the build instead. Checked over the parsed IMPORTS, not the text, so the
    module docstring stays free to describe the audience query in prose. Non-vacuous by
    construction: the pre-fix module imported `scoping` and would fail here.
    """
    path = Path(__file__).resolve().parents[1] / "media_views.py"
    tree = ast.parse(path.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
    assert "scoping" not in imported, "serve_media must resolve audience via Reader, not scoping"
    assert "viewers" in imported
    assert "reader.visible_media()" in path.read_text()


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


# --- the format allowlist must gate the DECODER, not just the result (TS-PP-3) ---


def test_a_disallowed_format_is_rejected_before_its_decoder_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TS-PP-3's answer says "enforce a format allowlist at `open`". It was enforced at
    reject -- one full decode too late.

    `img.load()` ran first and the allowlist checked `img.format` afterwards, so a crafted
    TIFF/PCX/PSD/TGA/DDS/JPEG2000 got its format-specific C decoder run to completion and
    was then politely declined. That makes the allowlist inert as a CVE-surface control,
    which is the entire reason pillow is floored at >=12.3 to clear the 11.3 decoder CVEs.

    This asserts the ORDER by spying on the decode, because asserting only "it was
    rejected" passes either way -- which is why this went unnoticed.
    """
    import io as _io

    from PIL import Image as _Image

    # Build the fixture BEFORE the spy: saving a new image calls load() on it too, and
    # those calls carry format=None. Counting them would have made this assertion noisy
    # and, worse, unfalsifiable-looking.
    buf = _io.BytesIO()
    _Image.new("RGB", (8, 8), "red").save(buf, format="TIFF")
    payload = buf.getvalue()

    decoded: list[str] = []
    original_load = _Image.Image.load

    def spy(self):  # type: ignore[no-untyped-def]
        if self.format:
            decoded.append(self.format)
        return original_load(self)

    monkeypatch.setattr(_Image.Image, "load", spy)

    with pytest.raises(media.MediaRejected):
        media._decode(payload)

    assert decoded == [], f"the {decoded} decoder ran before the format allowlist rejected the file"


# --- the parser child must not inherit the instance's secrets (TS-CO-5) ---


def test_ffmpeg_children_do_not_inherit_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """ffmpeg/ffprobe are the only processes here that run on attacker-supplied bytes.

    They inherited the whole environment -- the DB password, the backup passphrase, the
    mail provider key -- so a decode-time CVE (the risk the rlimits and the re-encode
    exist to bound) escalated straight to reading the key that decrypts every family
    backup, out of its own /proc/self/environ.

    Asserted by planting secrets and capturing the env actually handed to the child,
    rather than by reading the call site.
    """
    from core import transcoding

    monkeypatch.setenv("POSTGRES_PASSWORD", "planted-db-password")
    monkeypatch.setenv("BACKYARD_BACKUP_PASSPHRASE", "planted-backup-passphrase")
    monkeypatch.setenv("RESEND_API_KEY", "planted-resend-key")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    captured: dict[str, dict[str, str] | None] = {}

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    transcoding._run(["ffprobe", "-version"], timeout=5)

    env = captured["env"]
    assert env is not None, "the child inherited the parent environment wholesale"
    planted = ("POSTGRES_PASSWORD", "BACKYARD_BACKUP_PASSPHRASE", "RESEND_API_KEY")
    leaked = [name for name in planted if name in env]
    assert not leaked, f"secrets reached the parser child: {leaked}"
    assert env.get("PATH") == "/usr/bin:/bin", "the child still needs PATH to find ffmpeg"
