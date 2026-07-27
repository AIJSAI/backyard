"""The feed ends at the real end (P1), and only says so when it is true.

The audit's finding: the feed was a hard `[:100]` slice with no pagination and no archive
route, under an *unconditional* "You are all caught up." A ~40-person family passes 100
posts in a few months, and from that moment the product quietly amputates its own history
and tells the member they have seen everything. That also breaks the archive promise the
whole S-803 upgrade guard exists to protect: the data survives every migration and is then
unreachable in the product.

The pre-existing feed test asserted only that the end-cap STRING was present, which passed
whether or not the claim was true. These assert the claim.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core.feed_views import _PAGE_SIZE
from core.models import Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_TEST_PW = "a-Strong-passphrase-9"
_CAUGHT_UP = "You are all caught up."


@pytest.fixture
def world() -> dict[str, object]:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Cousins")
    pod.yards.set([yard])
    user = User.objects.create_user(username="reader", password=_TEST_PW)
    member = Member.objects.create(display_name="Reader", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return {"pod": pod, "member": member, "client": client}


def _fill(pod: Pod, author: Member, count: int) -> None:
    Post.objects.bulk_create(
        [Post(author=author, pod=pod, body=f"post-{i:03d}") for i in range(count)]
    )


def test_a_short_feed_still_says_you_are_all_caught_up(world: dict[str, object]) -> None:
    """The end-cap is not removed — it is made conditional. A family under the page size
    genuinely has reached the end, and must still be told so."""
    client, pod, member = world["client"], world["pod"], world["member"]
    assert isinstance(client, Client) and isinstance(pod, Pod) and isinstance(member, Member)
    _fill(pod, member, 3)
    page = client.get(reverse("feed")).content.decode()
    assert _CAUGHT_UP in page
    assert "Show older posts" not in page


def test_a_long_feed_does_not_claim_the_member_has_seen_everything(
    world: dict[str, object],
) -> None:
    """The lie, gone. Past the page size the member is offered the archive instead."""
    client, pod, member = world["client"], world["pod"], world["member"]
    assert isinstance(client, Client) and isinstance(pod, Pod) and isinstance(member, Member)
    _fill(pod, member, _PAGE_SIZE + 25)
    page = client.get(reverse("feed")).content.decode()
    assert _CAUGHT_UP not in page, "the feed claimed the end while 25 posts were unreachable"
    assert "Show older posts" in page


def test_the_oldest_post_is_actually_reachable_by_paging(world: dict[str, object]) -> None:
    """The whole point: walk the cursor to the end and find post-000.

    Before this there was no route to it at all — `grep -n 'paginat|page'` over the view
    returned nothing and urls.py had no archive view, so the only handle on an old post
    was a permalink nobody kept.
    """
    client, pod, member = world["client"], world["pod"], world["member"]
    assert isinstance(client, Client) and isinstance(pod, Pod) and isinstance(member, Member)
    total = _PAGE_SIZE * 2 + 10
    _fill(pod, member, total)

    seen: set[str] = set()
    url = reverse("feed")
    for _ in range(10):  # generous bound; the walk must terminate well inside it
        page = client.get(url).content.decode()
        seen.update(f"post-{i:03d}" for i in range(total) if f"post-{i:03d}" in page)
        if "Show older posts" not in page:
            break
        cursor = page.split("?before=")[1].split('"')[0]
        url = f"{reverse('feed')}?before={cursor}"
    else:  # pragma: no cover - only on a non-terminating cursor
        pytest.fail("paging never reached the end of the feed")

    assert "post-000" in seen, "the oldest post is still unreachable"
    assert len(seen) == total, f"paging lost posts: saw {len(seen)} of {total}"
    assert _CAUGHT_UP in page  # the last page is genuinely the end, and says so


def test_paging_into_the_archive_does_not_mark_the_new_posts_as_read(
    world: dict[str, object],
) -> None:
    """Reading history is not "opening the feed". If a cursor request advanced the unread
    boundary, going back to look at Grandpa's birthday post would silently mark everything
    new above it as seen (S-303)."""
    client, pod, member = world["client"], world["pod"], world["member"]
    assert isinstance(client, Client) and isinstance(pod, Pod) and isinstance(member, Member)
    _fill(pod, member, _PAGE_SIZE + 5)
    page = client.get(reverse("feed")).content.decode()  # this one DOES advance it
    boundary = Member.objects.get(pk=member.pk).feed_last_seen_at
    assert boundary is not None

    cursor = page.split("?before=")[1].split('"')[0]
    client.get(f"{reverse('feed')}?before={cursor}")
    assert Member.objects.get(pk=member.pk).feed_last_seen_at == boundary


def test_a_forged_or_mangled_cursor_reveals_nothing_and_does_not_error(
    world: dict[str, object],
) -> None:
    """The cursor names a position in time, never an audience. A garbage or hostile value
    falls back to page one; it can never widen what the member sees."""
    client, pod, member = world["client"], world["pod"], world["member"]
    assert isinstance(client, Client) and isinstance(pod, Pod) and isinstance(member, Member)
    _fill(pod, member, 3)

    # A post in a yard this member is not in must stay invisible on every cursor.
    other_yard = Yard.objects.create(name="Paternal", slug="paternal")
    other_pod = Pod.objects.create(name="Far cousins")
    other_pod.yards.set([other_yard])
    stranger = Member.objects.create(display_name="Stranger")
    PodMembership.objects.create(member=stranger, pod=other_pod)
    hidden = Post.objects.create(author=stranger, pod=other_pod, body="not-for-you")

    for raw in ("", "garbage", "not-a-date_5", "2026-01-01T00:00:00+00:00_notanint", "_"):
        response = client.get(reverse("feed"), {"before": raw})
        assert response.status_code == 200, raw
        assert hidden.body not in response.content.decode(), raw
