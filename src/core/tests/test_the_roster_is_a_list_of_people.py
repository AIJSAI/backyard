"""The roster is a list of PEOPLE, and a row that can do nothing says why.

Walk items 13 and 8, 2026-09-19.

ITEM 13. Every control for every relative was open at once: for each person a role select
and its button, a remove disclosure, and an add-a-child disclosure. On a six-person family
that is about five phone screens, four-fifths of it destruction UI — and the thing an
admin opens this page for, "who is in this family", was the one thing you had to scroll
past all of it to read. One compact line per person now; the actions live behind a single
native `<details>` on the row they belong to.

`<details>` rather than script, deliberately: it is keyboard-operable and announced as a
disclosure without a line of JavaScript, on the oldest phone in this family. The existing
e2e lane and the axe sweep both walk /members/ and both stay green, which is the other
half of this item.

ITEM 8. Some rows simply ended after the name and the badge — no actions, and nothing
saying why — so a side admin looking at her sister's household could not tell whether the
product was broken, whether she had done something wrong, or whether it was deliberate. It
is deliberate every time, and there are only three reasons, so the row now says which.
"""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _instance_admin(username: str = "ada") -> tuple[Client, Member, Pod, Yard]:
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = User.objects.create_user(username=username)
    admin = Member.objects.create(display_name="Ada Reed", user=user, role=Member.INSTANCE_ADMIN)
    PodMembership.objects.create(member=admin, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return client, admin, pod, yard


def _row_for(html: str, name: str) -> str:
    """The one `<li>` belonging to this person."""
    start = html.index(name)
    start = html.rindex("<li>", 0, start)
    return html[start : html.index("</li>", start)]


# --- item 13 --------------------------------------------------------------------------


def test_a_persons_row_is_one_line_with_everything_else_behind_manage() -> None:
    client, _admin, pod, _yard = _instance_admin()
    cousin_user = User.objects.create_user(username="cousin")
    cousin = Member.objects.create(display_name="Cousin Reed", user=cousin_user)
    PodMembership.objects.create(member=cousin, pod=pod)

    row = _row_for(client.get(reverse("members")).content.decode(), "Cousin Reed")

    assert '<details class="member-manage">' in row, "the row has no Manage disclosure"
    assert "<summary>Manage" in row
    # The actions are still all there — behind it, not gone.
    assert reverse("assign_role", args=[cousin.id]) in row
    assert reverse("member_remove", args=[cousin.id]) in row
    assert reverse("create_supervised") in row, "child accounts left the roster entirely"
    assert reverse("issue_recovery", args=[cousin.id]) in row

    # ...and the summary is the ONLY thing between the name and them: the role select and
    # the remove button must not be siblings of the name any more.
    head = row[: row.index("<details")]
    assert "<select" not in head and "<form" not in head, (
        "a control is still open on the row's head line, which is what made this page five "
        "screens long"
    )


def test_each_manage_has_a_name_a_screen_reader_can_tell_apart() -> None:
    """Six identical "Manage" controls on one page is a list a screen-reader user cannot
    navigate. The name is in visually-hidden text rather than on screen, because the
    visible line already carries it an inch away."""
    client, _admin, pod, _yard = _instance_admin()
    for name, username in (("Cousin Reed", "cousin"), ("Sam Reed", "sam")):
        member = Member.objects.create(
            display_name=name, user=User.objects.create_user(username=username)
        )
        PodMembership.objects.create(member=member, pod=pod)

    html = client.get(reverse("members")).content.decode()
    summaries = re.findall(r"<summary>Manage(.*?)</summary>", html)
    assert len(summaries) >= 3, summaries
    assert all('class="visually-hidden"' in s for s in summaries), summaries
    assert len({s for s in summaries}) == len(summaries), (
        f"two Manage controls announce the same name: {summaries}"
    )


def test_no_javascript_was_added_to_this_page() -> None:
    """The disclosure is native markup. A roster that needs a script is a roster that does
    not work for the person most likely to be on an old phone.

    Scoped to the ROSTER's own markup: every signed-in page carries base.html's
    service-worker registration, which is the PWA and not this page's doing.
    """
    client, _admin, pod, _yard = _instance_admin()
    member = Member.objects.create(
        display_name="Cousin Reed", user=User.objects.create_user(username="cousin")
    )
    PodMembership.objects.create(member=member, pod=pod)
    html = client.get(reverse("members")).content.decode()
    roster = html[html.index('<ul class="members">') : html.rindex("</ul>")]
    assert "Cousin Reed" in roster  # non-vacuity: this really is the roster
    assert "<script" not in roster, "the roster grew a script"
    assert "onclick" not in roster and "data-toggle" not in roster


# --- item 8 ---------------------------------------------------------------------------


def test_a_bridging_relative_a_side_admin_cannot_touch_says_why() -> None:
    """The case the walk actually hit. A household that belongs to BOTH sides is exactly
    what the owner's sister's household will be, so this row is not a corner case."""
    _client, family_admin, moms_pod, moms = _instance_admin()
    dads = Yard.objects.create(name="Dad's side", slug="dads-side")
    bridge = Pod.objects.create(name="The Both-Sides", kind=Pod.HOUSEHOLD)
    bridge.yards.set([moms, dads])
    bridging = Member.objects.create(
        display_name="Jo Reed", user=User.objects.create_user(username="jo")
    )
    PodMembership.objects.create(member=bridging, pod=bridge)

    side_admin_user = User.objects.create_user(username="sam")
    side_admin = Member.objects.create(
        display_name="Sam Reed", user=side_admin_user, role=Member.YARD_ADMIN
    )
    PodMembership.objects.create(member=side_admin, pod=moms_pod)

    client = Client()
    client.force_login(side_admin_user, backend=_BACKEND)
    html = client.get(reverse("members")).content.decode()
    row = _row_for(html, "Jo Reed")

    assert "member-manage" not in row, "the row offers Manage with nothing behind it"
    # "Also on the other side" until 2026-09-20. This line is rendered for one reader only
    # — an admin whose reach does not cover everybody on their roster — so it was the
    # product telling somebody on one side that a second side exists. The reason is stated
    # as what it is now; the rule, the key and the named person are unchanged.
    assert "Outside what you manage" in row
    assert "other side" not in row, row
    # It names the person who CAN, so the admin knows who to ask rather than
    # tapping at a row that will never answer.
    assert family_admin.short_name in row, row


def test_a_peer_admins_row_says_that_instead() -> None:
    _client, _family_admin, pod, _moms = _instance_admin()
    peer = Member.objects.create(
        display_name="Bo Reed",
        user=User.objects.create_user(username="bo"),
        role=Member.INSTANCE_ADMIN,
    )
    PodMembership.objects.create(member=peer, pod=pod)

    side_admin_user = User.objects.create_user(username="sam")
    side_admin = Member.objects.create(
        display_name="Sam Reed", user=side_admin_user, role=Member.YARD_ADMIN
    )
    PodMembership.objects.create(member=side_admin, pod=pod)

    client = Client()
    client.force_login(side_admin_user, backend=_BACKEND)
    row = _row_for(client.get(reverse("members")).content.decode(), "Bo Reed")

    assert "member-manage" not in row
    assert "An admin, so only" in row


def test_a_child_accounts_row_names_the_parent_and_not_the_family_admin() -> None:
    """The catch-all said "only <the family admin> can change this" over a child account,
    which the permission matrix contradicts: a supervised account is their managing
    parent's (TM-10), and the family admin is the wrong person to send an admin to.

    The admin here is a peer of the parent, not the parent: a supervised child's own parent
    gets controls on the row (the test below), so this sentence is only ever read by
    somebody who has none.
    """
    _client, _family_admin, pod, _moms = _instance_admin()
    parent = Member.objects.create(
        display_name="Pat Reed", user=User.objects.create_user(username="pat")
    )
    PodMembership.objects.create(member=parent, pod=pod)
    child = Member.objects.create(
        display_name="Kit Reed", is_supervised=True, managing_parent=parent
    )
    PodMembership.objects.create(member=child, pod=pod)

    other_admin_user = User.objects.create_user(username="sam")
    other_admin = Member.objects.create(
        display_name="Sam Reed", user=other_admin_user, role=Member.YARD_ADMIN
    )
    PodMembership.objects.create(member=other_admin, pod=pod)

    client = Client()
    client.force_login(other_admin_user, backend=_BACKEND)
    row = _row_for(client.get(reverse("members")).content.decode(), "Kit Reed")

    assert "member-manage" not in row, "the row offers Manage with nothing behind it"
    assert "A child account, so their parent changes it." in row
    assert "Family Admin" not in row, row


def test_the_childs_own_parent_gets_controls_rather_than_the_sentence() -> None:
    """The other half, and the reason the arm above is reached only by somebody else:
    `can_edit_profile_of` gives the managing parent Edit Profile whatever their role, so
    their row has actions and no explanation at all."""
    _client, _family_admin, pod, _moms = _instance_admin()
    parent_user = User.objects.create_user(username="pat")
    parent = Member.objects.create(display_name="Pat Reed", user=parent_user)
    PodMembership.objects.create(member=parent, pod=pod)
    child = Member.objects.create(
        display_name="Kit Reed", is_supervised=True, managing_parent=parent
    )
    PodMembership.objects.create(member=child, pod=pod)
    # The parent is an admin here only because the roster is an admin-only page; the
    # custody branch they rely on reads `managing_parent`, never a role.
    Member.objects.filter(pk=parent.pk).update(role=Member.YARD_ADMIN)

    client = Client()
    client.force_login(parent_user, backend=_BACKEND)
    row = _row_for(client.get(reverse("members")).content.decode(), "Kit Reed")

    assert "member-manage" in row, row
    assert "A child account, so their parent changes it." not in row


def test_a_row_with_actions_says_nothing_of_the_kind() -> None:
    """Non-vacuity for the three above: the explanation is not printed on every row."""
    client, _admin, pod, _yard = _instance_admin()
    cousin = Member.objects.create(
        display_name="Cousin Reed", user=User.objects.create_user(username="cousin")
    )
    PodMembership.objects.create(member=cousin, pod=pod)

    row = _row_for(client.get(reverse("members")).content.decode(), "Cousin Reed")
    assert "why-no-actions" not in row
    assert "member-manage" in row


def test_the_explanation_degrades_when_no_admin_can_be_named() -> None:
    """`help_contact` resolves to "" when there is no active instance admin with a name —
    a removed founder, mid-succession. The sentence must still be a sentence."""
    _client, family_admin, pod, moms = _instance_admin()
    dads = Yard.objects.create(name="Dad's side", slug="dads-side")
    bridge = Pod.objects.create(name="The Both-Sides", kind=Pod.HOUSEHOLD)
    bridge.yards.set([moms, dads])
    bridging = Member.objects.create(
        display_name="Jo Reed", user=User.objects.create_user(username="jo")
    )
    PodMembership.objects.create(member=bridging, pod=bridge)

    side_admin_user = User.objects.create_user(username="sam")
    side_admin = Member.objects.create(
        display_name="Sam Reed", user=side_admin_user, role=Member.YARD_ADMIN
    )
    PodMembership.objects.create(member=side_admin, pod=pod)
    # The only instance admin loses their name, which is what help_contact_name excludes on.
    Member.objects.filter(pk=family_admin.pk).update(display_name="")

    client = Client()
    client.force_login(side_admin_user, backend=_BACKEND)
    row = _row_for(client.get(reverse("members")).content.decode(), "Jo Reed")
    assert "so only" in row and "the Family Admin" in row
    assert "so only  can change" not in " ".join(row.split()), "the sentence lost its subject"


# --- the roster does not ask the same question once per person ------------------------


def test_the_actors_own_reach_is_resolved_once_not_once_per_row(
    django_assert_num_queries: object,
) -> None:
    """Copilot thread 1, measured rather than reasoned.

    `_no_actions_reason` resolved `scoping.visible_yards(actor)` itself, which is a
    property of the ACTOR and identical for every row — so it cost one query per person on
    the roster. The count below is asserted as a CEILING that does not move when the
    family grows: five more relatives must not buy five more queries.
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    client, _admin, pod, _yard = _instance_admin()
    for n in range(3):
        member = Member.objects.create(
            display_name=f"Cousin {n}", user=User.objects.create_user(username=f"c{n}")
        )
        PodMembership.objects.create(member=member, pod=pod)

    with CaptureQueriesContext(connection) as small:
        client.get(reverse("members"))

    for n in range(3, 9):
        member = Member.objects.create(
            display_name=f"Cousin {n}", user=User.objects.create_user(username=f"c{n}")
        )
        PodMembership.objects.create(member=member, pod=pod)

    with CaptureQueriesContext(connection) as large:
        client.get(reverse("members"))

    # Six more people. Some per-row work is inherent (each row asks which sides that
    # person is on), but the ACTOR's reach must not be among it.
    growth = len(large) - len(small)
    assert growth <= 6, (
        f"{growth} extra queries for 6 extra people - the roster is asking something "
        "about the ACTOR once per row again"
    )
