"""Media must survive the TM-3 confirmation hop, and any drop must be said out loud.

Two silent-failure defects from the honest audit, both in the compose path:

* **BLOCKER** — attaching photos or a video AND picking a yard audience discarded the
  media. The confirmation page is an ordinary form with no ``enctype`` and no file
  inputs, so the re-POST arrived with an empty ``request.FILES`` and the post was created
  with nothing attached. The most valuable post type in the product — photos aimed at a
  whole side of the family — silently became a caption.
* **HIGH** — photos past the 20-cap, oversized photos and undecodable files were dropped
  with a bare ``continue``: real family data loss under a success message.

The whole point is the NEGATIVE space, so each test asserts on what the post actually
holds and what the member is actually told, never on a status code alone.
"""

from __future__ import annotations

import io

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import Client
from django.urls import reverse
from PIL import Image

from core.models import MediaAsset, Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_TEST_PW = "a-Strong-passphrase-9"  # fixture credential, matches the other suites


def _jpeg(size: tuple[int, int] = (60, 40), colour: tuple[int, int, int] = (30, 92, 70)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="JPEG")
    return buf.getvalue()


def _upload(name: str = "camp.jpg", raw: bytes | None = None) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, raw if raw is not None else _jpeg(), content_type="image/jpeg")


@pytest.fixture
def world() -> dict[str, object]:
    yard = Yard.objects.create(name="Whitfields", slug="whitfields")
    pod = Pod.objects.create(name="Our house")
    pod.yards.set([yard])
    user = User.objects.create_user(username="priya", password=_TEST_PW)
    member = Member.objects.create(display_name="Priya", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return {"yard": yard, "pod": pod, "member": member, "client": client}


def _compose(client: Client, pod: Pod, yard: Yard | None, **extra: object) -> HttpResponse:
    data: dict[str, object] = {"body": "Camp dump, finally", "pod_id": pod.id}
    if yard is not None:
        data["audience_yards"] = yard.id
    data.update(extra)
    response = client.post(reverse("compose"), data)
    assert isinstance(response, HttpResponse)
    return response


def test_a_photo_survives_the_yard_audience_confirmation(world: dict[str, object]) -> None:
    """The blocker, end to end: photo + yard audience -> confirm -> the post HAS the photo.

    Before the fix this produced a post with zero media and no error of any kind.
    """
    client, pod, yard = world["client"], world["pod"], world["yard"]
    assert isinstance(client, Client) and isinstance(pod, Pod) and isinstance(yard, Yard)

    # Step 1: the composer POST that triggers TM-3 confirm-on-widen.
    first = _compose(client, pod, yard, photos=_upload())
    assert first.status_code == 200
    page = first.content.decode()
    assert "Yes, share with" in page  # we are on the confirmation page
    assert "will be posted too" in page  # and it says the photo is held
    assert Post.objects.count() == 0  # nothing created yet

    # The handle the page carries is what re-claims the bytes.
    handle = page.split('name="staged_uploads" value="')[1].split('"')[0]

    # Step 2: confirm, exactly as the browser would — no files in this request.
    second = _compose(client, pod, yard, confirm_wide="yes", staged_uploads=handle)
    assert second.status_code == 302

    post = Post.objects.get()
    assert list(post.audience_yards.all()) == [yard]  # the wide send really happened
    assert post.media.count() == 1  # ...and the photo came with it
    assert post.media.get().media_kind == MediaAsset.PHOTO


def test_the_pod_only_path_still_attaches_without_any_confirmation(
    world: dict[str, object],
) -> None:
    """The narrow path never had the bug and must not acquire one: no yard audience means
    no confirmation hop, and the photo attaches in the single request."""
    client, pod = world["client"], world["pod"]
    assert isinstance(client, Client) and isinstance(pod, Pod)
    assert _compose(client, pod, None, photos=_upload()).status_code == 302
    assert Post.objects.get().media.count() == 1


def test_staged_bytes_are_not_reusable_after_they_are_claimed(
    world: dict[str, object],
) -> None:
    """A handle is spent on use. Replaying a confirmation must not clone the photos onto
    a second post — the staged bytes are gone from both the session and the disk."""
    client, pod, yard = world["client"], world["pod"], world["yard"]
    assert isinstance(client, Client) and isinstance(pod, Pod) and isinstance(yard, Yard)
    page = _compose(client, pod, yard, photos=_upload()).content.decode()
    handle = page.split('name="staged_uploads" value="')[1].split('"')[0]
    _compose(client, pod, yard, confirm_wide="yes", staged_uploads=handle)
    _compose(client, pod, yard, confirm_wide="yes", staged_uploads=handle)  # replayed

    first, second = Post.objects.order_by("id")
    assert first.media.count() == 1
    assert second.media.count() == 0  # the replay got nothing, and said nothing untrue


def test_another_member_cannot_claim_someone_elses_staged_upload(
    world: dict[str, object],
) -> None:
    """The handle is only meaningful inside its own session. A handle lifted from one
    member's form must not attach that member's photographs to another member's post."""
    client, pod, yard = world["client"], world["pod"], world["yard"]
    assert isinstance(client, Client) and isinstance(pod, Pod) and isinstance(yard, Yard)
    page = _compose(client, pod, yard, photos=_upload()).content.decode()
    stolen = page.split('name="staged_uploads" value="')[1].split('"')[0]

    other_user = User.objects.create_user(username="mallory", password=_TEST_PW)
    other = Member.objects.create(display_name="Mallory", user=other_user)
    PodMembership.objects.create(member=other, pod=pod)
    thief = Client()
    thief.force_login(other_user, backend=_BACKEND)

    _compose(thief, pod, yard, confirm_wide="yes", staged_uploads=stolen)
    assert Post.objects.get(author=other).media.count() == 0


def test_photos_over_the_per_post_cap_are_reported_not_silently_dropped(
    world: dict[str, object],
) -> None:
    """21 photos, 20 allowed. The member must be TOLD one did not make it."""
    client, pod = world["client"], world["pod"]
    assert isinstance(client, Client) and isinstance(pod, Pod)
    response = client.post(
        reverse("compose"),
        {
            "body": "Birthday dump",
            "pod_id": pod.id,
            "photos": [_upload(f"p{i}.jpg") for i in range(21)],
        },
        follow=True,
    )
    assert Post.objects.get().media.count() == 20
    said = " ".join(str(m) for m in response.context["messages"])
    assert "1 of your 21 photos could not be added" in said
    assert "20 is the limit" in said


def test_an_undecodable_photo_is_reported_not_silently_dropped(
    world: dict[str, object],
) -> None:
    """A file the ingest gate refuses must produce a message, not a quiet gap in the
    album. HEIC forwarded from an iPhone lands here on browsers whose canvas conversion
    fails, so this is the common real case, not a synthetic one."""
    client, pod = world["client"], world["pod"]
    assert isinstance(client, Client) and isinstance(pod, Pod)
    response = client.post(
        reverse("compose"),
        {
            "body": "One good, one bad",
            "pod_id": pod.id,
            "photos": [_upload("good.jpg"), _upload("bad.jpg", raw=b"not an image at all")],
        },
        follow=True,
    )
    assert Post.objects.get().media.count() == 1
    said = " ".join(str(m) for m in response.context["messages"])
    assert "could not be added" in said
