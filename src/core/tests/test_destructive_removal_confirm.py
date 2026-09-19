"""NB-5: the delete choice takes a typed-name confirmation on a step of its own.

`remove_member(content="delete")` hard-purges a member's photographs from the volume
with no undo (T-MEDIA-6 makes that deliberate), and it sat behind ONE session POST from
a radio button on the roster — a few rows above and below four other people's Remove
buttons. The only protection was that an absent or unknown choice is refused, which is a
required form field, not a confirmation.

This is the single most destructive control the two new yard admins will hold, so the
tests are about what the confirm step REFUSES and what its page has to say out loud.
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


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (30, 20), (90, 30, 30)).save(buf, format="JPEG")
    return buf.getvalue()


class World:
    def __init__(self) -> None:
        yard = Yard.objects.create(name="Maternal", slug="maternal")
        self.pod = Pod.objects.create(name="Our house")
        self.pod.yards.set([yard])

        admin_user = User.objects.create_user(username="admin")
        self.admin = Member.objects.create(
            display_name="The Admin", user=admin_user, role=Member.YARD_ADMIN
        )
        PodMembership.objects.create(member=self.admin, pod=self.pod)

        self.leaver = Member.objects.create(
            display_name="Robin", user=User.objects.create_user(username="robin")
        )
        PodMembership.objects.create(member=self.leaver, pod=self.pod)
        self.other = Member.objects.create(
            display_name="Sam", user=User.objects.create_user(username="sam")
        )
        PodMembership.objects.create(member=self.other, pod=self.pod)

        # Two of Robin's posts, a photo on one, Robin's own reply, and SAM's reply with a
        # photo on it — the one an admin would not expect to lose.
        self.post = Post.objects.create(author=self.leaver, pod=self.pod, body="a thing Robin said")
        media.ingest_photo(post=self.post, raw=_jpeg())
        Post.objects.create(author=self.leaver, pod=self.pod, body="and another")
        Comment.objects.create(post=self.post, author=self.leaver, body="Robin replying")
        sams_reply = Comment.objects.create(post=self.post, author=self.other, body="Sam replying")
        media.ingest_photo(comment=sams_reply, raw=_jpeg())

        self.client = Client()
        self.client.force_login(admin_user, backend=_BACKEND)

    def remove_url(self) -> str:
        return reverse("member_remove", args=[self.leaver.pk])


@pytest.fixture
def world() -> World:
    return World()


def test_the_delete_choice_alone_destroys_nothing(world: World) -> None:
    """The POST the roster's radio makes. It must land on a confirm page, not act."""
    response = world.client.post(world.remove_url(), {"content": removal.DELETE})

    assert response.status_code == 200, "a delete POST redirected, so it acted"
    world.leaver.refresh_from_db()
    assert world.leaver.user is not None and world.leaver.user.is_active
    world.post.refresh_from_db()
    assert world.post.deleted_at is None
    assert MediaAsset.objects.filter(deleted_at__isnull=True).count() == 2


def test_a_wrong_name_destroys_nothing_and_says_so(world: World) -> None:
    response = world.client.post(
        world.remove_url(), {"content": removal.DELETE, "confirm_name": "Robyn"}
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "Robin" in body, "the page does not say which name to type"
    world.post.refresh_from_db()
    assert world.post.deleted_at is None


def test_the_confirm_page_states_what_it_will_destroy(world: World) -> None:
    """ "It cannot be undone" is only useful beside WHAT. The counts come from the same
    querysets `_delete_content` deletes from, so the sentence cannot drift from the act."""
    body = world.client.post(world.remove_url(), {"content": removal.DELETE}).content.decode()

    assert "cannot be undone" in body.lower()
    preview = removal.preview_deletion(world.leaver)
    assert (preview.posts, preview.replies, preview.photos) == (2, 1, 2)
    assert preview.others_photos == 1, "Sam's reply photo is not counted"
    for number in (preview.posts, preview.replies, preview.photos):
        assert f"<strong>{number}</strong>" in body
    # The surprising half, said out loud: deleting Robin's post takes the photographs off
    # OTHER people's replies to it, because purge_post_media reaches them through the post.
    assert "other people" in body.lower()


def test_the_typed_name_lets_it_through(
    world: World, django_capture_on_commit_callbacks: object
) -> None:
    import os

    stored = MediaAsset.objects.get(post=world.post).image.path
    assert os.path.exists(stored), "the fixture wrote no file; this would prove nothing"

    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        response = world.client.post(
            world.remove_url(), {"content": removal.DELETE, "confirm_name": "Robin"}
        )

    assert response.status_code == 302
    world.post.refresh_from_db()
    assert world.post.deleted_at is not None
    assert not os.path.exists(stored)


def test_the_name_check_forgives_case_and_stray_spaces(world: World) -> None:
    """A phone capitalises the first letter and adds a trailing space on autocomplete. The
    step exists to make the act deliberate, not to test anybody's typing."""
    response = world.client.post(
        world.remove_url(), {"content": removal.DELETE, "confirm_name": "  robin "}
    )
    assert response.status_code == 302


def test_an_empty_name_is_never_a_match(world: World) -> None:
    """The property the first POST depends on: a blank box must not read as agreement,
    including for a member whose display name is somehow blank."""
    world.leaver.display_name = ""
    world.leaver.save(update_fields=["display_name"])
    response = world.client.post(
        world.remove_url(), {"content": removal.DELETE, "confirm_name": "  "}
    )
    assert response.status_code == 200


@pytest.mark.parametrize("choice", [removal.KEEP, removal.ANONYMIZE])
def test_the_two_non_destructive_choices_are_still_one_step(world: World, choice: str) -> None:
    """The confirmation is priced against destruction, not against removal. Neither of
    these erases a file, and making an admin type a name for them would train them to
    type it for the third one too."""
    assert world.client.post(world.remove_url(), {"content": choice}).status_code == 302
    world.leaver.refresh_from_db()
    assert world.leaver.user is not None and not world.leaver.user.is_active


def test_a_missing_choice_is_still_refused(world: World) -> None:
    """The older guard has not been traded away for the new one."""
    assert world.client.post(world.remove_url(), {}).status_code == 400


def test_the_confirm_step_is_not_an_authorization_hole(world: World) -> None:
    """The confirm page is rendered AFTER the permission check, and a typed name is not a
    permission. A yard admin with a correct name for someone out of scope gets nothing."""
    other_yard = Yard.objects.create(name="Paternal", slug="paternal")
    far_pod = Pod.objects.create(name="Their house")
    far_pod.yards.set([other_yard])
    far = Member.objects.create(
        display_name="Far Cousin", user=User.objects.create_user(username="far")
    )
    PodMembership.objects.create(member=far, pod=far_pod)

    response = world.client.post(
        reverse("member_remove", args=[far.pk]),
        {"content": removal.DELETE, "confirm_name": "Far Cousin"},
    )
    assert response.status_code == 404
    far.user.refresh_from_db()
    assert far.user.is_active


def test_the_roster_warns_before_the_step(world: World) -> None:
    """The warning is on the page where the choice is made, not only after it."""
    body = world.client.get(reverse("members")).content.decode()
    assert "for good" in body.lower()
    assert "confirm" in body.lower()
