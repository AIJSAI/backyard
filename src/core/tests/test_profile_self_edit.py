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
