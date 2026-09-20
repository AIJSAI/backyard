"""A member's profile photo: the ingest gate, the audience, and the lifecycle (S-901).

"Shouldn't people be able to add a profile picture? Isn't that classic?" It is, and the
two halves that matter are the two this product already has opinions about.

THE GATE. A face is a member-uploaded image, so it goes through the same module a
photograph on a post goes through — one decoder allowlist, one decompression-bomb
ceiling, one re-encode that strips EXIF, GPS, XMP and the JPEG comment (TM-9) — and is
stored as two centre-cropped squares. The original upload never reaches the disk.

THE AUDIENCE. A photograph inherits its post's audience; a face inherits its PERSON's,
which in this product is the directory rule (scoping.visible_members): you may look at
the picture of anybody you could look up. The tests below hold that boundary from all
four sides — a member who shares a yard, a member on the other side of the family, an
elder holding a No-Login Link, and nobody at all — because the byline the photo sits
beside is on every screen in the product, and an unguessable token is defence in depth,
never the access control (S-403, T-MEDIA-1).
"""

from __future__ import annotations

import datetime
import io
import json
import zipfile

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from core import digest_links, elder_tokens, export, media, removal, scoping, supervised
from core.models import DigestIssue, Member, Pod, PodMembership, Post, ProfilePhoto, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_TEST_PW = "a-Strong-passphrase-9"

_ORIENTATION = 0x0112
_IMAGE_DESCRIPTION = 0x010E


def _member_with_user(pod: Pod, name: str, *, role: str = Member.MEMBER) -> Member:
    user = User.objects.create_user(username=name.lower().replace(" ", ""), password=_TEST_PW)
    member = Member.objects.create(display_name=name, user=user, role=role)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _client_for(member: Member) -> Client:
    assert member.user is not None
    client = Client()
    client.force_login(member.user, backend=_BACKEND)
    return client


def _jpeg(size: tuple[int, int] = (200, 100)) -> bytes:
    """A wide JPEG carrying EXIF, so both the crop and the strip have something to do."""
    img = Image.new("RGB", size, (40, 90, 160))
    exif = img.getexif()
    exif[_ORIENTATION] = 1
    exif[_IMAGE_DESCRIPTION] = "shot at home, 41.25 N 96.0 W"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (80, 80), (0, 128, 0, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _upload(name: str = "face.jpg", raw: bytes | None = None) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, raw if raw is not None else _jpeg(), content_type="image/jpeg")


@pytest.fixture
def world() -> dict[str, object]:
    """Two sides of one family that cannot see each other, and a post on one of them."""
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
        "p_pod": p_pod,
        "author": author,
        "pod_mate": _member_with_user(m_pod, "PodMate"),
        "other": _member_with_user(p_pod, "Other"),
        "post": post,
    }


def _photo_of(member: Member, raw: bytes | None = None) -> ProfilePhoto:
    return media.ingest_profile_photo(member=member, raw=raw if raw is not None else _jpeg())


# --- the gate: what reaches the disk ----------------------------------------------


def test_both_renditions_are_centre_cropped_squares(world: dict[str, object]) -> None:
    """The disc is a circle, so the stored bytes are a square: nothing is letterboxed or
    squashed by CSS, and the largest size drawn (`avatar-lg` at 2x) is covered."""
    author = world["author"]
    assert isinstance(author, Member)
    photo = _photo_of(author, _jpeg(size=(400, 200)))
    full = Image.open(io.BytesIO(photo.image.read()))
    small = Image.open(io.BytesIO(photo.thumbnail.read()))
    assert full.size == (media.AVATAR_FULL_PX, media.AVATAR_FULL_PX)
    assert small.size == (media.AVATAR_SMALL_PX, media.AVATAR_SMALL_PX)
    assert full.format == "JPEG" and small.format == "JPEG"


def test_the_upload_is_re_encoded_and_stripped_like_any_other_photo(
    world: dict[str, object],
) -> None:
    """The same gate, not a second one: a PNG comes out JPEG, the content type is pinned
    from what was decoded rather than claimed, and no EXIF survives (TM-9)."""
    author = world["author"]
    assert isinstance(author, Member)
    photo = _photo_of(author)
    assert photo.content_type == "image/jpeg"
    assert dict(Image.open(io.BytesIO(photo.image.read())).getexif()) == {}
    assert Image.open(io.BytesIO(_photo_of(author, _png()).image.read())).format == "JPEG"


def test_the_small_rendition_token_is_not_derivable_from_the_large_one(
    world: dict[str, object],
) -> None:
    author = world["author"]
    assert isinstance(author, Member)
    photo = _photo_of(author)
    assert photo.token and photo.thumbnail_token
    assert photo.token != photo.thumbnail_token  # TM-9: independent handles


def test_a_file_that_is_not_an_image_is_refused(world: dict[str, object]) -> None:
    author = world["author"]
    assert isinstance(author, Member)
    with pytest.raises(media.MediaRejected):
        media.ingest_profile_photo(member=author, raw=b"<svg><script>alert(1)</script></svg>")


def test_a_rejected_replacement_leaves_the_current_photo_alone(
    world: dict[str, object],
) -> None:
    """The decode runs before the purge, so a member whose second try is a PDF still has
    the face they uploaded first."""
    author = world["author"]
    assert isinstance(author, Member)
    first = _photo_of(author)
    with pytest.raises(media.MediaRejected):
        media.ingest_profile_photo(member=author, raw=b"not an image at all")
    assert ProfilePhoto.objects.get(member=author).pk == first.pk
    assert first.image.storage.exists(first.image.name)


def test_replacing_a_photo_leaves_one_row_and_no_orphan_files(
    world: dict[str, object], django_capture_on_commit_callbacks: object
) -> None:
    """One row and two files per member. Without the purge inside the ingest, a member
    trying four photographs leaves six renditions on the volume with no row to reach
    them by, which is the unreachable-and-unpurgeable state T-MEDIA-6 forbids.

    The unlink is deferred to commit (a rollback must not strand a live row pointing at
    a deleted file), so the callbacks are run here — the test itself never commits."""
    author = world["author"]
    assert isinstance(author, Member)
    first = _photo_of(author)
    storage, old_files = first.image.storage, (first.image.name, first.thumbnail.name)
    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        second = _photo_of(author)
    assert ProfilePhoto.objects.filter(member=author).count() == 1
    assert second.pk != first.pk
    for name in old_files:
        assert not storage.exists(name)


# --- the audience: who may fetch a face -------------------------------------------


def test_a_member_who_can_see_you_fetches_your_photo(world: dict[str, object]) -> None:
    author, pod_mate = world["author"], world["pod_mate"]
    assert isinstance(author, Member) and isinstance(pod_mate, Member)
    photo = _photo_of(author)
    client = _client_for(pod_mate)
    for token in (photo.token, photo.thumbnail_token):
        response = client.get(reverse("serve_profile_photo", args=[token]))
        assert response.status_code == 200
        assert response["X-Content-Type-Options"] == "nosniff"
        assert "no-store" in response["Cache-Control"]
        assert response["Referrer-Policy"] == "no-referrer"


def test_the_other_side_of_the_family_is_refused_both_tokens(
    world: dict[str, object],
) -> None:
    """The heart of it. Holding the URL is not the access control: a member the viewer
    cannot look up in the directory is a member whose face they cannot fetch (S-902,
    TM-1), and the refusal is the same 404 as an unknown token."""
    author, other = world["author"], world["other"]
    assert isinstance(author, Member) and isinstance(other, Member)
    photo = _photo_of(author)
    client = _client_for(other)
    for token in (photo.token, photo.thumbnail_token):
        assert client.get(reverse("serve_profile_photo", args=[token])).status_code == 404


def test_an_anonymous_request_gets_nothing(world: dict[str, object]) -> None:
    author = world["author"]
    assert isinstance(author, Member)
    photo = _photo_of(author)
    assert Client().get(reverse("serve_profile_photo", args=[photo.token])).status_code == 404


def test_an_elder_link_reader_loads_the_face_of_an_author_she_is_shown(
    world: dict[str, object],
) -> None:
    """A token-only elder has no Django user by design (TM-10). She reads her family's
    posts, so she reaches the faces on those bylines — and reaches nothing on the other
    side of the family, because the audience question is unchanged and only the
    authentication path widened."""
    author, post = world["author"], world["post"]
    assert isinstance(author, Member) and isinstance(post, Post)
    photo = _photo_of(author)

    elder = Member.objects.create(display_name="Gran")
    PodMembership.objects.create(member=elder, pod=post.pod)
    elder_client = Client()
    elder_client.get(reverse("elder_enter", args=[elder_tokens.mint(elder)]))
    assert elder_client.get(reverse("serve_profile_photo", args=[photo.token])).status_code == 200

    far_yard = Yard.objects.create(name="Far side", slug="far-side-faces")
    far_pod = Pod.objects.create(name="Far house")
    far_pod.yards.set([far_yard])
    stranger = Member.objects.create(display_name="Far Gran")
    PodMembership.objects.create(member=stranger, pod=far_pod)
    far_client = Client()
    far_client.get(reverse("elder_enter", args=[elder_tokens.mint(stranger)]))
    assert far_client.get(reverse("serve_profile_photo", args=[photo.token])).status_code == 404


def test_revoking_an_elder_link_ends_her_access_to_faces_too(
    world: dict[str, object],
) -> None:
    """ADR-003: the generation bump is what revokes, and it must reach every byte this
    session can fetch, not only the photographs on posts."""
    author, post = world["author"], world["post"]
    assert isinstance(author, Member) and isinstance(post, Post)
    photo = _photo_of(author)
    elder = Member.objects.create(display_name="Revoked Gran")
    PodMembership.objects.create(member=elder, pod=post.pod)
    client = Client()
    client.get(reverse("elder_enter", args=[elder_tokens.mint(elder)]))
    assert client.get(reverse("serve_profile_photo", args=[photo.token])).status_code == 200

    elder.token_generation += 1
    elder.save(update_fields=["token_generation"])
    assert client.get(reverse("serve_profile_photo", args=[photo.token])).status_code == 404


def test_a_digest_token_reaches_no_face_at_all(world: dict[str, object]) -> None:
    """The ceiling the credential carries. A digest link is minted to render one issue's
    posts; a face is in no issue, so honouring it here would turn a one-week read link
    into a standing "what does everyone in this family look like" credential."""
    author, pod_mate, maternal = world["author"], world["pod_mate"], world["maternal"]
    assert isinstance(author, Member) and isinstance(pod_mate, Member)
    assert isinstance(maternal, Yard)
    photo = _photo_of(author)
    window_end = timezone.now() + datetime.timedelta(hours=1)
    issue = DigestIssue.objects.create(
        member=pod_mate,
        yard=maternal,
        window_start=window_end - datetime.timedelta(days=7),
        window_end=window_end,
    )
    raw = digest_links.mint(issue)
    url = reverse("serve_profile_photo", args=[photo.token])
    assert Client().get(f"{url}?d={raw}").status_code == 404


def test_a_removed_photo_stops_being_served(
    world: dict[str, object], django_capture_on_commit_callbacks: object
) -> None:
    """Removing it deletes the files, so there is nothing left to serve even to the
    viewer who was entitled to it a second earlier (T-MEDIA-6)."""
    author, pod_mate = world["author"], world["pod_mate"]
    assert isinstance(author, Member) and isinstance(pod_mate, Member)
    photo = _photo_of(author)
    client = _client_for(pod_mate)
    assert client.get(reverse("serve_profile_photo", args=[photo.token])).status_code == 200

    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        media.purge_profile_photo(author)
    assert not photo.image.storage.exists(photo.image.name)
    assert client.get(reverse("serve_profile_photo", args=[photo.token])).status_code == 404


def test_the_scoping_rule_is_the_directory_rule(world: dict[str, object]) -> None:
    """Stated at the query, not only through the view: one audience function per object
    (TM-2), and this one is visible_members."""
    author, pod_mate, other = world["author"], world["pod_mate"], world["other"]
    assert isinstance(author, Member) and isinstance(pod_mate, Member)
    assert isinstance(other, Member)
    photo = _photo_of(author)
    assert photo.pk in set(scoping.visible_profile_photos(pod_mate).values_list("pk", flat=True))
    assert photo.pk not in set(scoping.visible_profile_photos(other).values_list("pk", flat=True))


# --- Settings: adding, replacing and removing -------------------------------------


def test_a_member_uploads_replaces_and_removes_their_own_photo(
    world: dict[str, object],
) -> None:
    author = world["author"]
    assert isinstance(author, Member)
    client = _client_for(author)

    added = client.post(
        reverse("profile_edit"), {"photo_action": "upload", "photo": _upload()}, follow=True
    )
    assert added.status_code == 200
    first = ProfilePhoto.objects.get(member=author)

    client.post(reverse("profile_edit"), {"photo_action": "upload", "photo": _upload()})
    replaced = ProfilePhoto.objects.get(member=author)
    assert replaced.pk != first.pk  # one row, a new one

    client.post(reverse("profile_edit"), {"photo_action": "remove"})
    assert not ProfilePhoto.objects.filter(member=author).exists()


def test_uploading_a_photo_does_not_disturb_the_profile_beside_it(
    world: dict[str, object],
) -> None:
    """The photo is its own form, so the name and the dates are not re-validated by it —
    and a member whose upload fails does not lose what they typed below."""
    author = world["author"]
    assert isinstance(author, Member)
    author.kinship_name = "Nana"
    author.save(update_fields=["kinship_name"])
    _client_for(author).post(reverse("profile_edit"), {"photo_action": "upload", "photo": _upload()})
    author.refresh_from_db()
    assert author.display_name == "Author" and author.kinship_name == "Nana"


def test_a_parent_sets_their_supervised_child_s_photo(world: dict[str, object]) -> None:
    """Same rule that already lets them edit that profile (S-901 acceptance 3), not a
    second one: a child account has no sign-in of its own."""
    author, m_pod = world["author"], world["m_pod"]
    assert isinstance(author, Member) and isinstance(m_pod, Pod)
    child = supervised.create_supervised_member(parent=author, display_name="Kiddo", pod=m_pod)
    response = _client_for(author).post(
        reverse("managed_profile_edit", args=[child.pk]),
        {"photo_action": "upload", "photo": _upload()},
    )
    assert response.status_code == 302
    assert ProfilePhoto.objects.filter(member=child).exists()


def test_a_pod_mate_cannot_put_a_photo_on_someone_else(world: dict[str, object]) -> None:
    """Sharing a household makes you visible to each other; it does not make you each
    other's editor."""
    author, pod_mate = world["author"], world["pod_mate"]
    assert isinstance(author, Member) and isinstance(pod_mate, Member)
    response = _client_for(pod_mate).post(
        reverse("managed_profile_edit", args=[author.pk]),
        {"photo_action": "upload", "photo": _upload()},
    )
    assert response.status_code == 403
    assert not ProfilePhoto.objects.filter(member=author).exists()


def test_the_other_side_of_the_family_is_a_404_when_it_tries(
    world: dict[str, object],
) -> None:
    """S-902 parity: across a boundary the refusal must not confirm the person exists."""
    author, other = world["author"], world["other"]
    assert isinstance(author, Member) and isinstance(other, Member)
    response = _client_for(other).post(
        reverse("managed_profile_edit", args=[author.pk]),
        {"photo_action": "upload", "photo": _upload()},
    )
    assert response.status_code == 404
    assert not ProfilePhoto.objects.filter(member=author).exists()


def test_an_upload_the_gate_rejects_says_so_and_changes_nothing(
    world: dict[str, object],
) -> None:
    author = world["author"]
    assert isinstance(author, Member)
    response = _client_for(author).post(
        reverse("profile_edit"),
        {"photo_action": "upload", "photo": SimpleUploadedFile("x.jpg", b"not an image")},
    )
    assert response.status_code == 200  # re-rendered with the sentence, not redirected
    assert "not an image Backyard can read" in response.content.decode()
    assert not ProfilePhoto.objects.filter(member=author).exists()


def test_an_upload_over_the_ceiling_is_refused_before_it_is_decoded(
    world: dict[str, object],
) -> None:
    """The composer's ceiling, not a second one: one number governs every photograph a
    member can send this product."""
    from core.feed_views import _MAX_PHOTO_BYTES

    author = world["author"]
    assert isinstance(author, Member)
    oversized = SimpleUploadedFile("big.jpg", b"\xff\xd8" + b"0" * (_MAX_PHOTO_BYTES + 1))
    response = _client_for(author).post(
        reverse("profile_edit"), {"photo_action": "upload", "photo": oversized}
    )
    assert response.status_code == 200
    assert "MB or smaller" in response.content.decode()
    assert not ProfilePhoto.objects.filter(member=author).exists()


def test_the_settings_page_offers_remove_only_when_there_is_a_photo(
    world: dict[str, object],
) -> None:
    author = world["author"]
    assert isinstance(author, Member)
    client = _client_for(author)
    assert "Remove Photo" not in client.get(reverse("profile_edit")).content.decode()
    _photo_of(author)
    page = client.get(reverse("profile_edit")).content.decode()
    assert "Remove Photo" in page and "Upload Photo" in page


# --- what the bylines draw ---------------------------------------------------------


def _avatar_src(photo: ProfilePhoto, *, large: bool = False) -> str:
    token = photo.token if large else photo.thumbnail_token
    return reverse("serve_profile_photo", args=[token])


def test_every_surface_that_draws_a_disc_draws_the_photo_instead(
    world: dict[str, object],
) -> None:
    """Feed, thread, reply, directory and profile: one tag, so one change reaches all of
    them, and the size still picks the rendition."""
    author, pod_mate, post = world["author"], world["pod_mate"], world["post"]
    assert isinstance(author, Member) and isinstance(pod_mate, Member)
    assert isinstance(post, Post)
    photo = _photo_of(author)
    client = _client_for(pod_mate)

    feed = client.get(reverse("feed")).content.decode()
    assert _avatar_src(photo) in feed
    assert f'width="{media.AVATAR_SMALL_PX}"' in feed  # sized, so nothing shifts

    thread = client.get(reverse("post_detail", args=[post.pk])).content.decode()
    assert _avatar_src(photo, large=True) in thread  # the heading disc is the large one

    directory = client.get(reverse("directory")).content.decode()
    assert _avatar_src(photo) in directory

    profile = client.get(reverse("member_profile", args=[author.pk])).content.decode()
    assert _avatar_src(photo, large=True) in profile


def test_a_reply_byline_draws_the_replier_s_photo(world: dict[str, object]) -> None:
    from core.models import Comment

    author, pod_mate, post = world["author"], world["pod_mate"], world["post"]
    assert isinstance(author, Member) and isinstance(pod_mate, Member)
    assert isinstance(post, Post)
    Comment.objects.create(post=post, author=pod_mate, body="a reply")
    photo = _photo_of(pod_mate)
    thread = _client_for(author).get(reverse("post_detail", args=[post.pk])).content.decode()
    assert _avatar_src(photo) in thread


def test_a_member_with_no_photo_still_gets_their_initials_disc(
    world: dict[str, object],
) -> None:
    """The disc is the fallback, not a removed feature: the product looks the same for
    everybody who has not uploaded anything."""
    pod_mate = world["pod_mate"]
    assert isinstance(pod_mate, Member)
    feed = _client_for(pod_mate).get(reverse("feed")).content.decode()
    assert 'class="avatar" data-tone=' in feed
    assert reverse("serve_profile_photo", args=["x"]).rsplit("x/", 1)[0] not in feed


def test_the_feed_does_not_ask_for_one_photo_per_post(world: dict[str, object]) -> None:
    """The N+1 guard, measured rather than asserted: five more authors with five more
    faces must not cost five more queries. It is the same join the gallery prefetch
    already does for the photographs ON those posts."""
    m_pod, pod_mate = world["m_pod"], world["pod_mate"]
    assert isinstance(m_pod, Pod) and isinstance(pod_mate, Member)
    client = _client_for(pod_mate)
    client.get(reverse("feed"))  # warm the session and the member lookup

    with CaptureQueriesContext(connection) as small:
        client.get(reverse("feed"))

    for index in range(5):
        author = _member_with_user(m_pod, f"Cousin{index}")
        _photo_of(author)
        Post.objects.create(author=author, pod=m_pod, body=f"post {index}")
    with CaptureQueriesContext(connection) as large:
        client.get(reverse("feed"))

    assert len(large) <= len(small), (
        f"{len(small)} queries for one post, {len(large)} for six with faces on them: "
        "the avatar is being fetched per byline"
    )


# --- lifecycle ---------------------------------------------------------------------


def test_removing_a_member_takes_their_face_with_them(
    world: dict[str, object], django_capture_on_commit_callbacks: object
) -> None:
    """Whatever the content choice. After removal they are nobody this family can look
    up, so the one rule that serves a face would refuse it beside every byline anyway —
    and the files must not sit on the volume unreachable and unpurgeable (S-702)."""
    author = world["author"]
    assert isinstance(author, Member)
    photo = _photo_of(author)
    storage = photo.image.storage
    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        removal.remove_member(author, content=removal.KEEP)
    assert not ProfilePhoto.objects.filter(member=author).exists()
    assert not storage.exists(photo.image.name)
    assert not storage.exists(photo.thumbnail.name)


def test_the_export_carries_the_member_s_own_profile_photo(
    world: dict[str, object],
) -> None:
    """"Download Your Data" means their data, and a face they uploaded is theirs
    (S-704)."""
    author = world["author"]
    assert isinstance(author, Member)
    _photo_of(author)
    archive = zipfile.ZipFile(io.BytesIO(export.build_member_export(author)))
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["member"]["profile_photo"] == "profile-photo.jpg"
    assert Image.open(io.BytesIO(archive.read("profile-photo.jpg"))).size == (
        media.AVATAR_FULL_PX,
        media.AVATAR_FULL_PX,
    )


def test_an_export_without_a_photo_says_so_rather_than_naming_a_missing_file(
    world: dict[str, object],
) -> None:
    author = world["author"]
    assert isinstance(author, Member)
    archive = zipfile.ZipFile(io.BytesIO(export.build_member_export(author)))
    assert json.loads(archive.read("manifest.json"))["member"]["profile_photo"] is None
    assert "profile-photo.jpg" not in archive.namelist()
