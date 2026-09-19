"""There is a person behind every name (the design walk's verdict, point 3).

"The single biggest thing holding it back as DESIGN: it has no human presence. There is
not one face, avatar or photo of a person anywhere in the chrome — the directory is a list
of green underlined links, profiles are three lines on a blank page — so a product whose
entire purpose is family warmth reads as a database with photographs attached."

The cure is an initials disc, not a photo-upload feature: no new model field, no new
storage, nothing for a family to maintain. What has to hold:

  EVERYWHERE  a name that leads a post, a reply, a directory row or a profile leads it
              beside the disc.
  STABLE      the same relative is the same colour on every surface and across processes,
              or the directory stops being scannable at a glance.
  CONTRAST    the tone is an INDEX into a token pair, and test_design_system_wcag proves
              both members of every pair clear AA in both themes.
  QUIET       the disc is decorative markup beside the name it stands for, so a screen
              reader does not read every byline in the product twice.

The other half of "a person behind the name" is the profile page, which was a dead end:
three lines and a link that downloaded an empty contact card.
"""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core import commenting, posting
from core.models import Member, Pod, PodMembership, Yard
from core.templatetags.avatars import TONE_COUNT, initials, tone_for

pytestmark = pytest.mark.django_db
User = get_user_model()
_PW = "a-Strong-passphrase-9"
_BACKEND = "django.contrib.auth.backends.ModelBackend"


@pytest.fixture
def world() -> dict[str, object]:
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    house = Pod.objects.create(name="Nana's house", kind=Pod.HOUSEHOLD)
    house.yards.set([yard])
    user = User.objects.create_user(username="reader", password=_PW)
    viewer = Member.objects.create(display_name="Ann Reader", user=user)
    PodMembership.objects.create(member=viewer, pod=house)
    rose = Member.objects.create(display_name="Rose Whitfield", kinship_name="Nana")
    PodMembership.objects.create(member=rose, pod=house)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return {"client": client, "pod": house, "viewer": viewer, "rose": rose, "yard": yard}


def _page(world: dict[str, object], url: str) -> str:
    client = world["client"]
    assert isinstance(client, Client)
    return client.get(url).content.decode()


# --- the tag ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Rose Whitfield", "RW"),
        ("Rose Mary Whitfield", "RW"),  # first and last, the way a family reads a name
        ("Rose", "R"),  # one letter, not "RO", which reads as a truncation
        ("  rose  ", "R"),
        ("", "•"),  # never an empty circle
        ("\U0001f600", "\U0001f600"),  # a name with no cased letters still gets a mark
    ],
)
def test_initials_read_as_a_monogram(name: str, expected: str) -> None:
    assert initials(name) == expected


def test_a_tone_is_stable_across_processes() -> None:
    """Not `hash()`: Python salts str hashing per process, so two gunicorn workers would
    serve the same relative in two different colours within one page load."""
    assert tone_for(7) == tone_for("7") == tone_for(7)
    assert all(1 <= tone_for(i) <= TONE_COUNT for i in range(200))
    # Non-vacuous: it really does spread, rather than answering 1 for everything.
    assert len({tone_for(i) for i in range(TONE_COUNT)}) == TONE_COUNT


# --- the surfaces ----------------------------------------------------------------


def _avatars(page: str) -> list[str]:
    return re.findall(r'<span class="avatar[^"]*" data-tone="(\d)" aria-hidden="true">', page)


def test_every_surface_where_a_name_leads_something_shows_the_person(
    world: dict[str, object],
) -> None:
    pod, rose, viewer = world["pod"], world["rose"], world["viewer"]
    assert isinstance(pod, Pod) and isinstance(rose, Member) and isinstance(viewer, Member)
    post = posting.create_post(author=rose, pod=pod, audience_yards=[], body="What a catch!")
    commenting.create_comment(author=viewer, post=post, body="Look at that")

    for url in (
        reverse("feed"),
        reverse("post_detail", args=[post.id]),
        reverse("directory"),
        reverse("member_profile", args=[rose.id]),
    ):
        page = _page(world, url)
        assert _avatars(page), f"no human presence on {url}"


def test_one_relative_is_one_colour_everywhere(world: dict[str, object]) -> None:
    pod, rose = world["pod"], world["rose"]
    assert isinstance(pod, Pod) and isinstance(rose, Member)
    post = posting.create_post(author=rose, pod=pod, audience_yards=[], body="What a catch!")
    expected = str(tone_for(rose.id))

    assert _avatars(_page(world, reverse("post_detail", args=[post.id])))[0] == expected
    assert expected in _avatars(_page(world, reverse("feed")))
    assert _avatars(_page(world, reverse("member_profile", args=[rose.id])))[0] == expected


def test_the_disc_is_decorative_beside_the_name_it_stands_for(world: dict[str, object]) -> None:
    """The name is always rendered as text right beside it, so announcing the monogram
    too would read every byline in the product twice."""
    rose = world["rose"]
    assert isinstance(rose, Member)
    page = _page(world, reverse("member_profile", args=[rose.id]))
    assert f">{initials('Rose Whitfield')}</span>" in page
    assert 'aria-hidden="true">RW</span>' in page
    assert "Rose Whitfield" in page


# --- the profile is no longer a dead end -----------------------------------------


def test_a_directory_row_says_where_the_person_sits_in_the_family(
    world: dict[str, object],
) -> None:
    page = _page(world, reverse("directory"))
    assert "Mom&#x27;s side" in page or "Mom's side" in page
    assert "Nana&#x27;s house" in page or "Nana's house" in page


def test_a_profile_shows_what_that_person_actually_wrote(world: dict[str, object]) -> None:
    pod, rose = world["pod"], world["rose"]
    assert isinstance(pod, Pod) and isinstance(rose, Member)
    posting.create_post(author=rose, pod=pod, audience_yards=[], body="Biggest fish of the day")
    page = _page(world, reverse("member_profile", args=[rose.id]))
    assert "Recent Posts" in page
    assert "Biggest fish of the day" in page


def test_a_profile_never_shows_a_post_the_viewer_could_not_see_on_the_feed(
    world: dict[str, object],
) -> None:
    """The recent-posts section runs through the SAME audience query the feed uses, so the
    directory cannot become a second route into somebody else's household."""
    far_yard = Yard.objects.create(name="Dad's side", slug="dads-side")
    far_house = Pod.objects.create(name="Far house", kind=Pod.HOUSEHOLD)
    far_house.yards.set([far_yard])
    rose = world["rose"]
    assert isinstance(rose, Member)
    PodMembership.objects.create(member=rose, pod=far_house)  # Rose bridges both sides
    posting.create_post(author=rose, pod=far_house, audience_yards=[], body="FAR-SIDE-SECRET")

    page = _page(world, reverse("member_profile", args=[rose.id]))
    assert "FAR-SIDE-SECRET" not in page
    # ...and her far-side household is not named in the placing line either (the same
    # traversal leak scoping.visible_pods_of exists to close).
    assert "Far house" not in page
