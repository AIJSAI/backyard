"""A post keeps the shape it was typed in, on every surface that renders one (C3/F3/F4).

The walk posted a four-line recipe with a blank line and a URL in it. It rendered as
"Grandma's pie, from her card: 2 cups flour 1 cup butter See the recipe at
https://example.com/pie" — one run-on sentence, the address inert. A recipe, a packing
list, an address or a poem is destroyed on the way to the people it was written for, and
nothing in the product ever said so.

Two properties, and the second is the one that makes the first safe:

  SHAPE     every body renders inside `.post-body` (white-space: pre-wrap), and the
            surfaces that may carry links run it through `|urlize`.
  ESCAPING  `urlize` autoescapes. A post containing a script tag must still arrive as
            text, and a URL crafted to break out of the href attribute it is about to be
            put inside must not do so. Both are asserted against a real rendered page
            rather than against the filter, because the filter is not what ships.

The elder surface is deliberately excluded from the urlize half: S-601 gives that page no
way off itself (every href on it is the elder feed), so turning a member-typed URL into a
tappable link is the one change that could strand a grandmother on a stranger's website.
It keeps the line breaks and nothing else — asserted below, so a future "consistency" pass
cannot quietly add the links back.
"""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core import commenting, elder_tokens, posting
from core.models import Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_PW = "a-Strong-passphrase-9"
_BACKEND = "django.contrib.auth.backends.ModelBackend"

_RECIPE = (
    "Grandma's pie, from her card:\n\n2 cups flour\n1 cup butter\n\nSee https://example.com/pie"
)
# A script tag, and a URL whose tail is crafted to close the href it is about to be put
# inside and add an event handler. Both are member-typed text and must arrive as text.
_HOSTILE = (
    '<script>alert("pie")</script>\n'
    'https://example.com/a"onmouseover="alert(1)\n'
    "https://example.com/b'onmouseover='alert(2)"
)


@pytest.fixture
def world() -> dict[str, object]:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Cousins")
    pod.yards.set([yard])
    user = User.objects.create_user(username="reader", password=_PW)
    member = Member.objects.create(display_name="Ann Reader", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    nana = Member.objects.create(display_name="Nana Ann", kinship_name="Nana")
    PodMembership.objects.create(member=nana, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return {"client": client, "pod": pod, "member": member, "nana": nana}


def _post(world: dict[str, object], body: str) -> Post:
    pod, member = world["pod"], world["member"]
    assert isinstance(pod, Pod) and isinstance(member, Member)
    return posting.create_post(author=member, pod=pod, audience_yards=[], body=body)


def _page(world: dict[str, object], url: str) -> str:
    client = world["client"]
    assert isinstance(client, Client)
    return client.get(url).content.decode()


def test_the_feed_keeps_line_breaks_and_makes_a_link_tappable(world: dict[str, object]) -> None:
    _post(world, _RECIPE)
    page = _page(world, reverse("feed"))
    assert 'class="post-body"' in page, "the body needs the pre-wrap component"
    assert "2 cups flour\n1 cup butter" in page, "the newlines the member typed are gone"
    assert 'href="https://example.com/pie"' in page, "the URL they typed is inert"


def test_a_thread_keeps_the_shape_of_the_post_and_of_every_reply(
    world: dict[str, object],
) -> None:
    post = _post(world, _RECIPE)
    nana = world["nana"]
    assert isinstance(nana, Member)
    commenting.create_comment(
        author=nana, post=post, body="Two lines\nnot one: https://example.com/r"
    )

    page = _page(world, reverse("post_detail", args=[post.id]))
    assert "2 cups flour\n1 cup butter" in page
    assert 'href="https://example.com/pie"' in page
    assert "Two lines\nnot one" in page, "a reply is somebody's words too"
    assert 'href="https://example.com/r"' in page


def test_the_elder_page_keeps_the_breaks_and_deliberately_not_the_links(
    world: dict[str, object],
) -> None:
    """S-601: no way off this surface. The shape survives; the link stays text."""
    _post(world, _RECIPE)
    nana = world["nana"]
    assert isinstance(nana, Member)
    client = Client()
    client.get(reverse("elder_enter", args=[elder_tokens.mint(nana)]))
    page = client.get(reverse("elder_feed")).content.decode()

    assert "2 cups flour\n1 cup butter" in page
    assert "https://example.com/pie" in page, "she must still be able to read the address"
    assert 'href="https://example.com/pie"' not in page, "S-601: nothing leaves this page"


def test_the_emailed_web_view_keeps_the_shape(world: dict[str, object]) -> None:
    """The /d/ web view renders the same bodies for a recipient with no session."""
    import datetime

    from core import digest_links
    from core.models import DigestIssue

    post = _post(world, _RECIPE)
    pod, member = world["pod"], world["member"]
    assert isinstance(pod, Pod) and isinstance(member, Member)
    yard = pod.yards.first()
    assert yard is not None
    issue = DigestIssue.objects.create(
        member=member,
        yard=yard,
        window_start=post.created_at - datetime.timedelta(days=1),
        window_end=post.created_at + datetime.timedelta(days=1),
    )
    raw = digest_links.mint(issue)
    page = Client().get(reverse("digest_web", args=[raw])).content.decode()
    assert 'class="post-body"' in page
    assert "2 cups flour\n1 cup butter" in page


@pytest.mark.parametrize(
    "surface",
    ["feed", "post_detail", "elder_feed"],
)
def test_autoescaping_holds_on_every_surface(world: dict[str, object], surface: str) -> None:
    """The whole point of pairing pre-wrap with urlize is that neither weakens escaping.

    A raw `<script>` would execute; a raw `"` inside the generated href would end the
    attribute and let the rest of the member's text become one. Both are asserted on the
    RENDERED page, because the filter is not what ships — the template is.
    """
    post = _post(world, _HOSTILE)
    if surface == "feed":
        page = _page(world, reverse("feed"))
    elif surface == "post_detail":
        page = _page(world, reverse("post_detail", args=[post.id]))
    else:
        nana = world["nana"]
        assert isinstance(nana, Member)
        client = Client()
        client.get(reverse("elder_enter", args=[elder_tokens.mint(nana)]))
        page = client.get(reverse("elder_feed")).content.decode()

    assert "<script>alert" not in page, "a member-typed script tag reached the page as markup"
    assert "&lt;script&gt;" in page, "...and it must be there, as text"
    # Inside a TAG is the only place an event handler does anything, so that is where this
    # looks. Asserting the bare substring would be satisfied by the correctly-escaped text
    # the page is supposed to show — which is the failure mode of a guard like this.
    assert not re.search(r"<[^>]*\bonmouseover\b[^>]*>", page), (
        "a crafted URL broke out of its own href attribute"
    )
    # Non-vacuity, both halves: the hostile body really did render on this surface, and
    # the quote that would have closed the attribute really is escaped rather than gone.
    assert "alert(1)" in page or "alert(2)" in page
    assert "&quot;onmouseover=&quot;" in page or "&#x27;onmouseover=&#x27;" in page


def test_autoescaping_holds_on_the_credential_free_digest_page(world: dict[str, object]) -> None:
    """The /d/ page is the lowest-trust surface in the product — no login, the credential in
    the URL, opened from an email by whoever has the link — and it is the one this PR made
    carry clickable member-typed links. It gets the same assertion the logged-in surfaces
    get, which the parametrize above did not reach.
    """
    import datetime

    from core import digest_links
    from core.models import DigestIssue

    post = _post(world, _HOSTILE)
    pod, member = world["pod"], world["member"]
    assert isinstance(pod, Pod) and isinstance(member, Member)
    yard = pod.yards.first()
    assert yard is not None
    issue = DigestIssue.objects.create(
        member=member,
        yard=yard,
        window_start=post.created_at - datetime.timedelta(days=1),
        window_end=post.created_at + datetime.timedelta(days=1),
    )
    page = Client().get(reverse("digest_web", args=[digest_links.mint(issue)])).content.decode()
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page
    assert not re.search(r"<[^>]*\bonmouseover\b[^>]*>", page)
    assert "alert(1)" in page or "alert(2)" in page


def test_the_emailed_digest_keeps_the_breaks_and_deliberately_not_the_links() -> None:
    """The same rule as the elder page, for the same reason one step further out: a link in
    an email body is the surface with the least context around it and the most forwarding,
    the family's mail client will linkify a bare address itself if it wants to, and
    test_digest asserts every href we emit in that email is on this instance's own origin.

    Asserted on the TEMPLATE SOURCE because the rule is about what we emit, not about what
    renders — the exclusion was true but rested on nobody editing the line in a later
    "consistency" pass.
    """
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parents[1] / "templates" / "core" / "email" / "digest.html"
    ).read_text()
    assert "block.body }}" in source, "the emailed body moved; re-point this assertion"
    assert "urlize" not in source, "the emailed digest must stay link-free"
    assert "white-space: pre-wrap" in source, "...but it must still keep the line breaks"
