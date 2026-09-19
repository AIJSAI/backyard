"""The systemic fixes the design walk asked for, asserted where they live.

These are the small structural rules that lift every screen at once, and every one of
them is the kind of thing that silently regresses in a later pass because nothing in the
suite knows it was a decision:

  C2   the error component that actually ships (`ul.errorlist`) is styled at all.
  C6   a destructive action leaves the primary row — three identical bold green links 36px
       apart meant a thumb aiming at "Open Post" could land on "Delete".
  C7   the 44px floor reaches the controls that were missing it, including the audience
       checkbox, which is the smallest target on the most consequential control in a
       privacy-first product.
  C10  banners and empty states share the card edge instead of being capped at the reading
       measure, and an empty state is never a dashed box inside a solid one.
  F9   "You are all caught up." is a claim about the top of the feed, so it does not
       appear at the bottom of an archive page.
  D9   the composer's primary is left-aligned like every other primary, and the composer
       opens small instead of standing 560px tall between a member and their family's
       first photograph.
"""

from __future__ import annotations

import pathlib
import re
from urllib.parse import quote

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core import posting
from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_PW = "a-Strong-passphrase-9"
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_BASE = pathlib.Path(__file__).resolve().parents[1] / "templates" / "core" / "base.html"


def _style() -> str:
    return _BASE.read_text()


@pytest.fixture
def world() -> dict[str, object]:
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="Nana's house", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = User.objects.create_user(username="reader", password=_PW)
    member = Member.objects.create(display_name="Ann Reader", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return {"client": client, "pod": pod, "member": member}


def _page(world: dict[str, object], url: str) -> str:
    client = world["client"]
    assert isinstance(client, Client)
    return client.get(url).content.decode()


# --- C2: the error component that ships ------------------------------------------


def test_the_shipped_error_list_is_styled(world: dict[str, object]) -> None:
    """`.errors` was the app's own component; `ul.errorlist` is what django-allauth and
    every Django form emit, and it had no rule anywhere — so the commonest failure in the
    product, a mistyped password, rendered as a browser-default bullet indented 40px and
    read as a page that had failed to load its stylesheet."""
    css = _style()
    assert "ul.errorlist" in css
    rule = re.search(r"ul\.errorlist, ul\.errorlist\.nonfield \{([^}]*)\}", css)
    assert rule, "the allauth non-field variant must be covered too"
    body = rule.group(1)
    assert "list-style: none" in body, "still a UA bullet"
    assert "var(--danger-tint)" in body and "var(--radius-sm)" in body


def test_a_real_sign_in_failure_renders_inside_it() -> None:
    """Asserted on the page, not on the stylesheet: the rule is worthless if the markup
    allauth emits does not actually carry that class."""
    User.objects.create_user(username="nana", password=_PW)
    page = Client().post(
        reverse("account_login"), {"login": "nana", "password": "wrong-on-purpose"}
    )
    assert "errorlist" in page.content.decode()


# --- C6: destructive actions leave the primary row --------------------------------


def test_delete_is_not_a_peer_of_open_post(world: dict[str, object]) -> None:
    pod, member = world["pod"], world["member"]
    assert isinstance(pod, Pod) and isinstance(member, Member)
    post = posting.create_post(author=member, pod=pod, audience_yards=[], body="mine")
    page = _page(world, reverse("feed"))

    assert f'<a class="destructive" href="{reverse("delete_post", args=[post.id])}"' in page
    assert f'<a href="{reverse("post_detail", args=[post.id])}">Open Post</a>' in page
    css = _style()
    assert ".actions .destructive, .actions form.takedown { margin-left: auto; }" in css
    assert ".actions a.destructive { color: var(--danger); font-weight: 400; }" in css


# --- C7: tap targets --------------------------------------------------------------


def test_the_audience_checkbox_clears_the_target_floor() -> None:
    """Measured on the phone pass at 19x19px inside a 26px-tall label: the control that
    decides who sees a photograph was the smallest thing on the screen."""
    rule = re.search(r"label\.inline-check \{([^}]*)\}", _style())
    assert rule and "min-height: 44px" in rule.group(1)
    box = re.search(
        r"label\.inline-check input\[type=checkbox\], label\.inline-check input\[type=radio\] \{"
        r"([^}]*)\}",
        _style(),
    )
    assert box and "width: 24px" in box.group(1) and "height: 24px" in box.group(1)


def test_the_header_nav_links_clear_it_too() -> None:
    """They were 39px tall, so the affordance on every page in the product was the one
    the floor missed."""
    rule = re.search(r"header\.site nav\.site-nav a \{([^}]*)\}", _style())
    assert rule and "min-height: 44px" in rule.group(1)


# --- C10: one shell edge, one empty state -----------------------------------------


def test_banners_and_empty_states_share_the_card_edge() -> None:
    css = _style()
    assert "main.wrap > p, main.wrap > h1 + p, .post > p { max-width: 34rem; }" in css
    assert (
        "aside.orientation, aside.prompt, aside.date-banner, .notice, .empty "
        "{ max-width: none; }" in css
    )


def test_the_empty_state_is_solid_and_never_nested(world: dict[str, object]) -> None:
    rule = re.search(r"\n\.empty \{([^}]*)\}", _style())
    assert rule and "dashed" not in rule.group(1), "the only dashed edge in the product"
    # And a list whose only child is the empty state stops drawing its own frame.
    assert "ul.comments:has(> li.empty:only-child)" in _style()
    pod, member = world["pod"], world["member"]
    assert isinstance(pod, Pod) and isinstance(member, Member)
    post = posting.create_post(author=member, pod=pod, audience_yards=[], body="no replies yet")
    assert 'class="empty"' in _page(world, reverse("post_detail", args=[post.id]))


# --- D9/D20: the composer, and the archive page -----------------------------------


def test_the_composer_primary_is_left_aligned_and_unruled() -> None:
    """The one right-aligned primary in the product, under a horizontal rule that put a
    ruled form footer on a page of family photographs."""
    rule = re.search(r"\.composer-submit \{([^}]*)\}", _style())
    assert rule
    assert "justify-content: flex-start" in rule.group(1)
    assert "border-top" not in rule.group(1)


def test_the_composer_opens_small(world: dict[str, object]) -> None:
    """Everything but the box you type in and the button that posts it waits until the
    composer is in use. Pure CSS, so a browser without :has() renders it open — which is
    exactly the old behaviour, never a broken one."""
    css = _style()
    assert (
        ".composer:not(.is-open):not(:focus-within):has(textarea:placeholder-shown) "
        ".composer-extras" in css
    )
    page = _page(world, reverse("feed"))
    assert 'class="composer-extras"' in page
    # The selector above keys on :placeholder-shown, which matches nothing when the
    # textarea has no placeholder attribute. Assert the DOM the rule needs, not the rule:
    # a copy edit removed the placeholder once and this test stayed green.
    assert re.search(r'<textarea[^>]*id="compose-body"[^>]*placeholder="[^"]', page), (
        "the compose textarea has no placeholder, so the collapse selector never matches"
    )
    # The textarea and the primary are NEVER inside the collapsing region: a member must
    # always be able to see, and tab to, the thing that posts.
    extras = page.split('class="composer-extras"')[1]
    assert "<textarea" not in extras.split("</form>")[0]
    assert '<div class="composer-submit">' not in extras.split("</div>")[0]


def test_an_archive_page_is_its_own_page(world: dict[str, object]) -> None:
    """Paging back kept the title "Your Backyard", the orientation card, the whole
    composer, and ended on "You are all caught up" — a history page claiming to be the
    current feed and then claiming the reader had seen everything."""
    pod, member = world["pod"], world["member"]
    assert isinstance(pod, Pod) and isinstance(member, Member)
    for i in range(3):
        posting.create_post(author=member, pod=pod, audience_yards=[], body=f"post {i}")
    newest = posting.create_post(author=member, pod=pod, audience_yards=[], body="newest")
    # quote(), because an ISO timestamp ends in "+00:00" and a bare + in a query string
    # decodes to a space — which the cursor parser correctly rejects, landing the request
    # back on page one and making this test pass against the wrong page.
    cursor = quote(f"{newest.created_at.isoformat()}_{newest.id}")

    page = _page(world, f"{reverse('feed')}?before={cursor}")
    assert "post 0" in page, "the cursor did not page: this is still the current feed"
    assert "<h1>Older Posts</h1>" in page
    assert "You are all caught up." not in page
    assert "Nothing older than this." in page
    assert 'class="composer"' not in page, "a history page is for reading"
    assert "Back To The Newest Posts" in page
