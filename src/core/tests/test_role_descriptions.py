"""S-907: the roster says what each role permits, and cannot lie about it.

The gap was measured, not guessed: the roster rendered "Pod owner / Yard admin /
Instance admin" and no sentence anywhere on the page described a capability, so the
relative being handed the admin controls had to be told out of band what picking one
would do.

Prose that describes authorization is a liability the moment the authorization moves,
so these descriptions are bound to reality in BOTH directions:

  * against `permissions.py` — a description cannot promise something the code
    refuses, or deny something the code allows. This is the half that matters, and
    it is behavioural: it calls the real predicate rather than reading source text.
  * against `docs/security/permission-matrix.md` — the human reference and the UI
    copy cannot drift apart silently.

A source-text assertion alone would be defeated by the comment beside the code, which
this project has already been bitten by; every claim below is exercised instead.
"""

from __future__ import annotations

import pathlib

import pytest

from core import permissions, pods
from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db

_MATRIX = pathlib.Path(__file__).resolve().parents[3] / "docs" / "security" / "permission-matrix.md"


@pytest.fixture
def side() -> Yard:
    return Yard.objects.create(name="Maternal", slug="maternal")


def _member(side: Yard, role: str, *, name: str) -> Member:
    pod = Pod.objects.create(name=f"{name}'s house")
    pod.yards.set([side])
    member = Member.objects.create(display_name=name, role=role)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def test_every_assignable_role_the_roster_offers_has_a_description() -> None:
    """The roster builds its key from ROLE_CHOICES filtered to the assignable set. A
    role added to the ladder without a sentence would render a blank definition."""
    for role, label in Member.ROLE_CHOICES:
        assert role in Member.ROLE_DESCRIPTIONS, f"{label} has no description"
        assert Member.ROLE_DESCRIPTIONS[role].strip(), f"{label}'s description is empty"


def test_the_pod_owner_role_grants_exactly_what_a_plain_member_gets(side: Yard) -> None:
    """`pod_owner` is a label, and the copy beside the control used to say otherwise.

    This test used to exercise only the sentence's NEGATIVE clause — "Cannot remove or
    re-role anyone" — which is why the two AFFIRMATIVE ones survived: the description
    promised "Sets their household's house rule and invites people into it", and both were
    refused in code. The module docstring sets a two-directional bar ("a description cannot
    promise something the code refuses, **or deny something the code allows**"); the
    yard_admin test below meets it on all three of its claims and this one did not.

    The general form: exercise every clause a sentence makes, not the convenient one.
    """
    owner = _member(side, Member.POD_OWNER, name="Pod Owner")
    plain = _member(side, Member.MEMBER, name="Neighbour")
    household = owner.pods.get()

    # Every predicate that takes a member, asked of both. Any divergence means the role
    # has quietly grown a capability and the description needs to say so.
    assert permissions.is_admin(owner) == permissions.is_admin(plain) is False
    assert permissions.is_instance_admin(owner) == permissions.is_instance_admin(plain) is False
    assert permissions.can_manage_member(owner, plain) == permissions.can_manage_member(
        plain, owner
    )
    assert permissions.can_issue_invite(owner, household) == permissions.can_issue_invite(
        plain, household
    ), "pod_owner was granted invites; the ladder in permission-matrix.md says it is not"

    # The two affirmative promises the old description made, exercised directly.
    assert not permissions.can_issue_invite(owner, household), (
        "the roster once told a delegate this role 'invites people into it'"
    )
    with pytest.raises(pods.PodActionNotAllowed):
        pods.set_house_rule(actor=owner, pod=household, house_rule="be kind")

    # And the description must not have grown the claim back.
    text = Member.ROLE_DESCRIPTIONS[Member.POD_OWNER]
    for false_promise in ("house rule and invites", "invites people into it"):
        assert false_promise not in text, (
            f"the pod_owner description promises {false_promise!r}, which the code refuses"
        )


def test_the_roster_no_longer_offers_a_role_that_does_nothing(side: Yard) -> None:
    """An admin should not be able to appoint someone to a role with no effect.

    `pod_owner` was in `_ASSIGNABLE_ROLES`, so the roster offered it — with a description
    claiming two powers it does not confer — while `docs/retro/2026-07-22-phase-2-retro.md`
    had already ruled "Activate `pod_owner`? **No.**"
    """
    from core.admin_views import _ASSIGNABLE_ROLES

    assert Member.POD_OWNER not in _ASSIGNABLE_ROLES
    # Denominator: the list still offers the roles that DO something, so the absence above
    # is a deliberate removal rather than the constant having been emptied.
    assert {Member.MEMBER, Member.YARD_ADMIN, Member.INSTANCE_ADMIN} <= set(_ASSIGNABLE_ROLES)


def test_the_yard_admin_description_is_true_on_all_three_of_its_claims(side: Yard) -> None:
    """The longest promise on the page, so the one most worth exercising: manages
    members on their own side, cannot touch an admin, cannot touch a bridging member."""
    other = Yard.objects.create(name="Paternal", slug="paternal")
    admin = _member(side, Member.YARD_ADMIN, name="Yard Admin")
    same_side = _member(side, Member.MEMBER, name="Same Side")
    an_admin = _member(side, Member.INSTANCE_ADMIN, name="Instance Admin")

    bridge = Pod.objects.create(name="The bridging household")
    bridge.yards.set([side, other])
    bridger = Member.objects.create(display_name="Bridger", role=Member.MEMBER)
    PodMembership.objects.create(member=bridger, pod=bridge)

    text = Member.ROLE_DESCRIPTIONS[Member.YARD_ADMIN]
    assert "only on their own side of the family" in text
    assert permissions.can_manage_member(admin, same_side), "cannot manage their own side"
    assert "Cannot touch an admin" in text
    assert not permissions.can_manage_member(admin, an_admin), "privilege inversion"
    assert "belongs to the other side" in text
    assert not permissions.can_manage_member(admin, bridger), "reached a bridging member"


def test_the_instance_admin_description_is_true_they_reach_everyone(side: Yard) -> None:
    other = Yard.objects.create(name="Paternal", slug="paternal")
    boss = _member(side, Member.INSTANCE_ADMIN, name="Instance Admin")
    far_pod = Pod.objects.create(name="Far household")
    far_pod.yards.set([other])
    far = Member.objects.create(display_name="Far Cousin", role=Member.MEMBER)
    PodMembership.objects.create(member=far, pod=far_pod)

    assert "Manages anyone, on either side" in Member.ROLE_DESCRIPTIONS[Member.INSTANCE_ADMIN]
    assert permissions.can_manage_member(boss, far)
    a_yard_admin = _member(side, Member.YARD_ADMIN, name="A Yard Admin")
    assert permissions.can_manage_member(boss, a_yard_admin)


def test_no_description_claims_self_administration(side: Yard) -> None:
    """Nobody removes or re-roles themselves, at any role. A description that implied
    otherwise would be the one mistake a reader could not discover without trying it."""
    for role in (Member.POD_OWNER, Member.YARD_ADMIN, Member.INSTANCE_ADMIN):
        actor = _member(side, role, name=f"Self {role}")
        assert not permissions.can_manage_member(actor, actor), f"{role} manages themselves"


def test_the_descriptions_and_the_permission_matrix_have_not_drifted() -> None:
    """The second binding direction. The matrix is the human reference S-701 requires;
    if someone rewrites a rule there, the UI copy that paraphrases it must be revisited.
    Anchored on the RULE each sentence paraphrases, not on shared wording."""
    # Collapse whitespace first: the matrix hard-wraps at ~80 columns, so
    # "does not remove or\n  re-role anyone" is one sentence to a reader and two
    # lines to a substring search. Anchoring on the raw text would make this guard
    # fail on a reflow and pass on a rewrite, which is exactly backwards.
    matrix = " ".join(_MATRIX.read_text().split())
    for phrase in (
        # pod_owner. Anchored on what the role IS rather than on the one thing it is
        # not: the old anchor ("does not remove or re-role anyone") was the sentence's
        # negative clause, so the matrix and the UI copy could both promise a house rule
        # and invites — which neither the code nor reality granted — and stay green.
        "grants nothing",
        "pod.owner",
        "only within their own yards",  # yard_admin, own side
        "no privilege inversion",  # yard_admin, cannot touch an admin
        "requires the instance admin",  # yard_admin, cannot touch a bridging member
        "manages anyone",  # instance_admin
        "no independent login",  # supervised
    ):
        assert phrase.lower() in matrix.lower(), (
            f"the permission matrix no longer states {phrase!r}; the roster's role key "
            "paraphrases it and must be revisited"
        )


def test_the_roster_actually_renders_the_key() -> None:
    """Guard the guard: everything above would still pass if the template never showed
    the descriptions. Render the page and look for them."""
    from django.template.loader import render_to_string
    from django.utils.html import escape

    html = render_to_string(
        "core/members.html",
        {
            "rows": [],
            "can_create_yard": False,
            "role_meanings": [
                (label, Member.ROLE_DESCRIPTIONS[role])
                for role, label in Member.ROLE_CHOICES
                if role != Member.SUPERVISED
            ],
        },
    )
    assert "What the roles mean" in html
    for role in (Member.POD_OWNER, Member.YARD_ADMIN, Member.INSTANCE_ADMIN):
        # escape(), because the descriptions contain apostrophes and the template
        # autoescapes them — comparing raw text would fail on correct output.
        assert escape(Member.ROLE_DESCRIPTIONS[role]) in html, (
            f"{role}'s description is not on the page"
        )


def test_the_roster_renders_no_empty_disclosure_without_meanings() -> None:
    """Reviewer catch on #99. `members.html` is rendered without `role_meanings` by
    other tests, and an unguarded block produced a "What the roles mean" disclosure
    that opened onto nothing — a control promising an answer it does not have."""
    from django.template.loader import render_to_string

    html = render_to_string("core/members.html", {"rows": [], "can_create_yard": False})
    assert "What the roles mean" not in html, "an empty role key rendered"
    # The ELEMENT, not the bare class name: base.html's stylesheet ships
    # `details.role-key { ... }` on every page, so a substring check for "role-key"
    # matches the CSS and fails against correct output.
    assert '<details class="role-key">' not in html
