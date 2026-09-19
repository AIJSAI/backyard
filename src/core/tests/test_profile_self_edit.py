"""S-901 acceptance 3: "Owners edit their own profiles; supervised and elder profiles are
manageable by the parent or designated helper."

The story sat at `passing` while neither half held. The self-edit form covered every field
EXCEPT `display_name` — so a member who married, changed their name, or was simply typed in
wrong could not fix their own name and had to ask someone with an admin role. And there was
no route at all for a parent to maintain a supervised child's profile, or for anyone to
maintain an elder's, though an elder has no login of her own by design (TM-10) and
therefore CANNOT be the owner who edits it.

The authorization arm matters more than the feature: a profile edit that reached across a
yard boundary, or let any member rewrite anyone's name, would be worse than the gap.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core import supervised
from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_TEST_PW = "a-Strong-passphrase-9"


def _member(pod: Pod, name: str, *, role: str = Member.MEMBER) -> Member:
    user = User.objects.create_user(username=name.lower().replace(" ", ""), password=_TEST_PW)
    member = Member.objects.create(display_name=name, user=user, role=role)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _client_for(member: Member) -> Client:
    assert member.user is not None
    client = Client()
    client.force_login(member.user, backend=_BACKEND)
    return client


@pytest.fixture
def world() -> dict[str, object]:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Our house")
    pod.yards.set([yard])
    far_yard = Yard.objects.create(name="Paternal", slug="paternal")
    far_pod = Pod.objects.create(name="Far house")
    far_pod.yards.set([far_yard])
    return {
        "pod": pod,
        "far_pod": far_pod,
        "parent": _member(pod, "Priya"),
        "podmate": _member(pod, "Sam"),
        "stranger": _member(far_pod, "Distant Cousin"),
        "admin": _member(pod, "The Admin", role=Member.INSTANCE_ADMIN),
    }


def _payload(**over: str) -> dict[str, str]:
    data = {"display_name": "New Name"}
    data.update(over)
    return data


def test_a_member_can_finally_change_their_own_name(world: dict[str, object]) -> None:
    """The gap: every other profile field was self-editable and this one was not."""
    parent = world["parent"]
    assert isinstance(parent, Member)
    response = _client_for(parent).post(reverse("profile_edit"), _payload(display_name="Priya R"))
    assert response.status_code == 302
    parent.refresh_from_db()
    assert parent.display_name == "Priya R"


def test_an_empty_name_is_refused(world: dict[str, object]) -> None:
    """A name is how a family recognises someone; blank is never what was meant."""
    parent = world["parent"]
    assert isinstance(parent, Member)
    response = _client_for(parent).post(reverse("profile_edit"), _payload(display_name="   "))
    assert response.status_code == 200  # re-rendered with the error, not saved
    parent.refresh_from_db()
    assert parent.display_name == "Priya"


def test_a_parent_can_maintain_their_supervised_child_s_profile(
    world: dict[str, object],
) -> None:
    parent, pod = world["parent"], world["pod"]
    assert isinstance(parent, Member) and isinstance(pod, Pod)
    child = supervised.create_supervised_member(parent=parent, display_name="Kiddo", pod=pod)

    response = _client_for(parent).post(
        reverse("managed_profile_edit", args=[child.pk]),
        _payload(display_name="Kiddo R", kinship_name="Squish"),
    )
    assert response.status_code == 302
    child.refresh_from_db()
    assert child.display_name == "Kiddo R"
    assert child.kinship_name == "Squish"


def test_the_managed_form_posts_back_to_the_person_being_edited(
    world: dict[str, object],
) -> None:
    """A hardcoded self-edit action would send a parent's edits of their child to the
    PARENT's own record — the form looks right and quietly changes the wrong person."""
    parent, pod = world["parent"], world["pod"]
    assert isinstance(parent, Member) and isinstance(pod, Pod)
    child = supervised.create_supervised_member(parent=parent, display_name="Kiddo", pod=pod)
    page = _client_for(parent).get(reverse("managed_profile_edit", args=[child.pk]))
    assert reverse("managed_profile_edit", args=[child.pk]) in page.content.decode()


def test_a_pod_mate_cannot_rewrite_someone_else_s_name(world: dict[str, object]) -> None:
    """The authorization arm. Sharing a pod makes you visible to each other; it does not
    make you each other's editor."""
    podmate, parent = world["podmate"], world["parent"]
    assert isinstance(podmate, Member) and isinstance(parent, Member)
    response = _client_for(podmate).post(
        reverse("managed_profile_edit", args=[parent.pk]), _payload(display_name="Hijacked")
    )
    assert response.status_code == 403
    parent.refresh_from_db()
    assert parent.display_name == "Priya"


def test_editing_across_a_yard_boundary_is_a_404_not_a_403(
    world: dict[str, object],
) -> None:
    """S-902's parity rule: someone outside your yards must be indistinguishable from
    someone who does not exist, so the refusal cannot be used to confirm they do."""
    parent, stranger = world["parent"], world["stranger"]
    assert isinstance(parent, Member) and isinstance(stranger, Member)
    response = _client_for(parent).post(
        reverse("managed_profile_edit", args=[stranger.pk]), _payload()
    )
    assert response.status_code == 404
    stranger.refresh_from_db()
    assert stranger.display_name == "Distant Cousin"


def test_an_admin_can_maintain_an_elder_s_profile(world: dict[str, object]) -> None:
    """An elder has no login by design (TM-10), so she can never be the owner who edits
    it. The admin who provisions her link is the 'designated helper' the story names."""
    admin, pod = world["admin"], world["pod"]
    assert isinstance(admin, Member) and isinstance(pod, Pod)
    elder = Member.objects.create(display_name="Nana")
    PodMembership.objects.create(member=elder, pod=pod)

    response = _client_for(admin).post(
        reverse("managed_profile_edit", args=[elder.pk]),
        _payload(display_name="Nana Whitfield", kinship_name="Nana"),
    )
    assert response.status_code == 302
    elder.refresh_from_db()
    assert elder.display_name == "Nana Whitfield"


# --- the contact half, which BY-11 did NOT widen -----------------------------------
#
# BY-11 opened this form to any admin who may manage the target, so a yard admin can fix a
# name typed wrong at invite time. This page renders the RAW `Member` row rather than
# `profiles.viewable_profile`, so without a second line the same widening would hand every
# yard admin a plaintext read of a phone number and a home address their owner scoped to
# "No one", plus the visibility select that publishes it to a whole side of the family.

_HIDDEN_PHONE = "555 0101"
_HIDDEN_ADDRESS = "12 Rowan Lane"


def _with_hidden_contact_details(member: Member) -> Member:
    member.phone = _HIDDEN_PHONE
    member.phone_visibility = Member.HIDDEN
    member.address = _HIDDEN_ADDRESS
    member.address_visibility = Member.HIDDEN
    member.contact_email = "nana@example.com"
    member.contact_email_visibility = Member.HIDDEN
    member.save()
    return member


def _yard_admin_over(pod: Pod) -> Member:
    return _member(pod, "The Delegate", role=Member.YARD_ADMIN)


def test_a_yard_admin_editing_a_relative_never_sees_their_contact_details(
    world: dict[str, object],
) -> None:
    """Showing the field is the same disclosure as changing it: the value arrives in a
    text input, in cleartext, on a page the owner never opened."""
    pod, podmate = world["pod"], world["podmate"]
    assert isinstance(pod, Pod) and isinstance(podmate, Member)
    _with_hidden_contact_details(podmate)
    delegate = _yard_admin_over(pod)

    body = (
        _client_for(delegate)
        .get(reverse("managed_profile_edit", args=[podmate.pk]))
        .content.decode()
    )
    assert _HIDDEN_PHONE not in body
    assert _HIDDEN_ADDRESS not in body
    assert "nana@example.com" not in body
    assert 'name="address_visibility"' not in body, "the control that publishes it"
    # ...and the half BY-11 was actually about is still there.
    assert 'name="display_name"' in body
    assert 'name="birthday_month"' in body


def test_a_hand_written_post_cannot_set_a_contact_field_the_page_would_not_show(
    world: dict[str, object],
) -> None:
    """The template `{% if %}` is presentation. The view refuses on the same predicate, or
    the control is a suggestion — `update_fields` simply never lists them."""
    pod, podmate = world["pod"], world["podmate"]
    assert isinstance(pod, Pod) and isinstance(podmate, Member)
    _with_hidden_contact_details(podmate)
    delegate = _yard_admin_over(pod)

    response = _client_for(delegate).post(
        reverse("managed_profile_edit", args=[podmate.pk]),
        _payload(
            display_name="Sam Corrected",
            phone="555 9999",
            address="somewhere else",
            address_visibility=Member.YARD,
            contact_email="attacker@example.com",
        ),
    )
    assert response.status_code == 302
    podmate.refresh_from_db()
    assert podmate.display_name == "Sam Corrected", "the widening BY-11 shipped is gone"
    assert podmate.phone == _HIDDEN_PHONE
    assert podmate.address == _HIDDEN_ADDRESS
    assert podmate.address_visibility == Member.HIDDEN, "an address was published silently"
    assert podmate.contact_email == "nana@example.com"


@pytest.mark.parametrize("editor", ["self", "instance_admin"])
def test_the_contact_half_stays_open_to_whoever_it_was_open_to_before(
    world: dict[str, object], editor: str
) -> None:
    """The set `can_edit_profile_of` had BEFORE BY-11: yourself, a managing parent (below),
    and the instance admin, who holds the database anyway (T-OP-G1)."""
    podmate, admin = world["podmate"], world["admin"]
    assert isinstance(podmate, Member) and isinstance(admin, Member)
    _with_hidden_contact_details(podmate)

    if editor == "self":
        client, url = _client_for(podmate), reverse("profile_edit")
    else:
        client = _client_for(admin)
        url = reverse("managed_profile_edit", args=[podmate.pk])

    assert _HIDDEN_PHONE in client.get(url).content.decode()
    assert client.post(url, _payload(display_name="Sam", phone="555 2222")).status_code == 302
    podmate.refresh_from_db()
    assert podmate.phone == "555 2222"


def test_a_managing_parent_keeps_the_contact_half_for_their_own_child(
    world: dict[str, object],
) -> None:
    """A supervised child's details are the parent's to keep: there is nobody else to
    keep them, since the account has no login of its own (TM-10)."""
    parent, pod = world["parent"], world["pod"]
    assert isinstance(parent, Member) and isinstance(pod, Pod)
    child = supervised.create_supervised_member(parent=parent, display_name="Kiddo", pod=pod)

    url = reverse("managed_profile_edit", args=[child.pk])
    assert 'name="phone"' in _client_for(parent).get(url).content.decode()
    assert _client_for(parent).post(url, _payload(phone="555 3333")).status_code == 302
    child.refresh_from_db()
    assert child.phone == "555 3333"


# --- BY-11 follow-on: the roster's link and this route have to agree ----------------


def test_the_instance_admins_edit_link_is_not_a_dead_link_across_a_side(
    world: dict[str, object],
) -> None:
    """The roster offers `Edit profile` on every row an admin may administer, and for the
    instance admin that is every member on the instance — they own it and sit above yard
    isolation (`permissions.administrable_members`; the threat model states plainly that
    isolation is a member-level promise, not an admin-level one, and the role's own
    description is "Manages anyone, on either side"). This route resolved the target
    through the READ guard instead, so the offered link 404d on click: the permission said
    yes and the page said the person does not exist.

    Removal, re-roling and the recovery link all resolve through the administrable set
    already. This one now does too, so the link and the route answer the same question.
    """
    admin, stranger = world["admin"], world["stranger"]
    assert isinstance(admin, Member) and isinstance(stranger, Member)
    client = _client_for(admin)
    url = reverse("managed_profile_edit", args=[stranger.pk])

    assert url in client.get(reverse("members")).content.decode(), "the roster stopped offering it"
    assert client.get(url).status_code == 200
    assert client.post(url, _payload(display_name="Distant Cousin Reid")).status_code == 302
    stranger.refresh_from_db()
    assert stranger.display_name == "Distant Cousin Reid"


def test_a_yard_admin_still_cannot_edit_across_a_side(world: dict[str, object]) -> None:
    """The other half of the same change: widening the lookup to the ADMINISTRABLE set
    must not widen it for anybody below the instance admin. A yard admin's administrable
    set IS the yard-scoped visible set, so the other side stays a byte-identical 404."""
    pod, stranger = world["pod"], world["stranger"]
    assert isinstance(pod, Pod) and isinstance(stranger, Member)
    delegate = _member(pod, "The Delegate", role=Member.YARD_ADMIN)
    url = reverse("managed_profile_edit", args=[stranger.pk])

    assert _client_for(delegate).get(url).status_code == 404
    assert _client_for(delegate).post(url, _payload()).status_code == 404
    stranger.refresh_from_db()
    assert stranger.display_name == "Distant Cousin"
