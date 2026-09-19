"""Tapping the button tells you something happened (C4/F6, and the draft that survives).

Three findings from the walk, all the same shape — the product does a thing and says
nothing, so the member cannot tell whether it worked:

  POST    tapping Post reloaded the feed with no message of any kind, and on a phone the
          new post lands about seventeen hundred pixels below the fold, so nothing
          visibly changed. Meanwhile the product cheerfully announced "Successfully
          signed in as priya" — it spoke about the least important event it knows and
          stayed silent on the most important one. A relative taps Post twice.
  REPLY   the same, under a thread.
  DRAFT   (F5) leaving the confirmation page any way except answering it threw the whole
          post away. The photos were already held server-side; the WORDS were not.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core import drafts
from core.models import Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_PW = "a-Strong-passphrase-9"
_BACKEND = "django.contrib.auth.backends.ModelBackend"


@pytest.fixture
def world() -> dict[str, object]:
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="Nana's house", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = User.objects.create_user(username="poster", password=_PW)
    member = Member.objects.create(display_name="Ann Poster", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return {"client": client, "pod": pod, "member": member, "yard": yard}


def _client(world: dict[str, object]) -> Client:
    client = world["client"]
    assert isinstance(client, Client)
    return client


def test_posting_says_so_on_the_page_the_member_lands_on(world: dict[str, object]) -> None:
    pod = world["pod"]
    assert isinstance(pod, Pod)
    page = _client(world).post(
        reverse("compose"), {"body": "Pie tonight", "pod_id": pod.id}, follow=True
    )
    body = page.content.decode()
    assert "Posted. Your family can see it now." in body
    # Rendered through the flash component that already exists, not a bespoke banner.
    assert 'class="messages"' in body and 'role="status"' in body


def test_replying_says_so_too(world: dict[str, object]) -> None:
    pod, member = world["pod"], world["member"]
    assert isinstance(pod, Pod) and isinstance(member, Member)
    post = Post.objects.create(author=member, pod=pod, body="a thread")
    page = _client(world).post(
        reverse("add_comment", args=[post.id]), {"body": "lovely"}, follow=True
    )
    assert "Your reply is up." in page.content.decode()


# --- F5: the draft survives leaving the confirmation ------------------------------


def _start_a_wide_post(world: dict[str, object], body: str) -> str:
    """Compose to a whole side of the family, which triggers the TM-3 confirmation."""
    pod, yard = world["pod"], world["yard"]
    assert isinstance(pod, Pod) and isinstance(yard, Yard)
    page = _client(world).post(
        reverse("compose"), {"body": body, "pod_id": pod.id, "audience_yards": [yard.id]}
    )
    assert page.status_code == 200
    return page.content.decode()


def test_the_confirmation_offers_one_primary_and_a_quiet_way_out(
    world: dict[str, object],
) -> None:
    """Cancel was a FILLED green button identical in weight to "Yes, share with …", so the
    two answers to a privacy question looked the same; and the post being confirmed sat in
    an unstyled forty-pixel browser indent."""
    page = _start_a_wide_post(world, "Camp dump, finally")
    assert 'class="btn-quiet"' in page, "cancelling must not look like confirming"
    assert 'class="quoted-post"' in page, "their own words need a real edge"
    assert page.count('<button type="submit">') == 1, "exactly one primary on the page"


def test_walking_away_from_the_confirmation_keeps_the_post(world: dict[str, object]) -> None:
    _start_a_wide_post(world, "Camp dump, finally")
    # She does not answer it: she goes back to the feed, the way the back button, the
    # header nav or a phone call would take her.
    feed = _client(world).get(reverse("feed")).content.decode()
    assert "Camp dump, finally" in feed, "her words were thrown away"
    assert "Your unfinished post is still here." in feed
    # ...and the composer opens with them showing rather than behind a tap.
    assert "is-open" in feed


def test_cancelling_is_the_one_thing_that_drops_it(world: dict[str, object]) -> None:
    _start_a_wide_post(world, "Camp dump, finally")
    _client(world).post(reverse("compose_cancel"), {})
    feed = _client(world).get(reverse("feed")).content.decode()
    assert "Camp dump, finally" not in feed
    assert "Your unfinished post is still here." not in feed


def test_posting_it_drops_it_too(world: dict[str, object]) -> None:
    """The draft has become the thing it was a draft of, so it must not come back and
    offer to be posted a second time."""
    pod, yard = world["pod"], world["yard"]
    assert isinstance(pod, Pod) and isinstance(yard, Yard)
    _start_a_wide_post(world, "Camp dump, finally")
    _client(world).post(
        reverse("compose"),
        {
            "body": "Camp dump, finally",
            "pod_id": pod.id,
            "audience_yards": [yard.id],
            "confirm_wide": "yes",
        },
    )
    assert Post.objects.filter(body="Camp dump, finally").count() == 1
    feed = _client(world).get(reverse("feed")).content.decode()
    assert "Your unfinished post is still here." not in feed


def test_a_bounced_compose_still_carries_its_own_words_back(world: dict[str, object]) -> None:
    """The pre-existing behaviour, re-asserted: the draft restore must not displace what
    the member is actually looking at."""
    pod = world["pod"]
    assert isinstance(pod, Pod)
    page = (
        _client(world)
        .post(reverse("compose"), {"body": "x" * 6000, "pod_id": pod.id})
        .content.decode()
    )
    assert "a little long" in page
    assert "x" * 6000 in page


def test_the_held_draft_is_bounded_before_it_reaches_the_session(
    world: dict[str, object],
) -> None:
    """The branch that holds a draft most often is the ERROR branch, and "that post is a
    little long" is one of those errors — so the one input guaranteed to be over the cap
    was the one copied verbatim into a database-backed session row, re-read on every
    request for six hours and re-rendered into the textarea each time. staged_uploads
    bounds its bytes; this is the same posture for the words."""
    pod = world["pod"]
    assert isinstance(pod, Pod)
    _client(world).post(reverse("compose"), {"body": "x" * 200_000, "pod_id": pod.id})

    session = _client(world).session
    held = session["pending_draft"]["body"]
    assert len(held) == drafts.MAX_DRAFT_BODY
    # The member still sees everything they typed on the page they are looking at: the
    # error path carries the body straight to the template, not through the session.
    assert (
        "x" * 200_000
        in _client(world)
        .post(reverse("compose"), {"body": "x" * 200_000, "pod_id": pod.id})
        .content.decode()
    )


def test_the_restored_draft_brings_back_the_household_it_was_written_for(
    world: dict[str, object],
) -> None:
    """Restoring the words and silently re-defaulting the audience is the wrong half to
    keep. Without the pod, the select falls back to whatever the member can see FIRST, so
    a note composed for a few people is re-aimed at a bigger group while the page says
    "Your unfinished post is still here" — and pod choice is never confirmed, because TM-3
    keys on the side of the family, not the household."""
    yard, member = world["yard"], world["member"]
    assert isinstance(yard, Yard) and isinstance(member, Member)
    second = Pod.objects.create(name="The cousins", kind=Pod.HOUSEHOLD)
    second.yards.set([yard])
    PodMembership.objects.create(member=member, pod=second)

    _client(world).post(
        reverse("compose"),
        {"body": "Just for the cousins", "pod_id": second.id, "audience_yards": [yard.id]},
    )
    feed = _client(world).get(reverse("feed")).content.decode()
    assert f'<option value="{second.id}" selected>' in feed, "the draft came back re-aimed"

    # ...and a pod they have since left is not trusted back out of the session: the
    # composer opens on its ordinary default instead.
    PodMembership.objects.filter(member=member, pod=second).delete()
    feed = _client(world).get(reverse("feed")).content.decode()
    assert "selected" not in feed
    assert "Just for the cousins" in feed, "the words still come back"


def test_one_members_draft_is_never_another_members(world: dict[str, object]) -> None:
    """It lives in the session, so this is a property of where it is kept rather than of
    a check — which is exactly why it is worth pinning."""
    _start_a_wide_post(world, "Camp dump, finally")
    pod = world["pod"]
    assert isinstance(pod, Pod)
    other_user = User.objects.create_user(username="other", password=_PW)
    other = Member.objects.create(display_name="Otto Other", user=other_user)
    PodMembership.objects.create(member=other, pod=pod)
    other_client = Client()
    other_client.force_login(other_user, backend=_BACKEND)
    assert "Camp dump, finally" not in other_client.get(reverse("feed")).content.decode()
