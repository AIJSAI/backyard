"""Bounds on staged uploads, and the shortfall that must never be silent.

Every test here corresponds to a live-reproduced security-review finding on the first cut
of this feature. The review's own probes are the specification:

* HIGH-1 — the per-post caps were applied to each request's upload but NOT to the merged
  claimed+new list, so looping the composer's error path accumulated 20 more photos per
  round onto one post (proven: 60 on one post), with every raw held in memory at once
  against a 768 MB container running three gunicorn workers.
* HIGH-3 — `claim()`'s docstring promised the caller compares what it staged with what it
  got back. No caller did. A sweep crossing the TTL between render and confirm produced
  `MEDIA: 0 | MESSAGES: ''` — the exact silent data loss this module exists to prevent.
* HIGH-5 — the TTL claimed 6 hours while a once-daily sweep made real retention ~30, and
  nothing anywhere tested the sweep, the TTL, or the task registration.
* MEDIUM-2 — Cancel was a bare link; `discard()` had zero callers and the code comment
  claiming the cancel path released the files was false.
"""

from __future__ import annotations

import datetime
import io
import os

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from PIL import Image

from core import staged_uploads
from core.feed_views import _MAX_PHOTOS
from core.models import Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_TEST_PW = "a-Strong-passphrase-9"


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (30, 92, 70)).save(buf, format="JPEG")
    return buf.getvalue()


def _upload(name: str = "p.jpg") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, _jpeg(), content_type="image/jpeg")


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


def _handle_from(page: str) -> str:
    return page.split('name="staged_uploads" value="')[1].split('"')[0]


def test_looping_the_error_path_cannot_pile_photos_past_the_per_post_cap(
    world: dict[str, object],
) -> None:
    """HIGH-1, the review's own attack: stage 20, re-stage 20 more, repeat, then post.

    The caps must hold over the MERGED list. Before the fix this produced 60 photos on
    one post — every per-post ceiling bypassed, and 900 MB resident in a 768 MB container.
    """
    client, pod, yard = world["client"], world["pod"], world["yard"]
    assert isinstance(client, Client) and isinstance(pod, Pod) and isinstance(yard, Yard)

    handle = ""
    for _ in range(3):
        data: dict[str, object] = {
            "body": "",  # empty body -> the error path, which re-stages
            "pod_id": pod.id,
            "audience_yards": yard.id,
            "photos": [_upload(f"r{i}.jpg") for i in range(_MAX_PHOTOS)],
        }
        if handle:
            data["staged_uploads"] = handle
        handle = _handle_from(client.post(reverse("compose"), data).content.decode())

    client.post(
        reverse("compose"),
        {
            "body": "finally",
            "pod_id": pod.id,
            "audience_yards": yard.id,
            "confirm_wide": "yes",
            "staged_uploads": handle,
        },
    )
    assert Post.objects.get().media.count() == _MAX_PHOTOS


def test_a_claim_that_came_up_short_is_reported_not_swallowed(
    world: dict[str, object],
) -> None:
    """HIGH-3: the sweep crosses the TTL while the member hesitates over the confirmation.

    The post still goes out — their words are not held hostage to their photos — but the
    member is TOLD the uploads expired. Silence here is the original defect, relocated.
    """
    client, pod, yard = world["client"], world["pod"], world["yard"]
    assert isinstance(client, Client) and isinstance(pod, Pod) and isinstance(yard, Yard)
    page = client.post(
        reverse("compose"),
        {"body": "Camp dump", "pod_id": pod.id, "audience_yards": yard.id, "photos": _upload()},
    ).content.decode()
    handle = _handle_from(page)

    staged_uploads.sweep(datetime.timedelta(seconds=0))  # the 04:45 sweep, mid-hesitation

    response = client.post(
        reverse("compose"),
        {
            "body": "Camp dump",
            "pod_id": pod.id,
            "audience_yards": yard.id,
            "confirm_wide": "yes",
            "staged_uploads": handle,
        },
        follow=True,
    )
    said = " ".join(str(m) for m in response.context["messages"])
    assert "expired before you confirmed" in said
    assert Post.objects.get().media.count() == 0  # honestly zero, and honestly reported


def test_cancel_releases_the_staged_bytes_immediately(world: dict[str, object]) -> None:
    """MEDIUM-2: Cancel was a bare link to the feed, so photographs sat on disk until the
    sweep — while a code comment claimed the cancel path released them."""
    client, pod, yard = world["client"], world["pod"], world["yard"]
    assert isinstance(client, Client) and isinstance(pod, Pod) and isinstance(yard, Yard)
    page = client.post(
        reverse("compose"),
        {"body": "Camp dump", "pod_id": pod.id, "audience_yards": yard.id, "photos": _upload()},
    ).content.decode()
    handle = _handle_from(page)
    staging = staged_uploads._staging_dir()
    assert os.listdir(staging), "nothing was staged, so this test proves nothing"

    assert client.post(reverse("compose_cancel"), {"staged_uploads": handle}).status_code == 302
    assert os.listdir(staging) == []


def test_cancel_refuses_a_get_so_a_prefetch_cannot_destroy_an_upload(
    world: dict[str, object],
) -> None:
    client = world["client"]
    assert isinstance(client, Client)
    assert client.get(reverse("compose_cancel")).status_code == 404


def test_the_sweep_collects_files_past_the_ttl_and_spares_fresh_ones(
    world: dict[str, object],
) -> None:
    """HIGH-5: the "bytes do not linger" guarantee had zero coverage of any kind."""
    client, pod, yard = world["client"], world["pod"], world["yard"]
    assert isinstance(client, Client) and isinstance(pod, Pod) and isinstance(yard, Yard)
    client.post(
        reverse("compose"),
        {"body": "Camp dump", "pod_id": pod.id, "audience_yards": yard.id, "photos": _upload()},
    )
    staging = staged_uploads._staging_dir()
    assert len(os.listdir(staging)) == 1

    assert staged_uploads.sweep(datetime.timedelta(hours=6)) == 0  # fresh: spared
    assert len(os.listdir(staging)) == 1
    assert staged_uploads.sweep(datetime.timedelta(seconds=0)) == 1  # past the TTL: taken
    assert os.listdir(staging) == []


def test_the_sweep_is_registered_hourly_not_daily() -> None:
    """The TTL is 6 hours; a once-daily cron made real worst-case retention ~30, so the
    documented guarantee was not the delivered one."""
    from core import tasks

    assert tasks.sweep_staged_uploads_task.name == "sweep_staged_uploads"

    # Read the decorator IMMEDIATELY above the function, not "everything before it".
    #
    # `.split("def sweep_staged_uploads")[0]` had two ways to lie. If the function were
    # renamed, `str.split` returns `[whole_text]` and `[0]` becomes the ENTIRE module — so any
    # other periodic's `cron="45 * * * *"` would satisfy this. And even intact, the prefix
    # contains every task declared above this one, so a matching cron anywhere earlier passes.
    # A denominator that can silently widen to the whole file is not a denominator.
    source = __import__("pathlib").Path(tasks.__file__).read_text()
    marker = "def sweep_staged_uploads"
    assert marker in source, (
        "sweep_staged_uploads was renamed; this check would otherwise read the whole module "
        "and pass on any other task's schedule"
    )
    # The block between the previous decorator and the function definition.
    before = source[: source.index(marker)]
    decorator = before[before.rindex("@app.periodic") :]
    assert 'cron="45 * * * *"' in decorator, (
        f"the sweep must run hourly; its own decorator says: {decorator.strip()[:120]}"
    )


def test_one_session_cannot_park_unbounded_bytes_in_staging(
    world: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """HIGH-5's other half: no quota existed anywhere, so looping the error path with a
    FRESH handle each time (never claiming) parked hundreds of MB per request on the same
    volume as the served media, the backups and the persisted secret key."""
    monkeypatch.setattr(staged_uploads, "MAX_SESSION_STAGED_BYTES", len(_jpeg()) * 3)
    client, pod, yard = world["client"], world["pod"], world["yard"]
    assert isinstance(client, Client) and isinstance(pod, Pod) and isinstance(yard, Yard)
    staging = staged_uploads._staging_dir()

    for _ in range(6):  # never confirm, never cancel: a fresh handle every round
        client.post(
            reverse("compose"),
            {"body": "", "pod_id": pod.id, "audience_yards": yard.id, "photos": _upload()},
        )

    assert len(os.listdir(staging)) <= 3, os.listdir(staging)
