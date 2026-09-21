"""An invite can make its FIRST joiner the side admin (R2-6, T-INVITE-2).

The owner is about to hand each side of the family to one relative with the words "invite
people if you want". An invite carried no role, so that relative would have landed as an
ordinary member who cannot invite anybody — `can_issue_invite` refuses a plain member —
and nothing anywhere would have said so. They would have found out by tapping Members and
getting a 403, and the cure was the owner noticing and promoting them by hand.

This is a bearer link that confers AUTHORITY, which is a different object from an invite
that confers membership, so the tests here are about the four things that bound it:

  WHAT it can grant   the side-admin role and nothing else, capped in three places
  WHO can mint one    the family admin, and a hand-made POST from a side admin is refused
  WHO gets it         the first redeemer, decided under the row lock, and nobody after
  HOW it dies         revoke, expiry, the TM-1 removal sweep, and never re-armed

The reach the role actually carries is asserted at the end, against `permissions`: a side
admin minted this way is a side admin and not a quiet family admin.
"""

from __future__ import annotations

import re
import threading
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.http import HttpResponse
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import invites, permissions, removal
from core.models import Invite, Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_TEST_PW = "a-Strong-passphrase-9"


def _member(pod: Pod, name: str, role: str = Member.MEMBER) -> Member:
    user = User.objects.create_user(username=name.lower(), password=_TEST_PW)
    member = Member.objects.create(display_name=name, user=user, role=role)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _client_for(member: Member) -> Client:
    assert member.user is not None
    client = Client()
    client.force_login(member.user, backend=_BACKEND)
    return client


class World:
    """Two sides of the family, a family admin, and a side admin on the maternal one."""

    def __init__(self) -> None:
        self.maternal = Yard.objects.create(name="Maternal", slug="maternal")
        self.paternal = Yard.objects.create(name="Paternal", slug="paternal")
        self.m_pod = Pod.objects.create(name="Maternal seed", kind=Pod.HOUSEHOLD)
        self.m_pod.yards.set([self.maternal])
        self.p_pod = Pod.objects.create(name="Paternal seed", kind=Pod.HOUSEHOLD)
        self.p_pod.yards.set([self.paternal])
        self.family_admin = _member(self.m_pod, "Boss", role=Member.INSTANCE_ADMIN)
        self.side_admin = _member(self.m_pod, "MaternalMod", role=Member.YARD_ADMIN)
        self.plain = _member(self.m_pod, "Cousin")


@pytest.fixture
def world() -> World:
    return World()


def _intent(client: Client) -> str:
    body = client.get(reverse("invite_household")).content.decode()
    match = re.search(r'name="intent" value="([^"]+)"', body)
    assert match, "no intent nonce on the invite page"
    return match.group(1)


def _create(client: Client, *, name: str, yard_ids: list[int], grants: bool) -> HttpResponse:
    payload: dict[str, object] = {
        "household_name": name,
        "yard_ids": [str(value) for value in yard_ids],
        "intent": _intent(client),
    }
    if grants:
        payload["grants_side_admin"] = "1"
    response = client.post(reverse("invite_household"), payload)
    # The narrowing the rest of this file needs to read `.content`, done once here the
    # way test_invite_household.py already does it.
    assert isinstance(response, HttpResponse)
    return response


def _text(html: str) -> str:
    """Visible words, tags removed and whitespace flattened: the sentences below wrap
    across lines in the template and carry <strong> around the side names."""
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def _raw_token_from(body: str) -> str:
    match = re.search(r'value="(http[^"]*/join/[^"]+)"', body)
    assert match, "no /join link in the page"
    return match.group(1).split("/join/")[1].rstrip("/")


# --- WHAT a link may grant --------------------------------------------------------------


def test_the_service_refuses_to_mint_a_link_that_grants_the_family_admin_role(
    world: World,
) -> None:
    """The cap, at the layer every surface goes through.

    A link has no face on the other end of it: whoever is holding it is whoever is holding
    it. The family admin reaches every side of the family, so that role is granted by one
    named person to another on the roster, where there is somebody to hold responsible.
    """
    with pytest.raises(invites.RoleNotGrantableByLink):
        invites.mint_invite(world.m_pod, world.family_admin, grants_role=Member.INSTANCE_ADMIN)
    assert not Invite.objects.exists(), "it refused and minted a link anyway"

    # ...and the same for anything else a caller might pass, including a role that exists.
    for role in (Member.SUPERVISED, Member.POD_OWNER, "administrator"):
        with pytest.raises(invites.RoleNotGrantableByLink):
            invites.mint_invite(world.m_pod, world.family_admin, grants_role=role)
    assert not Invite.objects.exists()


def test_the_database_refuses_the_row_even_when_the_service_is_gone_round(
    world: World,
) -> None:
    """The layer a hand-written UPDATE at a database shell cannot get past.

    `Invite.objects.create` skips `mint_invite` entirely, which is exactly what a repair
    script or a future second minting surface would do by accident. The CHECK constraint
    is what makes the cap a property of the data rather than of the code that happens to
    be writing it.
    """
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Invite.objects.create(
                pod=world.m_pod,
                token_digest="a" * 64,
                expires_at=timezone.now() + timedelta(days=7),
                grants_role=Member.INSTANCE_ADMIN,
            )


def test_a_row_carrying_an_illegal_role_still_cannot_escalate_at_redeem_time() -> None:
    """The third cap, and the one that answers "what if the other two were bypassed".

    Written by going round both of them: the CHECK constraint is dropped and the column is
    written by hand, which is the shape of the tampering this is about — a repair script, a
    restore from a database that predates the constraint, somebody at a psql prompt. What
    must hold is that the person joining still comes out an ORDINARY member, because the
    redeem path applies only a role a link may grant.

    Postgres runs DDL inside the transaction, and pytest-django rolls this test's
    transaction back, so the constraint comes back on its own. The DROP is the FIRST
    statement on purpose: `ALTER TABLE` refuses once the transaction has pending foreign-key
    trigger events, which every row the fixture would have inserted leaves behind — so this
    test builds its own small world afterwards rather than taking `world`.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE core_invite DROP CONSTRAINT invite_grants_only_the_side_admin_role"
        )

    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Household", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    _, raw = invites.mint_invite(pod, None, grants_role=Member.YARD_ADMIN)
    with connection.cursor() as cursor:
        cursor.execute("UPDATE core_invite SET grants_role = %s", [Member.INSTANCE_ADMIN])

    joined = invites.redeem_invite(raw, display_name="A Newcomer", user_id=None)

    assert joined.role == Member.MEMBER, (
        "a hand-edited invite row minted a family admin, so the cap that has to survive a "
        "database shell is not doing its job"
    )


# --- WHO may mint one -------------------------------------------------------------------


def test_only_the_family_admin_is_offered_the_control(world: World) -> None:
    """A side admin's authority is over PEOPLE on their side, never over who else gets to
    administer it — a delegate who can mint delegates can rebuild the roster around the
    family admin."""
    assert permissions.can_mint_a_role_granting_invite(world.family_admin)
    assert not permissions.can_mint_a_role_granting_invite(world.side_admin)

    page = _client_for(world.family_admin).get(reverse("invite_household")).content.decode()
    assert 'name="grants_side_admin"' in page, "the family admin is not offered the control"

    page = _client_for(world.side_admin).get(reverse("invite_household")).content.decode()
    assert 'name="grants_side_admin"' not in page, "a side admin is offered the control"


def test_a_forged_post_from_a_side_admin_is_refused_rather_than_ignored(
    world: World,
) -> None:
    """403, not a quietly ordinary invite.

    Dropping the field would leave a side admin looking at a household they believe hands
    over their side and a link that does nothing of the kind — and it would teach nothing
    to whoever wrote the request. The only way to submit a control that is not on the
    screen is to have made the request by hand.
    """
    client = _client_for(world.side_admin)
    response = _create(client, name="The Davis family", yard_ids=[world.maternal.id], grants=True)

    assert response.status_code == 403, response.status_code
    assert not Invite.objects.filter(grants_role__isnull=False).exists()
    assert not Pod.objects.filter(name="The Davis family").exists(), (
        "the refusal still created the household, so a refused request left a mess behind"
    )


def test_a_plain_members_forged_post_never_reaches_the_question(world: World) -> None:
    """The surface is admin-only before any of this: a plain member is refused at the door,
    which is where they were already refused."""
    client = _client_for(world.plain)
    assert client.get(reverse("invite_household")).status_code == 403
    response = client.post(
        reverse("invite_household"),
        {
            "household_name": "The Davis family",
            "yard_ids": [str(world.maternal.id)],
            "intent": "anything",
            "grants_side_admin": "1",
        },
    )
    assert response.status_code == 403
    assert not Invite.objects.exists()


def test_the_family_admin_mints_one_and_the_page_says_what_it_does(world: World) -> None:
    response = _create(
        _client_for(world.family_admin),
        name="The Davis family",
        yard_ids=[world.maternal.id],
        grants=True,
    )
    body = _text(response.content.decode())

    invite = Invite.objects.get(pod__name="The Davis family")
    assert invite.grants_role == Member.YARD_ADMIN
    # The side name is wrapped in <strong>, so the sentence is asserted up to it and the
    # rest on its own rather than with a tag-stripper's stray space inside the assertion.
    assert "becomes an Admin for Maternal" in body, body[-1200:]
    assert "Everyone after them joins as a member." in body


def test_not_ticking_it_mints_an_ordinary_invite(world: World) -> None:
    """The default, and it is the right way round: an unticked checkbox sends nothing, so
    the link that grants no authority is what you get by not thinking about it."""
    _create(
        _client_for(world.family_admin),
        name="The Nolan family",
        yard_ids=[world.maternal.id],
        grants=False,
    )
    invite = Invite.objects.get(pod__name="The Nolan family")
    assert invite.grants_role is None


def test_a_household_on_both_sides_hands_over_both_and_says_so(world: World) -> None:
    """A bridging household is allowed, and it is the case where the tick means most: that
    relative then administers both sides, which is what `_target_within_actor_scope`
    already means for somebody whose own households span two. The page names both sides
    rather than saying "this side", because two ticked boxes are easy to make without
    noticing what the third one did."""
    response = _create(
        _client_for(world.family_admin),
        name="The bridging household",
        yard_ids=[world.maternal.id, world.paternal.id],
        grants=True,
    )
    body = _text(response.content.decode())
    assert "becomes an Admin for Maternal and Paternal" in body, body[-1200:]

    raw = _raw_token_from(response.content.decode())
    joined = invites.redeem_invite(raw, display_name="The Delegate", user_id=None)
    assert joined.role == Member.YARD_ADMIN


# --- WHO gets the role ------------------------------------------------------------------


def test_the_first_person_through_the_link_gets_it_and_nobody_after_them(
    world: World,
) -> None:
    invite, raw = invites.mint_invite(
        world.m_pod, world.family_admin, grants_role=Member.YARD_ADMIN
    )

    first = invites.redeem_invite(raw, display_name="The Delegate", user_id=None)
    second = invites.redeem_invite(raw, display_name="Their Partner", user_id=None)
    third = invites.redeem_invite(raw, display_name="Their Child", user_id=None)

    assert first.role == Member.YARD_ADMIN
    assert second.role == Member.MEMBER, "the second person through the link is also an admin"
    assert third.role == Member.MEMBER
    invite.refresh_from_db()
    assert invite.use_count == 3, "the rest of the household could not use the same link"


def test_two_phones_racing_cannot_both_become_the_side_admin() -> None:
    """The race, with real threads, on the same link.

    The decision is made inside the transaction that already holds the invite row FOR
    UPDATE, off the same `use_count` read the one-use cap uses — so one transaction sees 0
    and the other sees 1 whatever the interleaving. Deciding it in the view, after the
    member exists, would be the double-redeem race this service was written to close,
    wearing a different outcome: a household with two side admins and no record of which
    one was meant.
    """
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Household", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    _, raw = invites.mint_invite(pod, None, grants_role=Member.YARD_ADMIN)

    lock = threading.Lock()
    roles: list[str] = []

    def attempt(name: str) -> None:
        try:
            member = invites.redeem_invite(raw, display_name=name, user_id=None)
            role = member.role
        except invites.InviteInvalid:
            role = "invalid"
        finally:
            connection.close()
        with lock:
            roles.append(role)

    threads = [threading.Thread(target=attempt, args=(f"racer-{i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert roles.count(Member.YARD_ADMIN) == 1, f"both phones came out admins: {roles}"
    assert Member.objects.filter(role=Member.YARD_ADMIN).count() == 1


test_two_phones_racing_cannot_both_become_the_side_admin = pytest.mark.django_db(transaction=True)(
    test_two_phones_racing_cannot_both_become_the_side_admin
)


def test_the_role_they_get_is_a_side_admins_and_not_a_family_admins(world: World) -> None:
    """The reach, asserted against `permissions` rather than against the stored string.

    A side admin minted this way must be exactly a side admin: they administer people on
    their own side, they are refused on the other side (a byte-identical 404 through
    `administrable_members`, the S-202 parity), and they cannot themselves hand out the
    role they were given.
    """
    _, raw = invites.mint_invite(world.m_pod, world.family_admin, grants_role=Member.YARD_ADMIN)
    delegate = invites.redeem_invite(raw, display_name="The Delegate", user_id=None)

    assert permissions.is_admin(delegate)
    assert not permissions.is_instance_admin(delegate)
    assert permissions.can_manage_member(delegate, world.plain), (
        "they cannot manage anybody on their own side, so the grant did nothing useful"
    )

    across = _member(world.p_pod, "OtherSideCousin")
    assert not permissions.can_manage_member(delegate, across), (
        "a link minted for one side handed somebody the other side of the family"
    )
    assert not permissions.administrable_members(delegate).filter(pk=across.pk).exists()
    assert not permissions.can_mint_a_role_granting_invite(delegate), (
        "the delegate can mint delegates, so one link is now an unbounded supply of them"
    )


# --- HOW it dies ------------------------------------------------------------------------


def test_a_revoked_role_granting_link_grants_nothing(world: World) -> None:
    invite, raw = invites.mint_invite(
        world.m_pod, world.family_admin, grants_role=Member.YARD_ADMIN
    )
    Invite.objects.filter(pk=invite.pk).update(revoked_at=timezone.now())

    with pytest.raises(invites.InviteInvalid):
        invites.redeem_invite(raw, display_name="Too Late", user_id=None)
    assert not Member.objects.filter(display_name="Too Late").exists()


def test_an_expired_role_granting_link_grants_nothing(world: World) -> None:
    """Seven days, like every other invite: `DEFAULT_TTL_DAYS` is not special-cased for
    this one, and a link that hands out authority is the last one that should live longer
    than the rest."""
    invite, raw = invites.mint_invite(
        world.m_pod, world.family_admin, grants_role=Member.YARD_ADMIN
    )
    assert (invite.expires_at - timezone.now()).days == invites.DEFAULT_TTL_DAYS - 1
    Invite.objects.filter(pk=invite.pk).update(expires_at=timezone.now() - timedelta(days=1))

    with pytest.raises(invites.InviteInvalid):
        invites.redeem_invite(raw, display_name="Too Late", user_id=None)
    assert not Member.objects.filter(display_name="Too Late").exists()


def test_removing_its_creator_voids_it_like_any_other_invite(world: World) -> None:
    """The TM-1 sweep reads `created_by` and the pods an invite reaches; it knows nothing
    about roles, and it must not need to. Asserted here because a link that hands out
    authority is the one whose survival past its creator's removal would matter most."""
    minter = _member(world.m_pod, "Delegate", role=Member.INSTANCE_ADMIN)
    _, raw = invites.mint_invite(world.m_pod, minter, grants_role=Member.YARD_ADMIN)

    removal.remove_member(minter, content=removal.KEEP)

    with pytest.raises(invites.InviteInvalid):
        invites.redeem_invite(raw, display_name="Too Late", user_id=None)


def test_make_another_link_mints_an_ordinary_invite(world: World) -> None:
    """A spent grant is never re-armed, and "Make another link" is the control it would be
    re-armed BY: it is the cheap one, tapped whenever a household needs one more copy. A
    household could otherwise end up with two or three people who each joined "first"
    through a different link."""
    response = _create(
        _client_for(world.family_admin),
        name="The Davis family",
        yard_ids=[world.maternal.id],
        grants=True,
    )
    original = Invite.objects.get(pod__name="The Davis family")
    assert original.grants_role == Member.YARD_ADMIN
    assert response.status_code == 200

    _client_for(world.family_admin).post(reverse("resend_invite", args=[original.id]))

    fresh = Invite.objects.filter(pod=original.pod).exclude(pk=original.pk).get()
    assert fresh.grants_role is None, "re-handing the link re-armed the role grant"


# --- what the admin can SEE -------------------------------------------------------------


def test_the_invite_ledger_says_which_links_carry_it_and_whether_it_was_taken(
    world: World,
) -> None:
    """The ledger is the only place an admin can tell one handed-out link from another,
    and once somebody has taken the role the link is an ordinary invite for everybody
    after them — so revoking it takes nothing back from the person who already joined.
    Both states are said out loud for that reason."""
    response = _create(
        _client_for(world.family_admin),
        name="The Davis family",
        yard_ids=[world.maternal.id],
        grants=True,
    )
    raw = _raw_token_from(response.content.decode())

    ledger = _text(_client_for(world.family_admin).get(reverse("member_invites")).content.decode())
    assert "The first person to join with this link becomes an Admin." in ledger, ledger[:1500]

    invites.redeem_invite(raw, display_name="The Delegate", user_id=None)

    ledger = _text(_client_for(world.family_admin).get(reverse("member_invites")).content.decode())
    assert "The Delegate joined first and is an Admin." in ledger, ledger[:1500]


def test_an_ordinary_invite_says_nothing_about_a_role(world: World) -> None:
    """Non-vacuity for the line above: a ledger that printed it on every row would pass
    every assertion in this file and tell an admin nothing."""
    _create(
        _client_for(world.family_admin),
        name="The Nolan family",
        yard_ids=[world.maternal.id],
        grants=False,
    )
    ledger = _client_for(world.family_admin).get(reverse("member_invites")).content.decode()
    assert "becomes an Admin" not in ledger


def test_the_welcomes_last_screen_points_a_new_admin_at_their_job(world: World) -> None:
    """Somebody who joined through one of these links IS an admin by the time they reach
    the end of the welcome, and the three screens are written for a relative arriving at a
    family's page. One line, pointing at the two places that answer "what now"."""
    _, raw = invites.mint_invite(world.m_pod, world.family_admin, grants_role=Member.YARD_ADMIN)
    user = User.objects.create_user(username="delegate", password=_TEST_PW)
    delegate = invites.redeem_invite(raw, display_name="The Delegate", user_id=user.id)
    assert delegate.role == Member.YARD_ADMIN

    client = Client()
    client.force_login(user, backend=_BACKEND)
    html = client.get(reverse("welcome_hello")).content.decode()

    line = "You are an Admin. You can add and remove members."
    assert line in _text(html), _text(html)[:1200]
    # The two destinations, asserted on the raw markup: a pointer with no route is a
    # sentence, and the point of the line is that it is one tap from where they landed.
    assert f'href="{reverse("members")}"' in html
    assert f'href="{reverse("admins_day_one")}"' in html


def test_an_ordinary_newcomer_is_not_shown_the_admin_line(world: World) -> None:
    """Non-vacuity, and the reason it is asked of the ROLE rather than of the invite: a
    line shown to everybody would send a relative who has just joined to a page that 403s
    on them."""
    _, raw = invites.mint_invite(world.m_pod, world.family_admin)
    user = User.objects.create_user(username="cousinjo", password=_TEST_PW)
    invites.redeem_invite(raw, display_name="Cousin Jo", user_id=user.id)

    client = Client()
    client.force_login(user, backend=_BACKEND)
    body = client.get(reverse("welcome_hello")).content.decode()

    assert "You are an Admin" not in body


# --- the form survives its own errors ---------------------------------------------------


def test_a_validation_error_keeps_the_role_grant_ticked(world: World) -> None:
    """The defect R2-6 exists to cure, reintroduced by a blank checkbox.

    The form re-rendered with the box empty after a validation error, so an admin who
    ticked it, got "Enter a household name.", fixed the name and submitted again handed
    over an ORDINARY link that appoints nobody — and nothing on any screen would say so
    until the relative arrived as a plain member. What they typed and ticked comes back.
    """
    client = _client_for(world.family_admin)
    response = client.post(
        reverse("invite_household"),
        {
            "household_name": "   ",  # refused: no name
            "yard_ids": [str(world.maternal.id), str(world.paternal.id)],
            "grants_side_admin": "1",
            "intent": _intent(client),
        },
    )
    body = response.content.decode()

    assert "Enter a household name." in body
    assert not Invite.objects.exists(), "it created a household despite refusing"
    ticked = body[
        body.index('name="grants_side_admin"') : body.index('name="grants_side_admin"') + 120
    ]
    assert "checked" in ticked, f"the tick was dropped on the error path: {ticked}"
    # ...and the sides they picked come back too, so the resubmission is one keystroke.
    for yard in (world.maternal, world.paternal):
        box = body[body.index(f'name="yard_ids" value="{yard.id}"') :][:120]
        assert "checked" in box, f"the side {yard.name} lost its tick: {box}"


def test_an_unticked_box_stays_unticked_after_an_error(world: World) -> None:
    """Non-vacuity: a template that printed `checked` unconditionally would pass the test
    above and silently arm every retried invite."""
    client = _client_for(world.family_admin)
    response = client.post(
        reverse("invite_household"),
        {
            "household_name": "",
            "yard_ids": [str(world.maternal.id)],
            "intent": _intent(client),
        },
    )
    body = response.content.decode()
    ticked = body[
        body.index('name="grants_side_admin"') : body.index('name="grants_side_admin"') + 120
    ]
    assert "checked" not in ticked, f"an untouched box came back ticked: {ticked}"


def test_the_string_zero_is_not_a_tick(world: World) -> None:
    """`bool("0")` is True, so the first version read the value a hand-made request or a
    scripted caller is most likely to send for "no" as a yes. The checkbox sends "1" and
    nothing at all, so the comparison is to "1"."""
    _create_raw = _client_for(world.family_admin)
    response = _create_raw.post(
        reverse("invite_household"),
        {
            "household_name": "The Nolan family",
            "yard_ids": [str(world.maternal.id)],
            "grants_side_admin": "0",
            "intent": _intent(_create_raw),
        },
    )
    assert response.status_code == 200
    assert Invite.objects.get(pod__name="The Nolan family").grants_role is None


# --- the ledger tells the truth about a dead link ----------------------------------------


@pytest.mark.parametrize("kill", ["revoked", "expired"])
def test_a_dead_link_nobody_used_says_it_handed_out_nothing(world: World, kill: str) -> None:
    """It said "The first person to join with this link becomes the side admin" directly
    under "This link no longer works" — a promise in the present tense about a link that
    cannot keep it, on the page an admin reads to work out whether the side has actually
    been handed over."""
    invite, _raw = invites.mint_invite(
        world.m_pod, world.family_admin, grants_role=Member.YARD_ADMIN
    )
    if kill == "revoked":
        Invite.objects.filter(pk=invite.pk).update(revoked_at=timezone.now())
    else:
        Invite.objects.filter(pk=invite.pk).update(expires_at=timezone.now() - timedelta(days=1))

    ledger = _text(_client_for(world.family_admin).get(reverse("member_invites")).content.decode())

    dead = "This link no longer works, and nobody used it, so nobody became an Admin."
    assert dead in ledger, ledger
    assert "The first person to join with this link becomes an Admin." not in ledger


def test_a_dead_link_whose_role_was_taken_still_names_who_took_it(world: World) -> None:
    """Revoking takes nothing back from the person who already joined, and that is the fact
    an admin most needs off this page."""
    invite, raw = invites.mint_invite(
        world.m_pod, world.family_admin, grants_role=Member.YARD_ADMIN
    )
    invites.redeem_invite(raw, display_name="The Delegate", user_id=None)
    Invite.objects.filter(pk=invite.pk).update(revoked_at=timezone.now())

    ledger = _text(_client_for(world.family_admin).get(reverse("member_invites")).content.decode())

    assert "The Delegate joined first and is an Admin." in ledger, ledger
    assert "nobody became an Admin" not in ledger


def test_a_live_link_still_says_what_it_will_do(world: World) -> None:
    """The third state, so the branch above cannot swallow the live one."""
    invites.mint_invite(world.m_pod, world.family_admin, grants_role=Member.YARD_ADMIN)
    ledger = _text(_client_for(world.family_admin).get(reverse("member_invites")).content.decode())
    assert "The first person to join with this link becomes an Admin." in ledger
    assert "nobody became an Admin" not in ledger


# --- the welcome line is true of whoever reads it -----------------------------------------


def test_the_family_admin_is_not_told_they_look_after_one_side(world: World) -> None:
    """The line said "You look after a side of the family" to whoever was an admin, which
    is the one thing the family admin's role is not: they reach every side. Only a
    role-granting link puts a side admin on this screen, but the founder and anybody
    promoted can open the welcome again. (The copy pass of 2026-09-19 also stopped the line
    using an idiom for a capability: it names the role and says what the role can do.)"""
    assert world.family_admin.user is not None
    client = Client()
    client.force_login(world.family_admin.user, backend=_BACKEND)
    body = _text(client.get(reverse("welcome_hello")).content.decode())

    line = "You are a Family Admin. You can add and remove members on both sides."
    assert line in body, body[:1200]
    assert "You are an Admin" not in body


def test_an_admin_is_told_what_their_role_lets_them_do(world: World) -> None:
    """Named for the line rather than for a side: "on your side" went on 2026-09-20,
    because an admin whose household belongs to both sides reaches both."""
    assert world.side_admin.user is not None
    client = Client()
    client.force_login(world.side_admin.user, backend=_BACKEND)
    body = _text(client.get(reverse("welcome_hello")).content.decode())

    line = "You are an Admin. You can add and remove members."
    assert line in body, body[:1200]
    assert "You are a Family Admin" not in body
