"""Taking somebody's post down asks first, and then says it happened.

From the production walk, 2026-09-19. A side admin taps "Take down" on a relative's post
and it is gone that instant: a 404 for everyone, the photographs purged from the volume
with no undo, no confirm page, no message. Two taps away, the day-one guide promises the
new admin that "nothing here is a one-tap disaster". The author's OWN delete route had
asked for a second tap since the beginning — the route that erases somebody ELSE's
photographs did not.

Three findings in one family, all on the same screens:

  ITEM 6   an admin reading their own post was offered Delete AND Take down, side by side
           in the same red. Taking down your own post is what Delete already does, so the
           pair was two names for one outcome and a chance to pick the wrong one.
  ITEM 29  the takedown fired on a single tap, for a post and for a reply.
  ITEM 10  deleting a post said nothing afterwards, on a phone where the post was already
           below the fold.

What is deliberately NOT changed: the permission ORDER. Admin first (403), then the read
guard (404), so neither the confirm page nor the action itself tells a stranger whether a
post exists — the byte-identical 404 that S-202 isolation rests on. The last two tests
here are what hold that.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core.models import Comment, Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"


@pytest.fixture
def world() -> dict[str, object]:
    """One household, an admin, and a relative with a post and a reply in it."""
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])

    admin_user = User.objects.create_user(username="admin")
    admin = Member.objects.create(
        display_name="Ada Reed", user=admin_user, role=Member.INSTANCE_ADMIN
    )
    PodMembership.objects.create(member=admin, pod=pod)

    author_user = User.objects.create_user(username="cousin")
    author = Member.objects.create(display_name="Cousin Reed", user=author_user)
    PodMembership.objects.create(member=author, pod=pod)

    post = Post.objects.create(author=author, pod=pod, body="Camp dump, finally.")
    post.audience_yards.set([yard])
    comment = Comment.objects.create(post=post, author=author, body="And one more.")

    client = Client()
    client.force_login(admin_user, backend=_BACKEND)
    return {
        "client": client,
        "admin": admin,
        "admin_user": admin_user,
        "author": author,
        "author_user": author_user,
        "pod": pod,
        "yard": yard,
        "post": post,
        "comment": comment,
    }


def _client(world: dict[str, object]) -> Client:
    client = world["client"]
    assert isinstance(client, Client)
    return client


def _post(world: dict[str, object]) -> Post:
    post = world["post"]
    assert isinstance(post, Post)
    return post


# --- item 29: the confirm page --------------------------------------------------------


def test_opening_take_down_on_a_post_asks_rather_than_acting(world: dict[str, object]) -> None:
    """The whole item: a GET must CONFIRM, and must not be the thing that destroys."""
    post = _post(world)
    page = _client(world).get(reverse("take_down_post", args=[post.id]))

    assert page.status_code == 200, page.status_code
    body = page.content.decode()
    assert "Take This Post Down?" in body
    assert "Cousin Reed wrote this." in body, "the page does not say whose post it is"
    assert "Camp dump, finally." in body, "the admin cannot see what they are about to erase"
    assert "permanently deletes its photos" in body
    assert "is not told" in body, "it does not say the author is never told"
    assert "Cancel" in body, "there is no quiet way out"

    post.refresh_from_db()
    assert post.deleted_at is None, "LOADING the confirm page took the post down"


def test_confirming_takes_it_down_and_says_so(world: dict[str, object]) -> None:
    post = _post(world)
    page = _client(world).post(reverse("take_down_post", args=[post.id]), follow=True)

    assert page.status_code == 200
    post.refresh_from_db()
    assert post.deleted_at is not None, "the POST did not take the post down"
    body = page.content.decode()
    assert "Post taken down." in body
    # Through the flash component the composer already uses, not a bespoke banner.
    assert 'class="messages"' in body and 'role="status"' in body


def test_a_reply_gets_the_same_two_taps(world: dict[str, object]) -> None:
    """A reply is somebody's words too, and taking one down was the same one-tap action."""
    comment = world["comment"]
    assert isinstance(comment, Comment)
    client = _client(world)

    page = client.get(reverse("take_down_comment", args=[comment.id]))
    assert page.status_code == 200
    body = page.content.decode()
    assert "Take This Reply Down?" in body
    assert "And one more." in body
    comment.refresh_from_db()
    assert comment.deleted_at is None, "LOADING the confirm page took the reply down"

    done = client.post(reverse("take_down_comment", args=[comment.id]), follow=True)
    comment.refresh_from_db()
    assert comment.deleted_at is not None
    assert "Reply taken down." in done.content.decode()


def test_the_confirm_page_is_not_a_way_around_the_guards(world: dict[str, object]) -> None:
    """The order that matters, asserted on the NEW surface.

    A non-admin is refused before the post is ever resolved, and a post the admin cannot
    see is a bare 404 — so the confirm page cannot be used to ask "does post 41 exist?"
    or to read a post from the other side of the family.
    """
    post = _post(world)
    author_user = world["author_user"]
    assert isinstance(author_user, User)

    ordinary = Client()
    ordinary.force_login(author_user, backend=_BACKEND)
    refused = ordinary.get(reverse("take_down_post", args=[post.id]))
    assert refused.status_code == 403, refused.status_code

    missing = _client(world).get(reverse("take_down_post", args=[post.id + 9999]))
    assert missing.status_code == 404, missing.status_code
    post.refresh_from_db()
    assert post.deleted_at is None


def test_a_post_on_the_other_side_of_the_family_is_a_404_not_a_preview(
    world: dict[str, object],
) -> None:
    """The isolation case. A side admin who can reach the confirm page for a post they
    cannot READ would be handed its body and its author's name on that page — which is
    exactly the leak the byte-identical 404 exists to prevent."""
    other_yard = Yard.objects.create(name="Dad's side", slug="dads-side")
    other_pod = Pod.objects.create(name="The Ferraras", kind=Pod.HOUSEHOLD)
    other_pod.yards.set([other_yard])
    stranger = Member.objects.create(display_name="Dave Ferrara")
    PodMembership.objects.create(member=stranger, pod=other_pod)
    hidden = Post.objects.create(author=stranger, pod=other_pod, body="A secret thing")
    hidden.audience_yards.set([other_yard])

    side_admin_user = User.objects.create_user(username="sideadmin")
    side_admin = Member.objects.create(
        display_name="Sam Reed", user=side_admin_user, role=Member.YARD_ADMIN
    )
    pod = world["pod"]
    assert isinstance(pod, Pod)
    PodMembership.objects.create(member=side_admin, pod=pod)

    client = Client()
    client.force_login(side_admin_user, backend=_BACKEND)
    page = client.get(reverse("take_down_post", args=[hidden.id]))
    assert page.status_code == 404, page.status_code
    assert b"A secret thing" not in page.content


# --- item 6: never both Delete and Take down on your own post -------------------------


def test_an_admin_reading_their_own_post_is_offered_edit_and_delete_only(
    world: dict[str, object],
) -> None:
    pod = world["pod"]
    admin = world["admin"]
    yard = world["yard"]
    assert isinstance(pod, Pod) and isinstance(admin, Member) and isinstance(yard, Yard)
    mine = Post.objects.create(author=admin, pod=pod, body="My own post")
    mine.audience_yards.set([yard])

    body = _client(world).get(reverse("feed")).content.decode()
    row = body[body.index("My own post") :]
    row = row[: row.index("</li>")]
    assert reverse("delete_post", args=[mine.id]) in row
    assert reverse("take_down_post", args=[mine.id]) not in row, (
        "an admin's own post still offers Take down beside Delete — two names for one "
        "outcome, in the same red, on a control that erases photographs"
    )


def test_somebody_else_s_post_still_offers_take_down(world: dict[str, object]) -> None:
    """Non-vacuity for the test above: the affordance did not simply disappear."""
    post = _post(world)
    body = _client(world).get(reverse("feed")).content.decode()
    assert reverse("take_down_post", args=[post.id]) in body


def test_the_thread_page_follows_the_same_two_rules(world: dict[str, object]) -> None:
    """Item 19 as well: on the thread it was a large outlined BUTTON between the post and
    the reactions — the loudest control on a page about somebody's photograph."""
    post = _post(world)
    body = _client(world).get(reverse("post_detail", args=[post.id])).content.decode()
    assert f'href="{reverse("take_down_post", args=[post.id])}"' in body, (
        "the thread's takedown is not a link, so it cannot reach the confirm page"
    )
    assert "Take Down Post</button>" not in body, "it is still a button that fires on a tap"


# --- item 10: a delete says so --------------------------------------------------------


def test_deleting_your_own_post_says_so(world: dict[str, object]) -> None:
    pod = world["pod"]
    admin = world["admin"]
    yard = world["yard"]
    assert isinstance(pod, Pod) and isinstance(admin, Member) and isinstance(yard, Yard)
    mine = Post.objects.create(author=admin, pod=pod, body="My own post")
    mine.audience_yards.set([yard])

    page = _client(world).post(reverse("delete_post", args=[mine.id]), follow=True)
    body = page.content.decode()
    assert "Post deleted." in body
    assert 'class="messages"' in body and 'role="status"' in body
