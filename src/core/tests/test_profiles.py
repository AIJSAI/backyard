"""Profiles and the directory (S-901, S-902): the isolation suite grows to fields.

The directory lists only members who share a yard with the viewer and never leaks
across a yard (same 404 rule as posts). Each contact field is shown only to a viewer
the owner scoped it for: HIDDEN to no one, POD to pod-mates, YARD to yard-mates. A
birthday shows month and day, never a year or an age. Family dates carry the same
per-field visibility as contacts (S-903), and the feed's on-the-day banner is the
only in-product surface for them: quiet, pull-based, never a push.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import profiles, supervised
from core.models import Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_TEST_PW = "a-Strong-passphrase-9"


def _member_with_user(pod: Pod, name: str) -> Member:
    user = User.objects.create_user(username=name.lower(), password=_TEST_PW)
    member = Member.objects.create(display_name=name, user=user)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _client_for(member: Member) -> Client:
    assert member.user is not None
    c = Client()
    c.force_login(member.user, backend=_BACKEND)
    return c


@dataclass
class World:
    maternal: Yard
    paternal: Yard
    author: Member  # m_pod_a
    pod_mate: Member  # m_pod_a (same pod as author)
    yard_mate: Member  # m_pod_b (same yard, different pod)
    other: Member  # paternal


@pytest.fixture
def world() -> World:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    m_pod_a = Pod.objects.create(name="Cousins A")
    m_pod_a.yards.set([maternal])
    m_pod_b = Pod.objects.create(name="Cousins B")
    m_pod_b.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal")
    p_pod.yards.set([paternal])
    return World(
        maternal=maternal,
        paternal=paternal,
        author=_member_with_user(m_pod_a, "Author"),
        pod_mate=_member_with_user(m_pod_a, "PodMate"),
        yard_mate=_member_with_user(m_pod_b, "YardMate"),
        other=_member_with_user(p_pod, "Other"),
    )


# --- birthday: month and day, never a year or age ---


def test_birthday_text_shows_month_and_day_only(world: World) -> None:
    world.author.birthday_month = 3
    world.author.birthday_day = 5
    world.author.birthday_year = 1980
    assert profiles.birthday_text(world.author) == "March 5"  # no year, no age


def test_birthday_text_empty_without_month_and_day(world: World) -> None:
    world.author.birthday_month = 3
    world.author.birthday_day = None
    assert profiles.birthday_text(world.author) == ""


# --- per-field visibility ---


def test_field_visibility_pod_yard_hidden(world: World) -> None:
    author = world.author
    author.phone = "555-1111"
    author.phone_visibility = Member.YARD
    author.address = "1 Maple St"
    author.address_visibility = Member.POD
    author.contact_email = "a@example.com"
    author.contact_email_visibility = Member.HIDDEN
    author.save()

    pod_labels = {c.label for c in profiles.viewable_profile(world.pod_mate, author).contacts}
    yard_labels = {c.label for c in profiles.viewable_profile(world.yard_mate, author).contacts}
    own_labels = {c.label for c in profiles.viewable_profile(author, author).contacts}

    assert pod_labels == {"Phone", "Address"}  # pod-mate: YARD + POD, not HIDDEN
    assert yard_labels == {"Phone"}  # yard-mate (different pod): YARD only, not POD
    assert own_labels == {"Phone", "Address", "Email"}  # the owner sees everything


# --- directory view ---


def test_directory_lists_yard_members_not_cross_yard(world: World) -> None:
    body = _client_for(world.author).get(reverse("directory")).content.decode()
    assert "PodMate" in body
    assert "YardMate" in body
    assert "Author" not in body  # the viewer is excluded from their own directory list
    assert "Other" not in body  # paternal member never appears


def test_directory_search_filters_by_name(world: World) -> None:
    body = _client_for(world.author).get(reverse("directory"), {"q": "PodMate"}).content.decode()
    assert "PodMate" in body
    assert "YardMate" not in body


def test_member_profile_cross_yard_404s(world: World) -> None:
    assert (
        _client_for(world.author).get(reverse("member_profile", args=[world.other.id])).status_code
        == 404
    )


def test_member_profile_hides_unshared_fields(world: World) -> None:
    author = world.author
    author.phone = "555-2222"
    author.phone_visibility = Member.HIDDEN
    author.contact_email = "shown@example.com"
    author.contact_email_visibility = Member.YARD
    author.save()
    body = (
        _client_for(world.yard_mate)
        .get(reverse("member_profile", args=[author.id]))
        .content.decode()
    )
    assert "shown@example.com" in body  # YARD field visible to a yard-mate
    assert "555-2222" not in body  # HIDDEN field never leaks


# --- profile edit ---


def test_profile_edit_saves_fields(world: World) -> None:
    response = _client_for(world.author).post(
        reverse("profile_edit"),
        {
            "kinship_name": "Papa",
            "birthday_month": "3",
            "birthday_day": "5",
            "phone": "555-9999",
            "phone_visibility": "yard",
            "contact_email_visibility": "hidden",
            "address_visibility": "hidden",
        },
    )
    assert response.status_code == 302
    world.author.refresh_from_db()
    assert world.author.kinship_name == "Papa"
    assert world.author.birthday_month == 3
    assert world.author.phone_visibility == Member.YARD


def test_profile_edit_rejects_a_half_birthday(world: World) -> None:
    response = _client_for(world.author).post(
        reverse("profile_edit"),
        {"birthday_month": "3"},  # no day
    )
    assert response.status_code == 200  # re-rendered with the error
    world.author.refresh_from_db()
    assert world.author.birthday_month is None  # nothing saved


def test_profile_edit_defaults_an_unknown_visibility_to_hidden(world: World) -> None:
    response = _client_for(world.author).post(
        reverse("profile_edit"),
        {"phone": "555-0000", "phone_visibility": "everyone"},  # not a real choice
    )
    assert response.status_code == 302
    world.author.refresh_from_db()
    assert world.author.phone_visibility == Member.HIDDEN  # fail closed to no one


def test_profile_edit_rejects_an_impossible_year(world: World) -> None:
    """Security review of #33 LOW-1: an out-of-range year must be a validation
    message, never a smallint DataError 500."""
    response = _client_for(world.author).post(
        reverse("profile_edit"),
        {"birthday_month": "3", "birthday_day": "5", "birthday_year": "99999"},
    )
    assert response.status_code == 200  # re-rendered with the error, not a 500
    world.author.refresh_from_db()
    assert world.author.birthday_year is None  # nothing saved


# --- family dates carry per-field visibility (S-903) ---


def test_birthday_is_gated_like_a_contact_field(world: World) -> None:
    author = world.author
    author.birthday_month = 3
    author.birthday_day = 5
    author.birthday_visibility = Member.POD
    author.save()
    assert profiles.viewable_profile(world.pod_mate, author).birthday == "March 5"
    assert profiles.viewable_profile(world.yard_mate, author).birthday == ""  # absent
    assert profiles.viewable_profile(author, author).birthday == "March 5"  # own always


def test_hidden_birthday_shows_to_no_one_but_self(world: World) -> None:
    author = world.author
    author.birthday_month = 3
    author.birthday_day = 5
    author.birthday_visibility = Member.HIDDEN
    author.save()
    assert profiles.viewable_profile(world.pod_mate, author).birthday == ""
    assert profiles.viewable_profile(author, author).birthday == "March 5"


def test_birthday_defaults_to_yard_scope(world: World) -> None:
    """The migration default matches how far the birthday already reached (the whole
    directory), so the gate lands without silently widening or narrowing anyone."""
    author = world.author
    author.birthday_month = 3
    author.birthday_day = 5
    author.save()
    assert author.birthday_visibility == Member.YARD
    assert profiles.viewable_profile(world.yard_mate, author).birthday == "March 5"


def test_anniversary_mirrors_birthday_gating(world: World) -> None:
    author = world.author
    author.anniversary_month = 6
    author.anniversary_day = 10
    author.anniversary_year = 1980
    author.anniversary_visibility = Member.POD
    author.save()
    assert profiles.viewable_profile(world.pod_mate, author).anniversary == "June 10"
    assert profiles.viewable_profile(world.yard_mate, author).anniversary == ""


def test_supervised_member_dates_default_to_pod(world: World) -> None:
    """A freshly created supervised member's dates stay inside the household
    (T-MINOR-6) — asserted through the real creation path, not a fixture default."""
    pod = world.author.pods.first()
    assert pod is not None
    child = supervised.create_supervised_member(parent=world.author, display_name="Kid", pod=pod)
    child.refresh_from_db()
    assert child.birthday_visibility == Member.POD
    assert child.anniversary_visibility == Member.POD


def test_no_year_or_age_renders_anywhere(world: World) -> None:
    author = world.author
    author.birthday_month = 3
    author.birthday_day = 5
    author.birthday_year = 1950
    author.anniversary_month = 6
    author.anniversary_day = 10
    author.anniversary_year = 1980
    author.save()
    viewer = _client_for(world.yard_mate)
    profile_body = viewer.get(reverse("member_profile", args=[author.id])).content.decode()
    directory_body = viewer.get(reverse("directory")).content.decode()
    assert "March 5" in profile_body and "June 10" in profile_body
    for body in (profile_body, directory_body):
        assert "1950" not in body and "1980" not in body  # never a year, never an age


# --- the one date resolver and the quiet banner (S-903) ---


def test_upcoming_dates_honors_visibility(world: World) -> None:
    start = datetime.date(2026, 3, 1)
    for member in (world.pod_mate, world.yard_mate):
        member.birthday_month = 3
        member.birthday_day = 4
        member.birthday_visibility = Member.POD
        member.save()
    found = profiles.upcoming_dates(world.author, start=start, days=7)
    names = {d.display_name for d in found}
    assert names == {"PodMate"}  # POD-scoped: the pod-mate's date, not the yard-mate's
    assert found[0].on == datetime.date(2026, 3, 4)
    assert found[0].date_text == "March 4"


def test_upcoming_dates_window_crosses_new_year(world: World) -> None:
    author = world.author
    author.birthday_month = 1
    author.birthday_day = 2
    author.save()
    found = profiles.upcoming_dates(world.yard_mate, start=datetime.date(2026, 12, 29), days=7)
    assert [d.member_id for d in found] == [author.id]
    assert found[0].on == datetime.date(2027, 1, 2)


def test_upcoming_dates_caps_its_window(world: World) -> None:
    """Security review of #33 LOW-2: the resolver owns its own bound; past a year
    every (month, day) recurs, so a larger ask is a caller bug."""
    with pytest.raises(ValueError):
        profiles.upcoming_dates(world.author, start=datetime.date(2026, 1, 1), days=367)


def test_feed_banner_shows_only_todays_dates(world: World) -> None:
    today = timezone.localdate()
    tomorrow = today + datetime.timedelta(days=1)
    world.pod_mate.birthday_month = today.month
    world.pod_mate.birthday_day = today.day
    world.pod_mate.save()
    world.yard_mate.birthday_month = tomorrow.month
    world.yard_mate.birthday_day = tomorrow.day
    world.yard_mate.save()
    body = _client_for(world.author).get(reverse("feed")).content.decode()
    assert "PodMate" in body and "birthday" in body  # the quiet banner, today only
    assert "YardMate" not in body  # tomorrow's date is not today's banner


# --- kinship name in the feed (S-901) ---


def test_kinship_name_shows_in_the_feed(world: World) -> None:
    world.author.kinship_name = "Papa"
    world.author.save(update_fields=["kinship_name"])
    pod = world.author.pods.first()
    assert pod is not None
    Post.objects.create(author=world.author, pod=pod, body="hi all")
    body = _client_for(world.pod_mate).get(reverse("feed")).content.decode()
    assert "Author (Papa)" in body
