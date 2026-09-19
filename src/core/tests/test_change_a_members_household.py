"""Putting somebody who already has an account into a household — and taking them out.

The gap this covers, measured on production: redeeming an invite MINTS A NEW MEMBER
(`invites.redeem_invite`), and `pods.add_member_to_pod` refuses a household outright
("Members join a household pod by invite, not here"). So there was no route at all for
"this person already has an account and belongs in that household": not for the founder
placing somebody on a side he has just created, and not for the two relatives about to hold
`yard_admin` on the day somebody joined the wrong household, an adult child moved out, or
two households merged. The only existing route was `scripts/demo_seed.py` piped into a
shell, which also re-seeds fixture data.

Adding somebody to a household in a side they were not in HANDS THEM THAT SIDE'S FEED,
directory and photographs, so these tests lead with the refusals: a yard admin reaching
across the boundary (add, create, remove), a plain member, self-administration, an admin as
the target, stranding somebody in no household at all, the byte-identical 404, CSRF, and a
GET that must never change anything. The positives at the end are measured THROUGH THE REAL
VIEWS — the feed, the directory, a post's own page — because "the membership row exists" is
not the promise; "they can now read that side of the family" is.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import posting, supervised
from core.models import (
    DigestSubscription,
    HouseholdChange,
    Invite,
    Member,
    Pod,
    PodMembership,
    Yard,
)

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
# The nonce is read the way a browser gets it — out of the confirm page's own hidden field —
# so a test cannot accidentally skip the confirm step the whole design rests on.
_INTENT = re.compile(r'name="intent" value="([^"]+)"')


def _member(pod: Pod | None, name: str, role: str = Member.MEMBER) -> Member:
    """A member with a login, optionally already in a household."""
    user = User.objects.create_user(username=name.lower().replace(" ", "-"))
    member = Member.objects.create(display_name=name, role=role, user=user)
    if pod is not None:
        PodMembership.objects.create(member=member, pod=pod)
    return member


@pytest.fixture
def world() -> dict[str, Member | Pod | Yard]:
    """Two sides, three households, and one member who bridges both.

    The bridging member is the shape T-AUTH-G2 is about: a yard-A admin can SEE them (they
    share yard A) and must never gain a lever over yard B through them.
    """
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    first = Pod.objects.create(name="The first household")
    first.yards.set([maternal])
    second = Pod.objects.create(name="The second household")
    second.yards.set([maternal])
    far = Pod.objects.create(name="A household on the other side")
    far.yards.set([paternal])

    bridging = _member(first, "Bridging Person")
    PodMembership.objects.create(member=bridging, pod=far)
    return {
        "maternal": maternal,
        "paternal": paternal,
        "first": first,
        "second": second,
        "far": far,
        "owner": _member(first, "The Owner", Member.INSTANCE_ADMIN),
        "side_admin": _member(first, "Side Admin", Member.YARD_ADMIN),
        "peer_admin": _member(second, "Peer Admin", Member.YARD_ADMIN),
        "cousin": _member(first, "A Cousin"),
        "far_cousin": _member(far, "A Far Cousin"),
        "bridging": bridging,
    }


def _who(world: dict[str, Member | Pod | Yard], key: str) -> Member:
    value = world[key]
    assert isinstance(value, Member)
    return value


def _pod(world: dict[str, Member | Pod | Yard], key: str) -> Pod:
    value = world[key]
    assert isinstance(value, Pod)
    return value


def _yard(world: dict[str, Member | Pod | Yard], key: str) -> Yard:
    value = world[key]
    assert isinstance(value, Yard)
    return value


def _client_for(member: Member) -> Client:
    assert member.user is not None
    client = Client()
    client.force_login(member.user, backend=_BACKEND)
    return client


def _url(target: Member) -> str:
    return reverse("change_household", args=[target.id])


def _propose(client: Client, target: Member, **data: object) -> HttpResponse:
    """The first POST. It may only ever render — never act."""
    response = client.post(_url(target), data)
    assert isinstance(response, HttpResponse)
    return response


def _carry_out(client: Client, target: Member, **data: object) -> HttpResponse:
    """Both steps, the way a person does them: propose, then submit the confirm page."""
    first = client.post(_url(target), data)
    assert first.status_code == 200, first.status_code
    match = _INTENT.search(first.content.decode())
    assert match is not None, "the confirm step rendered no form to submit"
    response = client.post(_url(target), {**data, "intent": match.group(1)})
    assert isinstance(response, HttpResponse)
    return response


def _households(member: Member) -> set[int]:
    return set(member.pods.filter(kind=Pod.HOUSEHOLD).values_list("id", flat=True))


def _without_per_response_noise(body: bytes) -> bytes:
    """The rendered page minus the one thing that legitimately differs between two renders
    of the SAME page: the CSP script nonce, which is fresh per response. Measured — it is
    the only difference between the two 404s below, and comparing raw bytes would make this
    test fail for a reason that carries no information about anybody's existence."""
    return re.sub(rb'nonce="[^"]*"', b'nonce=""', body)


def _block(body: str, css_class: str) -> str:
    """One named list out of the rendered confirm page, so an assertion about what the page
    says a member LOSES cannot be satisfied by the same word appearing elsewhere."""
    match = re.search(rf'<ul class="{css_class}">(.*?)</ul>', body, re.S)
    return match.group(1) if match else ""


# --------------------------------------------------------------------------------------
# The refusals.
# --------------------------------------------------------------------------------------


def test_a_yard_admin_cannot_add_someone_to_a_household_on_the_other_side(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """The whole isolation promise in one request: yard A's delegate must not be able to
    hand one of their own members a seat in yard B's living room."""
    cousin, far = _who(world, "cousin"), _pod(world, "far")

    response = _propose(_client_for(_who(world, "side_admin")), cousin, act="add", pod_id=far.id)

    assert response.status_code == 404, response.status_code
    assert not PodMembership.objects.filter(member=cousin, pod=far).exists()


def test_a_yard_admin_cannot_make_a_household_on_a_side_they_do_not_administer(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """The same boundary by the other route: creating the household rather than picking it.

    A refusal on `add` alone would be a control that moves one door over — the create form
    takes side ids straight from a POST.
    """
    response = _propose(
        _client_for(_who(world, "side_admin")),
        _who(world, "cousin"),
        act="create",
        household_name="A household I should not be able to make",
        yard_ids=[_yard(world, "paternal").id],
    )

    assert response.status_code == 404, response.status_code
    assert not Pod.objects.filter(name="A household I should not be able to make").exists()


def test_a_yard_admin_cannot_take_someone_out_of_a_household_on_the_other_side(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """Removal is a lever too: a yard-A admin who could cut a bridging member out of yard B
    would be administering yard B. `can_manage_member` refuses a bridging target outright
    (T-AUTH-G2), and it is a 403 rather than a 404 because the actor can already see this
    person in their own yard — their existence is not the secret."""
    bridging, far = _who(world, "bridging"), _pod(world, "far")

    response = _propose(
        _client_for(_who(world, "side_admin")), bridging, act="remove", pod_id=far.id
    )

    assert response.status_code == 403, response.status_code
    assert PodMembership.objects.filter(member=bridging, pod=far).exists()


def test_a_plain_member_cannot_open_the_page_or_act_through_it(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """Nobody below an admin. A plain member sharing the household is the likeliest hand on
    this URL, and they may not move anybody — including the person sitting next to them."""
    owner, second = _who(world, "owner"), _pod(world, "second")
    client = _client_for(_who(world, "cousin"))

    assert client.get(_url(owner)).status_code == 403
    assert _propose(client, owner, act="add", pod_id=second.id).status_code == 403
    assert not PodMembership.objects.filter(member=owner, pod=second).exists()


@pytest.mark.parametrize("who", ["owner", "side_admin"])
def test_nobody_changes_their_own_household(
    world: dict[str, Member | Pod | Yard], who: str
) -> None:
    """No self-administration, for either admin role (`permissions.can_manage_member`).

    This is the one refusal that costs something real: on a single-admin instance the
    founder cannot place HIMSELF on a side he has just created, and the cure is the
    succession path — appoint a second instance admin, who can. The alternative is a
    surface where one person hands themselves a seat in the other side of the family's
    private feed with one tap and no second party, which is the thing yard isolation is for.
    """
    actor, second = _who(world, who), _pod(world, "second")
    client = _client_for(actor)

    assert client.get(_url(actor)).status_code == 403
    assert _propose(client, actor, act="add", pod_id=second.id).status_code == 403
    assert not PodMembership.objects.filter(member=actor, pod=second).exists()


def test_a_yard_admin_cannot_change_another_admins_household(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """No privilege inversion: below the instance admin, nobody administers an admin."""
    peer, second = _who(world, "peer_admin"), _pod(world, "second")

    response = _propose(
        _client_for(_who(world, "side_admin")), peer, act="remove", pod_id=second.id
    )

    assert response.status_code == 403, response.status_code
    assert PodMembership.objects.filter(member=peer, pod=second).exists()


def test_taking_someone_out_of_their_last_household_is_refused(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """A member in no household belongs to no side, and `scoping` then resolves nobody for
    them — including themselves. No feed, no directory, no way back short of a shell. The
    demo wipe already refuses to strand anyone (`demo_data._refuse_if_it_strands_anyone`);
    this surface must not do by one tap what that guard exists to prevent."""
    cousin, first = _who(world, "cousin"), _pod(world, "first")

    # Refused at the FIRST submit: nobody is shown a confirm page for an act that is then
    # turned down, and the page they are already looking at says why.
    response = _propose(_client_for(_who(world, "owner")), cousin, act="remove", pod_id=first.id)

    assert response.status_code == 200, response.status_code
    assert "only household" in response.content.decode()
    assert PodMembership.objects.filter(member=cousin, pod=first).exists()
    assert not HouseholdChange.objects.exists()


def test_a_target_on_the_other_side_is_byte_identical_to_one_who_does_not_exist(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """S-202 parity. "No such person" and "not yours to administer" must not be
    distinguishable, or the page becomes an oracle for who exists on the other side."""
    client = _client_for(_who(world, "side_admin"))
    last = Member.objects.order_by("-id").first()
    assert last is not None

    across = client.get(_url(_who(world, "far_cousin")))
    nobody = client.get(reverse("change_household", args=[last.id + 1000]))

    assert across.status_code == nobody.status_code == 404
    assert _without_per_response_noise(across.content) == _without_per_response_noise(
        nobody.content
    )


def test_a_post_without_a_csrf_token_changes_nothing(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """The act is a state change, so it is refused without a token — with the successful
    token-carrying submit as the denominator, so this cannot pass by the act being broken."""
    owner, cousin, second = _who(world, "owner"), _who(world, "cousin"), _pod(world, "second")
    assert owner.user is not None
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(owner.user, backend=_BACKEND)

    refused = strict.post(_url(cousin), {"act": "add", "pod_id": second.id})

    assert refused.status_code == 403, refused.status_code
    assert not PodMembership.objects.filter(member=cousin, pod=second).exists()
    # Denominator: the same act, through a client that sends the token, does work.
    assert _carry_out(_client_for(owner), cousin, act="add", pod_id=second.id).status_code == 302
    assert PodMembership.objects.filter(member=cousin, pod=second).exists()


def test_a_get_never_changes_anything(world: dict[str, Member | Pod | Yard]) -> None:
    """Loading the page — or hand-building the act as a query string — must not act. A
    browser prefetch, a link preview or a back button must never move somebody between
    sides of a family."""
    cousin, first, second = _who(world, "cousin"), _pod(world, "first"), _pod(world, "second")
    client = _client_for(_who(world, "owner"))

    page = client.get(_url(cousin), {"act": "add", "pod_id": str(second.id), "intent": "anything"})

    assert page.status_code == 200
    assert _households(cousin) == {first.id}
    assert not HouseholdChange.objects.exists()


def test_an_unknown_act_is_refused(world: dict[str, Member | Pod | Yard]) -> None:
    """A POST naming no recognised act is an unknown request, not a server error, and must
    never fall through to a default that does something."""
    cousin, first, second = _who(world, "cousin"), _pod(world, "first"), _pod(world, "second")

    response = _propose(
        _client_for(_who(world, "owner")), cousin, act="something-else", pod_id=second.id
    )

    assert response.status_code == 404, response.status_code
    assert _households(cousin) == {first.id}


def test_a_household_is_never_confused_with_an_ad_hoc_group(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """This page moves people between HOUSEHOLDS. An ad-hoc group ("just us cousins") is a
    member's own to create and leave (S-204/S-205), and admin authority over one would be a
    new power over a private group — so it is neither offered nor accepted."""
    cousin = _who(world, "cousin")
    adhoc = Pod.objects.create(name="Just us cousins", kind=Pod.ADHOC, owner=cousin)
    adhoc.yards.set([_yard(world, "maternal")])

    response = _propose(_client_for(_who(world, "owner")), cousin, act="add", pod_id=adhoc.id)

    assert response.status_code == 404, response.status_code
    assert not PodMembership.objects.filter(member=cousin, pod=adhoc).exists()


def test_a_supervised_child_follows_the_existing_custody_rule(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """TM-10: a supervised account is its managing parent's, or the instance admin's. A yard
    admin who is NOT the parent has no say, even inside their own side."""
    cousin, first, second = _who(world, "cousin"), _pod(world, "first"), _pod(world, "second")
    child = supervised.create_supervised_member(parent=cousin, display_name="A Child", pod=first)

    response = _propose(_client_for(_who(world, "side_admin")), child, act="add", pod_id=second.id)

    assert response.status_code == 403, response.status_code
    assert not PodMembership.objects.filter(member=child, pod=second).exists()


def test_adding_somebody_to_a_household_they_are_already_in_is_refused(
    world: dict[str, Member | Pod | Yard],
) -> None:
    cousin, first = _who(world, "cousin"), _pod(world, "first")

    # A stale page, or two admins working at once — a mistake to explain, not an attack to
    # stonewall, so it earns the sentence rather than the 404 an out-of-reach household gets.
    response = _propose(_client_for(_who(world, "owner")), cousin, act="add", pod_id=first.id)

    assert response.status_code == 200, response.status_code
    assert "already in" in response.content.decode()
    assert PodMembership.objects.filter(member=cousin, pod=first).count() == 1


def test_a_new_household_needs_a_name_and_at_least_one_side(
    world: dict[str, Member | Pod | Yard],
) -> None:
    cousin = _who(world, "cousin")
    client = _client_for(_who(world, "owner"))

    nameless = _propose(
        client, cousin, act="create", household_name="", yard_ids=[_yard(world, "maternal").id]
    )
    sideless = _propose(client, cousin, act="create", household_name="Nowhere", yard_ids=[])

    assert nameless.status_code == 200 and sideless.status_code == 200
    assert "Give the household a name." in nameless.content.decode()
    assert "Pick at least one side of the family." in sideless.content.decode()
    assert not Pod.objects.filter(name="Nowhere").exists()
    assert _households(cousin) == {_pod(world, "first").id}


def test_leaving_one_of_two_households_on_the_same_side_loses_nothing(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """The confirm page must not tell somebody they are losing a side they keep.

    The obvious query for "which sides do they keep" — filter the member's sides, exclude
    this pod — reads correctly and is not: `exclude` on a multi-valued relation drops EVERY
    side this pod belongs to, so a person in two households on one side would be warned
    they were about to lose it, and an admin who believed the page would leave them where
    they were.
    """
    cousin, first, second = _who(world, "cousin"), _pod(world, "first"), _pod(world, "second")
    PodMembership.objects.create(member=cousin, pod=second)  # both on the Maternal side

    body = _propose(
        _client_for(_who(world, "owner")), cousin, act="remove", pod_id=first.id
    ).content.decode()

    assert _block(body, "sides-lost") == ""
    assert "keeps them on the same sides of the family" in body


# --------------------------------------------------------------------------------------
# The confirm step, and what it has to say out loud.
# --------------------------------------------------------------------------------------


def test_the_first_submit_only_confirms_and_names_the_side_they_gain(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """One act per submit, and the confirm step states the consequence in plain words: this
    person will start seeing that side of the family. Nothing has happened yet."""
    cousin, far = _who(world, "cousin"), _pod(world, "far")

    response = _propose(_client_for(_who(world, "owner")), cousin, act="add", pod_id=far.id)
    body = response.content.decode()

    assert response.status_code == 200
    assert "Paternal" in _block(body, "sides-gained"), "the confirm step must NAME the side"
    assert not PodMembership.objects.filter(member=cousin, pod=far).exists()
    assert not HouseholdChange.objects.exists()


def test_the_confirm_step_names_only_the_side_they_stop_seeing(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """A bridging member taken out of the far household loses that side and keeps their own,
    so the page must say Paternal and must not say Maternal in the same breath."""
    bridging, far = _who(world, "bridging"), _pod(world, "far")

    body = _propose(
        _client_for(_who(world, "owner")), bridging, act="remove", pod_id=far.id
    ).content.decode()
    lost = _block(body, "sides-lost")

    assert "Paternal" in lost
    assert "Maternal" not in lost


def test_the_page_says_what_a_removal_costs_beyond_the_feed(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """The confirm step has to state the credential consequences too, because they are not
    guessable: the person is signed out everywhere, their weekly email stops, and
    invitations into that side that nobody has used yet stop working."""
    bridging, far = _who(world, "bridging"), _pod(world, "far")

    body = _propose(
        _client_for(_who(world, "owner")), bridging, act="remove", pod_id=far.id
    ).content.decode()

    assert "signed out" in body
    assert "weekly email" in body
    assert "invitation" in body


def test_a_second_submit_of_a_spent_confirmation_does_not_act_twice(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """A browser refresh replays the confirm POST. The single-use nonce (`handover`) means
    the replay lands back on the confirm page instead of adding a second record."""
    cousin, second = _who(world, "cousin"), _pod(world, "second")
    client = _client_for(_who(world, "owner"))
    url = _url(cousin)
    first = client.post(url, {"act": "add", "pod_id": second.id})
    match = _INTENT.search(first.content.decode())
    assert match is not None
    payload = {"act": "add", "pod_id": second.id, "intent": match.group(1)}

    assert client.post(url, payload).status_code == 302
    replay = client.post(url, payload)

    assert replay.status_code == 200, "a replayed confirmation must not act again"
    assert HouseholdChange.objects.filter(member=cousin, pod=second).count() == 1


# --------------------------------------------------------------------------------------
# What it does when it is allowed: proven through the real views.
# --------------------------------------------------------------------------------------


def test_after_an_add_they_really_do_see_the_new_sides_posts(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """Not `PodMembership.objects.filter(...).exists()` — the promise is what they can READ,
    so this walks the feed, a post's own page and the directory as the member."""
    cousin, far, far_cousin = _who(world, "cousin"), _pod(world, "far"), _who(world, "far_cousin")
    post = posting.create_post(
        author=far_cousin,
        pod=far,
        audience_yards=[_yard(world, "paternal")],
        body="Supper at ours on Sunday",
    )
    assert "Supper at ours" not in _client_for(cousin).get(reverse("feed")).content.decode()

    moved = _carry_out(_client_for(_who(world, "owner")), cousin, act="add", pod_id=far.id)

    assert moved.status_code == 302, moved.status_code
    after = _client_for(cousin)
    assert "Supper at ours on Sunday" in after.get(reverse("feed")).content.decode()
    assert after.get(reverse("post_detail", args=[post.id])).status_code == 200
    assert after.get(reverse("member_profile", args=[far_cousin.id])).status_code == 200


def test_after_a_remove_they_really_do_not_see_that_sides_posts(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """The mirror, and the more important half: afterwards the far side's posts, the far
    side's people and the far side's photographs are gone from every surface."""
    bridging, far, far_cousin = (
        _who(world, "bridging"),
        _pod(world, "far"),
        _who(world, "far_cousin"),
    )
    post = posting.create_post(
        author=far_cousin,
        pod=far,
        audience_yards=[_yard(world, "paternal")],
        body="Supper at ours on Sunday",
    )
    assert "Supper at ours" in _client_for(bridging).get(reverse("feed")).content.decode()

    moved = _carry_out(_client_for(_who(world, "owner")), bridging, act="remove", pod_id=far.id)

    assert moved.status_code == 302, moved.status_code
    after = _client_for(bridging)  # a fresh sign-in: the act revoked the old session
    assert "Supper at ours" not in after.get(reverse("feed")).content.decode()
    assert after.get(reverse("post_detail", args=[post.id])).status_code == 404
    assert after.get(reverse("member_profile", args=[far_cousin.id])).status_code == 404


def test_the_owner_can_put_an_existing_member_into_a_brand_new_household(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """The case the whole work item exists for: somebody who already has an account, placed
    into a household that does not exist yet, on a side the instance admin names."""
    cousin, paternal = _who(world, "cousin"), _yard(world, "paternal")

    response = _carry_out(
        _client_for(_who(world, "owner")),
        cousin,
        act="create",
        household_name="The cousins' new place",
        yard_ids=[paternal.id],
    )

    assert response.status_code == 302, response.status_code
    made = Pod.objects.get(name="The cousins' new place")
    assert made.kind == Pod.HOUSEHOLD
    assert set(made.yards.values_list("id", flat=True)) == {paternal.id}
    assert PodMembership.objects.filter(member=cousin, pod=made).exists()


def test_a_removal_revokes_the_credentials_that_reached_that_side(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """A membership SHRINK fires the ONE revocation act (TM-1), while the member's remaining
    memberships stay untouched. Without it the person keeps a live session, a live invite
    into the side they just left, and an emailed digest of it."""
    bridging, far, first = _who(world, "bridging"), _pod(world, "far"), _pod(world, "first")
    before_generation = bridging.token_generation
    DigestSubscription.objects.create(member=bridging, address="someone@example.com", enabled=True)
    invite = Invite.objects.create(
        pod=far,
        token_digest="a-digest-reaching-the-side-they-are-leaving",
        expires_at=timezone.now() + timedelta(days=7),
    )

    moved = _carry_out(_client_for(_who(world, "owner")), bridging, act="remove", pod_id=far.id)

    assert moved.status_code == 302, moved.status_code
    bridging.refresh_from_db()
    invite.refresh_from_db()
    assert bridging.token_generation > before_generation, "every carried credential must die"
    assert invite.revoked_at is not None, "a live invite into that side is a way back in"
    assert not DigestSubscription.objects.get(member=bridging).enabled
    assert _households(bridging) == {first.id}


def test_every_act_leaves_a_record_of_who_did_it(world: dict[str, Member | Pod | Yard]) -> None:
    """Who, whom, which household, when — the `RecoveryToken.issued_by` shape, not a general
    audit log (there is none here, and inventing one for this would be a new surface)."""
    owner, cousin, second = _who(world, "owner"), _who(world, "cousin"), _pod(world, "second")
    client = _client_for(owner)

    assert _carry_out(client, cousin, act="add", pod_id=second.id).status_code == 302
    assert _carry_out(client, cousin, act="remove", pod_id=second.id).status_code == 302

    records = list(HouseholdChange.objects.filter(member=cousin).order_by("id"))
    assert [record.action for record in records] == [HouseholdChange.ADDED, HouseholdChange.REMOVED]
    assert {record.changed_by_id for record in records} == {owner.id}
    assert {record.pod_id for record in records} == {second.id}
    assert all(record.created_at is not None for record in records)


def test_the_roster_offers_the_link_exactly_where_it_works(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """A link that 403s is a link that lies: the roster control is gated on the same
    predicate the page is, so it never appears on the actor's own row or on an admin's."""
    admin, cousin, peer = (
        _who(world, "side_admin"),
        _who(world, "cousin"),
        _who(world, "peer_admin"),
    )

    body = _client_for(admin).get(reverse("members")).content.decode()

    assert _url(cousin) in body
    assert _url(admin) not in body
    assert _url(peer) not in body
