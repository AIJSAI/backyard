"""S-702 acceptance 2: "Admin explicitly chooses: keep content attributed, anonymize, or
delete."

The story sat at `passing` while removal was a single POST with no decision in it. The
module's own docstring deferred this to "the feed and media waves", which never came — so
every removal silently kept everything, which is the one outcome that needs no button.

The three outcomes are tested by what actually happens to the content, not by whether the
view returned a 302.
"""

from __future__ import annotations

import io

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from PIL import Image

from core import media, removal
from core.models import Comment, MediaAsset, Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_TEST_PW = "a-Strong-passphrase-9"


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (30, 92, 70)).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def world() -> dict[str, object]:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Our house")
    pod.yards.set([yard])
    user = User.objects.create_user(username="leaver", password=_TEST_PW)
    leaver = Member.objects.create(
        display_name="Robin", kinship_name="Rob", user=user, phone="555-0000"
    )
    PodMembership.objects.create(member=leaver, pod=pod)
    admin_user = User.objects.create_user(username="admin", password=_TEST_PW)
    admin = Member.objects.create(
        display_name="The Admin", user=admin_user, role=Member.INSTANCE_ADMIN
    )
    PodMembership.objects.create(member=admin, pod=pod)

    post = Post.objects.create(author=leaver, pod=pod, body="a thing Robin said")
    media.ingest_photo(post=post, raw=_jpeg())
    Comment.objects.create(post=post, author=leaver, body="and a reply from Robin")
    return {"pod": pod, "leaver": leaver, "admin": admin, "post": post}


def test_keep_leaves_the_history_exactly_as_it_was(world: dict[str, object]) -> None:
    """Someone who simply left. Their words stay, attributed to them."""
    leaver, post = world["leaver"], world["post"]
    assert isinstance(leaver, Member) and isinstance(post, Post)
    removal.remove_member(leaver, content=removal.KEEP)

    post.refresh_from_db()
    leaver.refresh_from_db()
    assert post.deleted_at is None
    assert leaver.display_name == "Robin"
    assert post.media.filter(deleted_at__isnull=True).count() == 1


def test_anonymize_keeps_the_thread_but_removes_the_person(
    world: dict[str, object],
) -> None:
    """The content stays readable; it just no longer points at a named individual."""
    leaver, post = world["leaver"], world["post"]
    assert isinstance(leaver, Member) and isinstance(post, Post)
    removal.remove_member(leaver, content=removal.ANONYMIZE)

    post.refresh_from_db()
    leaver.refresh_from_db()
    assert post.deleted_at is None, "anonymize keeps the content"
    assert post.body == "a thing Robin said"
    assert leaver.display_name == removal.ANONYMOUS_NAME
    assert leaver.kinship_name == ""
    assert leaver.phone == "", "contact details must not survive anonymisation"
    assert leaver.birthday_month is None


def test_delete_removes_their_posts_replies_and_photo_bytes(
    world: dict[str, object], django_capture_on_commit_callbacks: object
) -> None:
    """For the case this exists for: someone whose presence in the archive is the harm.

    Posts and comments are SOFT-deleted so the archive-compatibility guarantees hold,
    but media is purged the same way a member deleting their own post already purges it
    (T-MEDIA-6): the row is dropped and the FILES leave the disk, because a photograph
    must not survive after someone has been told it is gone.
    """
    import os

    leaver, post = world["leaver"], world["post"]
    assert isinstance(leaver, Member) and isinstance(post, Post)
    asset_pk = post.media.get().pk
    stored = post.media.get().image.path
    assert os.path.exists(stored), "the fixture never wrote a file; this would prove nothing"

    # purge_post_media unlinks the FILES on commit, deliberately: a rollback must never
    # leave a live row pointing at a deleted file. A test transaction never commits, so
    # the callbacks are run explicitly — otherwise this would assert nothing about bytes.
    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        removal.remove_member(leaver, content=removal.DELETE)

    post.refresh_from_db()
    assert post.deleted_at is not None
    assert Comment.objects.get(author=leaver).deleted_at is not None
    assert not MediaAsset.objects.filter(pk=asset_pk).exists(), "the media row survived"
    assert not os.path.exists(stored), "the photo bytes are still on disk"


def test_removal_refuses_without_an_explicit_choice(world: dict[str, object]) -> None:
    """No default. A default would silently keep everything — the exact behaviour this
    criterion exists to replace."""
    leaver = world["leaver"]
    assert isinstance(leaver, Member)
    with pytest.raises(removal.UnknownContentChoice):
        removal.remove_member(leaver, content="")
    with pytest.raises(removal.UnknownContentChoice):
        removal.remove_member(leaver, content="whatever-the-caller-felt-like")
    leaver.refresh_from_db()
    assert leaver.display_name == "Robin", "a refused removal must change nothing"


def test_the_roster_offers_all_three_choices_and_the_view_requires_one(
    world: dict[str, object],
) -> None:
    """End to end through the admin surface, because that is where the decision is made."""
    admin, leaver = world["admin"], world["leaver"]
    assert isinstance(admin, Member) and isinstance(leaver, Member)
    assert admin.user is not None
    client = Client()
    client.force_login(admin.user, backend=_BACKEND)

    page = client.get(reverse("members")).content.decode()
    for value, _label in removal.CONTENT_CHOICES:
        assert f'value="{value}"' in page, f"the roster does not offer {value}"

    # A POST with no choice is refused, and the member is untouched.
    assert client.post(reverse("member_remove", args=[leaver.pk]), {}).status_code == 400
    leaver.refresh_from_db()
    assert leaver.user is not None and leaver.user.is_active

    # ...and with a choice it goes through, applying that choice.
    response = client.post(
        reverse("member_remove", args=[leaver.pk]), {"content": removal.ANONYMIZE}
    )
    assert response.status_code == 302
    leaver.refresh_from_db()
    assert leaver.display_name == removal.ANONYMOUS_NAME


def test_every_choice_still_revokes_credentials(world: dict[str, object]) -> None:
    """The content decision must never weaken the revocation half: whichever outcome the
    admin picks, the person is out."""
    pod = world["pod"]
    assert isinstance(pod, Pod)
    for index, choice in enumerate((removal.KEEP, removal.ANONYMIZE, removal.DELETE)):
        user = User.objects.create_user(username=f"gone{index}", password=_TEST_PW)
        member = Member.objects.create(display_name=f"Gone {index}", user=user)
        PodMembership.objects.create(member=member, pod=pod)

        removal.remove_member(member, content=choice)

        user.refresh_from_db()
        assert not user.is_active, choice
        assert not PodMembership.objects.filter(member=member).exists(), choice
