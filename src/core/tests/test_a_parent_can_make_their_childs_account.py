"""S-703's capability existed, was authorized, and could not be reached by a parent.

`can_create_supervised` has always allowed a member to create a supervised account they
will manage themselves — `actor.pk == parent.pk` is its first branch. But the only control
in the product sat on `/members/`, which is `is_admin` only. Measured before the fix:

    permissions.can_create_supervised(parent, parent) = True
    GET /members/ as that parent -> 403
    POST create_supervised directly -> 302
    child created: True
    'create_supervised' offered on Settings: False

The permission said yes, the page said no, and a hand-written POST worked. So every child
account had to go through an admin, in a product whose whole point is that a family runs
its own instance.
"""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core import permissions, supervised
from core.models import Member, Pod, PodMembership, Yard

User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"


@pytest.fixture
def parent_at_home() -> tuple[Client, Member, Pod, Yard]:
    yard = Yard.objects.create(name="Y", slug="y")
    pod = Pod.objects.create(name="Their house")
    pod.yards.set([yard])
    user = User.objects.create_user(username="parent")
    parent = Member.objects.create(display_name="A Parent", user=user)
    PodMembership.objects.create(member=parent, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return client, parent, pod, yard


@pytest.mark.django_db
def test_a_parent_is_offered_the_control_on_their_own_settings(
    parent_at_home: tuple[Client, Member, Pod, Yard],
) -> None:
    """Reachable by following links, not by knowing the URL — an ordinary member cannot
    open the roster where the only other copy of this control lives."""
    client, parent, _pod, _yard = parent_at_home
    assert permissions.can_create_supervised(parent, parent), "premise changed"
    assert client.get(reverse("members")).status_code == 403, (
        "the roster became reachable to a plain member; this test's premise is that it is not"
    )

    page = client.get(reverse("profile_edit"))
    assert reverse("create_supervised") in page.content.decode(), (
        "a parent is still not offered any way to create their own child's account, so the "
        "permission that explicitly allows it remains unreachable"
    )


@pytest.mark.django_db
def test_the_control_works_end_to_end_from_settings(
    parent_at_home: tuple[Client, Member, Pod, Yard],
) -> None:
    client, parent, pod, _yard = parent_at_home
    response = client.post(
        reverse("create_supervised"),
        {"parent_id": parent.pk, "pod_id": pod.pk, "display_name": "Ollie"},
    )
    # Back to Settings, not the roster: a plain member gets a 403 there, and redirecting
    # somebody to a page they cannot open is a dead end at the end of a working action.
    assert response.status_code == 302
    assert response.headers["Location"] == reverse("profile_edit"), response.headers["Location"]

    child = Member.objects.get(display_name="Ollie")
    assert child.is_supervised and child.managing_parent_id == parent.pk
    assert child.user_id is None, "a supervised child must have no independent login"
    assert list(child.pods.all()) == [pod]


@pytest.mark.django_db
def test_a_child_cannot_be_placed_in_a_household_their_parent_is_not_in(
    parent_at_home: tuple[Client, Member, Pod, Yard],
) -> None:
    """The service invariant, and the reason the offered list narrowed.

    The roster offered `scoping.visible_pods(actor)` — for an instance admin, every pod on
    the instance. The obvious mistake, picking the wrong household from a long list, put a
    child in a family their own parent is not in. Nothing refused it: the view checked only
    that the POD was visible to whoever submitted the form.
    """
    _client, parent, _pod, yard = parent_at_home
    elsewhere = Pod.objects.create(name="Another house")
    elsewhere.yards.set([yard])

    with pytest.raises(ValueError, match="is not in"):
        supervised.create_supervised_member(parent=parent, display_name="Stranded", pod=elsewhere)
    assert not Member.objects.filter(display_name="Stranded").exists(), (
        "it refused and created the child anyway"
    )


@pytest.mark.django_db
def test_a_handcrafted_post_is_refused_rather_than_crashing(
    parent_at_home: tuple[Client, Member, Pod, Yard],
) -> None:
    """Neither control can express this, so a request that does was written by hand. It is
    answered as a refusal — a 500 would be an unhandled invariant reaching the operator as
    a stack trace.

    Submitted as an ADMIN on purpose. For the parent themselves the pod is not visible at
    all, so `require_visible_pod` answers 404 first and the invariant is never reached —
    which is the audience guard working, and the reason this path belongs to the one actor
    who CAN see every pod on the instance.
    """
    _client, parent, pod, yard = parent_at_home
    elsewhere = Pod.objects.create(name="Another house")
    elsewhere.yards.set([yard])

    admin_user = User.objects.create_user(username="admin-handcrafting")
    admin = Member.objects.create(display_name="Admin", user=admin_user, role=Member.INSTANCE_ADMIN)
    PodMembership.objects.create(member=admin, pod=pod)
    PodMembership.objects.create(member=admin, pod=elsewhere)
    client = Client()
    client.force_login(admin_user, backend=_BACKEND)

    response = client.post(
        reverse("create_supervised"),
        {"parent_id": parent.pk, "pod_id": elsewhere.pk, "display_name": "Stranded"},
    )
    assert response.status_code == 403, response.status_code
    assert not Member.objects.filter(display_name="Stranded").exists()


@pytest.mark.django_db
def test_the_roster_offers_only_the_parents_own_households(
    parent_at_home: tuple[Client, Member, Pod, Yard],
) -> None:
    """An admin's copy of the control must not be able to express the refusal above."""
    _client, parent, pod, yard = parent_at_home
    elsewhere = Pod.objects.create(name="A pod the parent is not in")
    elsewhere.yards.set([yard])

    admin_user = User.objects.create_user(username="admin")
    admin = Member.objects.create(display_name="Admin", user=admin_user, role=Member.INSTANCE_ADMIN)
    PodMembership.objects.create(member=admin, pod=pod)
    # The admin must be in the other household TOO, or this test cannot tell the two
    # behaviours apart: `visible_pods(admin)` would not have offered it either, so the
    # assertion below would pass against the very code it exists to forbid. Caught by
    # reverting the fix and watching this test stay green — a guard that has not been seen
    # to fail has not been tested.
    PodMembership.objects.create(member=admin, pod=elsewhere)
    client = Client()
    client.force_login(admin_user, backend=_BACKEND)

    body = client.get(reverse("members")).content.decode()

    # Read the PARENT's own select, not the whole page. The admin's row renders a child form
    # too and the admin IS in the other household, so a page-wide substring check goes red on
    # correct code — for the right reason, in the wrong place.
    select = re.search(rf'<select id="child-pod-{parent.pk}"[^>]*>(.*?)</select>', body, re.S)
    assert select is not None, "the parent's row offers no household control at all"
    offered = select.group(1)

    assert pod.name in offered, "denominator: the parent's own household must be offered"
    assert elsewhere.name not in offered, (
        "the roster offered a household the parent is not in, so an admin picking the wrong "
        "line puts a child somewhere their own parent cannot see them"
    )


@pytest.mark.django_db
def test_an_adhoc_group_is_not_offered_as_a_household(
    parent_at_home: tuple[Client, Member, Pod, Yard],
) -> None:
    """The control says "households". `member.pods` includes ad-hoc groups.

    This is the same mislabel already fixed once on this roster — "Which household" over a
    list built from `visible_pods` — reintroduced by a new field a few weeks later. A child
    does not belong to a book club, and a caption that says households must offer households.
    """
    client, parent, pod, yard = parent_at_home
    club = Pod.objects.create(name="The book club", kind=Pod.ADHOC, owner=parent)
    club.yards.set([yard])
    PodMembership.objects.create(member=parent, pod=club)

    select = re.search(
        r'<select id="own-child-pod"[^>]*>(.*?)</select>',
        client.get(reverse("profile_edit")).content.decode(),
        re.S,
    )
    assert select is not None, "the parent is offered no household control at all"
    offered = select.group(1)
    assert pod.name in offered, "denominator: their actual household must be offered"
    assert club.name not in offered, (
        "an ad-hoc group was offered as a household, under a label that says households"
    )


@pytest.mark.django_db
def test_the_roster_does_not_run_a_query_per_row(
    parent_at_home: tuple[Client, Member, Pod, Yard],
) -> None:
    """`member.pods.order_by("name")` inside the row loop is one query per roster line.

    Worse than ordinary N+1: the `order_by` is exactly what stops a plain
    `prefetch_related` from being used, so the obvious way to write it is also the one that
    cannot benefit from the obvious fix. It is a `Prefetch` with the ordering inside.

    Asserted as "the count does not grow with the roster" rather than against a fixed
    number, which would be a magic constant that gets edited whenever it fails.
    """
    _client, _parent, pod, _yard = parent_at_home
    admin_user = User.objects.create_user(username="counting-admin")
    admin = Member.objects.create(display_name="Admin", user=admin_user, role=Member.INSTANCE_ADMIN)
    PodMembership.objects.create(member=admin, pod=pod)
    client = Client()
    client.force_login(admin_user, backend=_BACKEND)

    def queries_for(extra: int) -> int:
        for index in range(extra):
            relative = Member.objects.create(display_name=f"Relative {index}")
            PodMembership.objects.create(member=relative, pod=pod)
        with CaptureQueriesContext(connection) as captured:
            assert client.get(reverse("members")).status_code == 200
        return len(captured)

    small = queries_for(2)
    large = queries_for(20)
    assert large <= small + 2, (
        f"the roster ran {small} queries for 3 members and {large} for 23 — it is doing work "
        "per row. On a family instance that is slow; the reason it is a defect rather than a "
        "preference is that the fix (a Prefetch) is also the only way to order the households "
        "without a query each."
    )
