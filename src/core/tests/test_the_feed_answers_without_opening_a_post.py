"""A relative can see that somebody answered, and answer back, from the feed itself.

The owner held this beside Facebook and Instagram at phone width on 2026-09-20: a post
was a bordered card with photographs inset inside it, and the only things under it were
a link to the thread and a red Delete. Nothing on the feed said that anybody had reacted
or replied, so a photograph looked unanswered to the person who shared it, and saying
one word back meant opening a page first.

What is asserted here:

  * the reactor line names who reacted, capped at three with the rest one tap away, and
    is absent entirely when nobody has;
  * both the line and the reply count are scoped to what THIS viewer may see, through
    the same guards the thread page uses (a bridging post must not name the other side);
  * a Love sent from the feed toggles like the thread page's buttons do and lands the
    member back on their own post — on the archive page they were reading, never at the
    top of the feed;
  * the return path is request data, so it is used only when it is a local path;
  * and the whole page costs a bounded number of queries: twenty posts must not cost
    twenty round trips for reactions and twenty more for reply counts.
"""

from __future__ import annotations

from urllib.parse import quote

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.models import Comment, Member, Pod, PodMembership, Post, Reaction, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _member(pod: Pod, name: str, *, login: bool = True) -> Member:
    user = User.objects.create_user(username=name.lower().replace(" ", "")) if login else None
    member = Member.objects.create(display_name=name, user=user)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _client_for(member: Member) -> Client:
    assert member.user is not None
    client = Client()
    client.force_login(member.user, backend=_BACKEND)
    return client


@pytest.fixture
def household() -> dict[str, object]:
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="Nana's house", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    author = _member(pod, "Ann Reader")
    return {
        "yard": yard,
        "pod": pod,
        "author": author,
        "client": _client_for(author),
        "sam": _member(pod, "Sam Reed"),
        "dave": _member(pod, "Dave Reed"),
        "jo": _member(pod, "Jo Reed"),
        "kit": _member(pod, "Kit Reed"),
    }


def _post(household: dict[str, object], body: str = "a photo of the lake") -> Post:
    pod, author = household["pod"], household["author"]
    assert isinstance(pod, Pod) and isinstance(author, Member)
    return Post.objects.create(author=author, pod=pod, body=body)


def _feed(household: dict[str, object], url: str | None = None) -> str:
    client = household["client"]
    assert isinstance(client, Client)
    return client.get(url or reverse("feed")).content.decode()


def _item(page: str, post: Post) -> str:
    """The one list item, from its own id to the end of the item."""
    item = page[page.index(f'id="post-{post.id}"') :]
    return item[: item.index("</li>")]


# --- who reacted, on the feed ----------------------------------------------------------


def test_the_feed_names_who_reacted(household: dict[str, object]) -> None:
    post = _post(household)
    Reaction.objects.create(member=household["sam"], post=post, kind=Reaction.HEART)
    Reaction.objects.create(member=household["dave"], post=post, kind=Reaction.HEART)

    item = _item(_feed(household), post)
    assert "Love:" in item
    assert "Sam Reed, Dave Reed" in item


def test_a_post_nobody_reacted_to_says_nothing(household: dict[str, object]) -> None:
    """No line at all, not an empty one: `hidden` keeps it out of the page a screen
    reader walks as well as off the screen."""
    post = _post(household)
    item = _item(_feed(household), post)
    assert "Love:" not in item
    assert 'data-reaction-line hidden' in item


def test_a_long_reactor_list_stops_at_three_names(household: dict[str, object]) -> None:
    """Three names and a way to the rest. Never "and 2 others" with a number in it: the
    product's one rule about reactions is that they are people, not a score (S-304)."""
    post = _post(household)
    for who in ("sam", "dave", "jo", "kit"):
        Reaction.objects.create(member=household[who], post=post, kind=Reaction.HEART)

    item = _item(_feed(household), post)
    assert "Sam Reed, Dave Reed, Jo Reed" in item
    assert "Kit Reed" not in item
    assert f'<a href="{reverse("post_detail", args=[post.id])}">And Others</a>' in item
    for tally in ("and 1 other", "and 2 others", "4 people", "4 reactions"):
        assert tally not in item.lower()


# --- the reply count -------------------------------------------------------------------


def test_the_reply_count_is_a_link_and_is_absent_at_zero(household: dict[str, object]) -> None:
    post = _post(household)
    assert "Reply</a>" in _item(_feed(household), post)  # the way to answer is always there
    assert "1 Reply" not in _item(_feed(household), post)

    Comment.objects.create(post=post, author=household["sam"], body="lovely")
    assert "1 Reply</a>" in _item(_feed(household), post)
    Comment.objects.create(post=post, author=household["dave"], body="that view")
    assert "2 Replies</a>" in _item(_feed(household), post)


def test_a_deleted_reply_stops_being_counted(household: dict[str, object]) -> None:
    """The count runs through `visible_comments`, so a soft-deleted reply leaves it for
    free rather than needing a rule of its own."""
    post = _post(household)
    reply = Comment.objects.create(post=post, author=household["sam"], body="lovely")
    Comment.objects.filter(pk=reply.pk).update(deleted_at="2026-09-20T12:00:00+00:00")
    assert "1 Reply" not in _item(_feed(household), post)


# --- the yard boundary holds on both of them -------------------------------------------


@pytest.fixture
def bridged() -> dict[str, object]:
    """The case where scoping gets interesting: a household in BOTH sides posts to both,
    so each side can see the post while neither may learn the other side exists."""
    moms = Yard.objects.create(name="Mom's side", slug="moms-side")
    dads = Yard.objects.create(name="Dad's side", slug="dads-side")
    bridge = Pod.objects.create(name="Our house", kind=Pod.HOUSEHOLD)
    bridge.yards.set([moms, dads])
    m_pod = Pod.objects.create(name="Nana's house", kind=Pod.HOUSEHOLD)
    m_pod.yards.set([moms])
    p_pod = Pod.objects.create(name="The Ferraras", kind=Pod.HOUSEHOLD)
    p_pod.yards.set([dads])
    bridging = _member(bridge, "Priya Bridge")
    post = Post.objects.create(author=bridging, pod=bridge, body="both sides see this")
    post.audience_yards.set([moms, dads])
    return {
        "post": post,
        "maternal": _member(m_pod, "Mo Maternal"),
        "paternal": _member(p_pod, "Pa Paternal"),
    }


def test_the_reactor_line_never_crosses_the_yard_boundary(bridged: dict[str, object]) -> None:
    post, maternal, paternal = bridged["post"], bridged["maternal"], bridged["paternal"]
    assert isinstance(post, Post) and isinstance(maternal, Member) and isinstance(paternal, Member)
    Reaction.objects.create(member=paternal, post=post, kind=Reaction.HEART)

    page = _client_for(maternal).get(reverse("feed")).content.decode()
    assert "both sides see this" in page, "the post itself is visible to both sides"
    assert "Pa Paternal" not in page, (
        "the feed's reactor line names somebody the viewer cannot otherwise know exists"
    )


def test_the_reply_count_counts_only_replies_this_viewer_may_read(
    bridged: dict[str, object],
) -> None:
    """A number is a fact about the far side too. Counting a reply the viewer cannot
    read would report that those people are there."""
    post, maternal, paternal = bridged["post"], bridged["maternal"], bridged["paternal"]
    assert isinstance(post, Post) and isinstance(maternal, Member) and isinstance(paternal, Member)
    Comment.objects.create(post=post, author=paternal, body="from the other side")

    page = _client_for(maternal).get(reverse("feed")).content.decode()
    assert "1 Reply" not in page


# --- Love, from the feed ---------------------------------------------------------------


def _love(household: dict[str, object], post: Post, **extra: str) -> object:
    client = household["client"]
    assert isinstance(client, Client)
    return client.post(reverse("react", args=[post.id]), {"kind": "heart", **extra})


def test_love_from_the_feed_toggles_and_comes_back_to_the_post(
    household: dict[str, object],
) -> None:
    post = _post(household)
    response = _love(household, post, next=reverse("feed"))
    assert response.status_code == 302
    assert response["Location"] == f"{reverse('feed')}#post-{post.id}"
    assert Reaction.objects.get(member=household["author"], post=post).kind == Reaction.HEART

    # ...and the button says so, which is what the member looks at when they land.
    item = _item(_feed(household), post)
    assert 'aria-pressed="true"' in item

    # Pressing it again removes it, exactly as the thread page's buttons behave.
    _love(household, post, next=reverse("feed"))
    assert not Reaction.objects.filter(member=household["author"], post=post).exists()
    assert 'aria-pressed="false"' in _item(_feed(household), post)


def test_loving_an_older_post_keeps_the_archive_page(household: dict[str, object]) -> None:
    """The cursor survives the round trip. Without it, reacting to something from last
    spring answered by throwing the reader back to this morning."""
    pod, author = household["pod"], household["author"]
    assert isinstance(pod, Pod) and isinstance(author, Member)
    older = _post(household, "from last spring")
    newest = Post.objects.create(author=author, pod=pod, body="this morning")
    cursor = quote(f"{newest.created_at.isoformat()}_{newest.id}")
    archive = f"{reverse('feed')}?before={cursor}"

    # The page hands its own cursor to every Love button on it.
    assert f'name="next" value="{archive}"' in _feed(household, archive)

    response = _love(household, older, next=archive)
    assert response["Location"] == f"{archive}#post-{older.id}"


def test_a_return_path_that_is_not_local_is_refused(household: dict[str, object]) -> None:
    """The return path arrives in a POST from a browser, so it is request data. Anything
    that is not a path on this site sends the member to the post instead (never an open
    redirect), and the reaction itself still happens."""
    post = _post(household)
    for hostile in (
        "https://example.invalid/",
        "//example.invalid/",
        "/\\example.invalid/",
        "http:/example.invalid",
        "javascript:alert(1)",  # noqa: S106  # not a credential; a refused scheme
        "example.invalid",
    ):
        Reaction.objects.filter(post=post).delete()
        response = _love(household, post, next=hostile)
        assert response["Location"] == reverse("post_detail", args=[post.id]), hostile
        assert Reaction.objects.filter(post=post).exists(), f"{hostile} lost the reaction"


def test_the_enhanced_path_answers_with_the_same_scoped_names(
    bridged: dict[str, object],
) -> None:
    """The script's answer is the rendered line's answer: same grouping, same cap, same
    guard. A JSON route that assembled its own list would be the second audience rule
    this codebase exists to not have."""
    post, maternal, paternal = bridged["post"], bridged["maternal"], bridged["paternal"]
    assert isinstance(post, Post) and isinstance(maternal, Member) and isinstance(paternal, Member)
    Reaction.objects.create(member=paternal, post=post, kind=Reaction.HEART)

    response = _client_for(maternal).post(
        reverse("react", args=[post.id]),
        {"kind": "heart"},
        headers={"x-requested-with": "XMLHttpRequest"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mine"] == "heart"
    names = [name for group in payload["groups"] for name in group["names"]]
    assert names == ["Mo Maternal"], "the far side's reactor reached the enhanced path"
    assert payload["post_url"] == reverse("post_detail", args=[post.id])


# --- the page's cost does not grow with the family's history ---------------------------


def test_reactions_and_reply_counts_cost_the_same_at_any_length(
    household: dict[str, object],
) -> None:
    """The whole point of loading them per PAGE.

    Measured on this fixture rather than reasoned: the feed rendered in 19 queries before
    the reactor line and the reply count existed and renders in 23 with them, at two
    posts and at twenty alike. The four are: the reactors for every post on the page and
    the reply counts for every post on the page, each preceded by the viewer's own
    yard-id lookup, which `scoping.visible_members` resolves eagerly inside both guards.
    All four are per PAGE.

    Both halves are asserted. The growth is the property worth guarding — eighteen more
    posts must buy nothing — and the total is a ceiling rather than an equality, because
    an unrelated change (a session probe, another middleware read) moves it and should
    make somebody re-measure rather than silently pass.
    """
    pod, author = household["pod"], household["author"]
    assert isinstance(pod, Pod) and isinstance(author, Member)
    client = household["client"]
    assert isinstance(client, Client)

    def fill(count: int) -> None:
        for index in range(count):
            post = Post.objects.create(author=author, pod=pod, body=f"post {index}")
            Reaction.objects.create(member=household["sam"], post=post, kind=Reaction.HEART)
            Comment.objects.create(post=post, author=household["dave"], body="a reply")

    fill(2)
    with CaptureQueriesContext(connection) as small:
        client.get(reverse("feed"))
    fill(18)
    with CaptureQueriesContext(connection) as large:
        client.get(reverse("feed"))

    assert len(large) == len(small), (
        f"18 more posts cost {len(large) - len(small)} more queries: something on the "
        "feed is asking per post again"
    )
    assert len(large) <= 23, f"the feed now renders in {len(large)} queries, up from 23"
