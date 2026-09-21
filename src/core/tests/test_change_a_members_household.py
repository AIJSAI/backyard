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
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from core import households, posting, supervised
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


def test_a_yard_admin_never_changes_their_own_household(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """A yard admin's authority is BOUNDED BY their own sides, so a seat they hand
    themselves is the widening T-AUTH-G2 exists to forbid — one person, one tap, no second
    party. The predicate tests `is_instance_admin` and not `is_admin` for exactly this row,
    so this test is what stops that from eroding into "any admin"."""
    actor, second = _who(world, "side_admin"), _pod(world, "second")
    client = _client_for(actor)

    assert client.get(_url(actor)).status_code == 403
    assert _propose(client, actor, act="add", pod_id=second.id).status_code == 403
    assert not PodMembership.objects.filter(member=actor, pod=second).exists()


def test_the_instance_admin_can_put_themselves_on_a_side_they_have_just_made(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """The self-host case the whole feature is for: one person owns the instance, creates
    the second side of the family, and has to be in a household on it. They already hold
    every side through `can_issue_invite` and could already redeem their own invite into
    it, so refusing the one-tap version bought a shell session and not a boundary — and the
    act is still said back in full first, and still recorded against them."""
    owner, paternal = _who(world, "owner"), _yard(world, "paternal")

    shown = _propose(
        _client_for(owner),
        owner,
        act="create",
        household_name="The owner's other place",
        yard_ids=[paternal.id],
    )
    assert "Paternal" in _block(shown.content.decode(), "sides-gained"), (
        "self-service does not skip the step that names the side"
    )

    done = _carry_out(
        _client_for(owner),
        owner,
        act="create",
        household_name="The owner's other place",
        yard_ids=[paternal.id],
    )

    assert done.status_code == 302, done.status_code
    made = Pod.objects.get(name="The owner's other place")
    assert PodMembership.objects.filter(member=owner, pod=made).exists()
    record = HouseholdChange.objects.get(member=owner, pod=made)
    assert record.changed_by_id == owner.id, "the record says who did it, even to themselves"
    assert record.action == HouseholdChange.ADDED


def test_the_instance_admin_cannot_take_away_their_own_last_household(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """The one state self-service must never reach. An instance admin keeps every power
    through their ROLE, not their membership, so moving themselves is reversible by
    themselves — except this: a member in no household resolves nobody through the guard,
    including themselves, and the sole owner of a self-hosted instance would be locking
    himself out of his own family with one tap. `check_remove` is target-agnostic, and this
    is the assertion that says so on the row where it matters most."""
    owner, first = _who(world, "owner"), _pod(world, "first")

    response = _propose(_client_for(owner), owner, act="remove", pod_id=first.id)

    assert response.status_code == 200, response.status_code
    assert "only household" in response.content.decode()
    assert PodMembership.objects.filter(member=owner, pod=first).exists()
    assert not HouseholdChange.objects.exists()


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
    assert "Enter a household name." in nameless.content.decode()
    assert "Choose at least one side." in sideless.content.decode()
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
    # ...and it must not stop there. The plural half of the same sentence used to end "so
    # this does not change what they can see", which is false: the household they leave
    # takes its own posts, photographs and My Household fields with it.
    assert "kept to itself" in " ".join(body.split())


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
    guessable: the person is signed out on every device, the links in the email updates
    they already hold stop working, and so does any unused invite into that side."""
    bridging, far = _who(world, "bridging"), _pod(world, "far")

    body = _propose(
        _client_for(_who(world, "owner")), bridging, act="remove", pod_id=far.id
    ).content.decode()

    assert "signed out" in body
    assert "email updates" in body
    assert "invite" in body


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
    """A membership SHRINK fires its OWN revocation registry (TM-1), scoped to the side
    being lost.

    Three things at once, and the last two are what make it a shrink rather than a removal:
    everything the member HOLDS dies (the generation bump), the invite reaching the side
    they just left dies because it is a re-entry route (T-AUTH-G3) — and the invite into the
    side they KEEP survives, because that one is the invited household's credential and not
    theirs, while the digest SUBSCRIPTION survives because they are still here and an elder
    has no login to turn it back on with (S-501, T-EMAIL-6).
    """
    bridging, far, first = _who(world, "bridging"), _pod(world, "far"), _pod(world, "first")
    before_generation = bridging.token_generation
    DigestSubscription.objects.create(
        member=bridging,
        address="someone@example.com",
        enabled=True,
        # Non-empty, or the "emailed capabilities die" assertion below would pass on a
        # field that was blank to begin with.
        confirm_token_digest="a" * 64,
        unsubscribe_token_digest="b" * 64,
    )
    invite = Invite.objects.create(
        pod=far,
        token_digest="a-digest-reaching-the-side-they-are-leaving",
        expires_at=timezone.now() + timedelta(days=7),
    )
    kept_side_invite = Invite.objects.create(
        pod=first,
        token_digest="a-digest-reaching-the-side-they-keep",
        expires_at=timezone.now() + timedelta(days=7),
    )

    moved = _carry_out(_client_for(_who(world, "owner")), bridging, act="remove", pod_id=far.id)

    assert moved.status_code == 302, moved.status_code
    bridging.refresh_from_db()
    invite.refresh_from_db()
    kept_side_invite.refresh_from_db()
    assert bridging.token_generation > before_generation, "every carried credential must die"
    assert invite.revoked_at is not None, "a live invite into that side is a way back in"
    assert kept_side_invite.revoked_at is None, (
        "another household's hand-over link, on the side this person KEEPS, was cancelled "
        "by an act that was only meant to move them"
    )
    subscription = DigestSubscription.objects.get(member=bridging)
    assert subscription.enabled, "a shrink is not a removal: the preference survives (S-501)"
    assert subscription.confirm_token_digest == "", "the emailed capabilities still die"
    assert subscription.unsubscribe_token_digest == ""
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
    """A link that 403s is a link that lies, and a capability with no control is a
    capability nobody has: the roster reads the same predicate the page enforces, so it
    never appears on a yard admin's own row or on an admin they may not administer — and it
    DOES appear on the instance admin's own row, which is the one place the predicate now
    says yes to self."""
    admin, cousin, peer, owner = (
        _who(world, "side_admin"),
        _who(world, "cousin"),
        _who(world, "peer_admin"),
        _who(world, "owner"),
    )

    body = _client_for(admin).get(reverse("members")).content.decode()

    assert _url(cousin) in body
    assert _url(admin) not in body
    assert _url(peer) not in body

    # The instance admin's roster, where the self row is the point of the whole decision.
    owners_view = _client_for(owner).get(reverse("members")).content.decode()
    assert _url(owner) in owners_view, (
        "the owner can change their own household and the roster did not offer it, so the "
        "capability exists and nobody can reach it"
    )
    assert _url(admin) in owners_view  # and everyone else's, on either side


def test_a_yard_admin_cannot_reach_a_household_that_bridges_the_two_sides(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """The subset rule with the case the whole isolation model is built around. `world` has
    a bridging MEMBER and no bridging POD, and a household in reach is one whose sides are
    ALL inside the actor's own — so without this the rule that separates
    `filter(yards__in=mine)` from `filter(...).exclude(yards__in=theirs)` has no test, and
    the failure it would let through is a yard admin handing one of their own members a seat
    in the far side's living room."""
    side_admin, cousin = _who(world, "side_admin"), _who(world, "cousin")
    bridge = Pod.objects.create(name="The bridging household")
    bridge.yards.set([_yard(world, "maternal"), _yard(world, "paternal")])
    client = _client_for(side_admin)

    assert "The bridging household" not in client.get(_url(cousin)).content.decode()
    assert _propose(client, cousin, act="add", pod_id=bridge.id).status_code == 404
    assert not PodMembership.objects.filter(member=cousin, pod=bridge).exists()


def test_a_plain_member_parent_cannot_move_their_own_supervised_child(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """`can_manage_member` is True for a managing parent of ANY role (TM-10). That is right
    for editing their child's profile and wrong here, because a household hands over a side
    of the family's whole feed — so `can_change_household` asks `is_admin` as well. Neither
    the predicate's half nor the view's gate had a test; both could be deleted and this file
    stayed green."""
    cousin, first, second = _who(world, "cousin"), _pod(world, "first"), _pod(world, "second")
    child = supervised.create_supervised_member(parent=cousin, display_name="A Child", pod=first)
    client = _client_for(cousin)

    assert client.get(_url(child)).status_code == 403
    assert _propose(client, child, act="add", pod_id=second.id).status_code == 403
    assert not PodMembership.objects.filter(member=child, pod=second).exists()


def test_a_yard_admin_cannot_reach_their_own_supervised_child_who_bridges_both_sides(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """The custody branch of `can_manage_member` returns True for a managing parent BEFORE
    the yard-subset test runs (TM-10), so a yard admin whose own supervised child also
    belongs to a household on the other side would have reached this act on a bridging
    target — and the shrink's revocation resolves its scope from that child's LIVE
    memberships, reaching a side the admin administers none of. The subset rule is re-asked
    in `can_change_household` for exactly this row."""
    side_admin, first, far = _who(world, "side_admin"), _pod(world, "first"), _pod(world, "far")
    child = supervised.create_supervised_member(
        parent=side_admin, display_name="A Bridging Child", pod=first
    )
    PodMembership.objects.create(member=child, pod=far)  # also on the other side
    client = _client_for(side_admin)

    assert client.get(_url(child)).status_code == 403
    assert _propose(client, child, act="remove", pod_id=first.id).status_code == 403
    assert PodMembership.objects.filter(member=child, pod=first).exists()

    # Denominator: the same parent, the same act, on a child who is NOT bridging, works.
    in_scope = supervised.create_supervised_member(
        parent=side_admin, display_name="An In Scope Child", pod=first
    )
    assert client.get(_url(in_scope)).status_code == 200


def test_the_services_re_ask_authorization_inside_their_own_transaction(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """Defence in depth is a claim, and an unasserted claim is a comment. Called directly —
    the way a future caller reaches these — each service refuses on its own."""
    side_admin, bridging, far = (
        _who(world, "side_admin"),
        _who(world, "bridging"),
        _pod(world, "far"),
    )
    cousin, maternal = _who(world, "cousin"), _yard(world, "maternal")

    with pytest.raises(PermissionDenied):
        households.add_to_household(actor=side_admin, member=cousin, pod=far)
    with pytest.raises(PermissionDenied):
        households.remove_from_household(actor=side_admin, member=bridging, pod=far)
    with pytest.raises(PermissionDenied):
        households.create_household_and_add(
            actor=cousin,
            member=bridging,
            name="Not theirs to make",
            yards=[maternal],
        )
    assert not Pod.objects.filter(name="Not theirs to make").exists()
    assert not PodMembership.objects.filter(member=cousin, pod=far).exists()


def test_a_confirmation_cannot_be_spent_on_a_different_act(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """The nonce is keyed on the PERSON, so on its own it is a permission to change this
    person's households rather than a confirmation of the one change the admin read. A
    confirm page rendered for a household on their own side must not be submittable as the
    household on the other side — the sides gained were never named on any page."""
    cousin, second, far = _who(world, "cousin"), _pod(world, "second"), _pod(world, "far")
    client = _client_for(_who(world, "owner"))
    shown = client.post(_url(cousin), {"act": "add", "pod_id": second.id})
    match = _INTENT.search(shown.content.decode())
    assert match is not None

    swapped = client.post(_url(cousin), {"act": "add", "pod_id": far.id, "intent": match.group(1)})

    assert swapped.status_code == 200, "the swapped act must not be carried out"
    assert not PodMembership.objects.filter(member=cousin, pod=far).exists()
    assert not HouseholdChange.objects.exists()
    # What comes back is a confirm page for what was ACTUALLY submitted, naming the side
    # that act would hand over — so the next tap confirms the change being really made,
    # which is the whole point of binding the confirmation to the proposal.
    assert "Paternal" in _block(swapped.content.decode(), "sides-gained")


def test_the_confirm_page_says_a_household_carries_its_own_private_posts(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """An add that gains no SIDE still hands over the household's pod-only posts (S-204) and
    whatever its members — the children included — scoped to My Household (S-903). The page
    used to say, in as many words, that nothing changed."""
    cousin, second = _who(world, "cousin"), _pod(world, "second")

    body = _propose(
        _client_for(_who(world, "owner")), cousin, act="add", pod_id=second.id
    ).content.decode()
    # Whitespace-normalised: the sentence wraps in the template, and the field's own
    # visibility choice ("My Household") is what it has to name.
    flat = " ".join(body.split())

    assert _block(body, "sides-gained") == ""  # same side: no new side is gained
    assert "kept to itself" in flat
    assert "set to My Household" in flat
    assert "does not change which sides of the family" not in flat


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_removals_cannot_strand_a_member(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """The stranding refusal has to hold against a RACE, not only against a second click.

    Two admins take a member out of her two remaining households at the same instant. Under
    READ COMMITTED each sees the other's membership row still present, so each passes
    `check_remove` — and both deletes land, leaving her in no household at all, resolving
    nobody through the guard including herself. The member row lock is what serialises them.

    Driven on two real connections with a barrier between the check and the write, which is
    the only way this failure mode is reachable; `transaction=True` gives each thread its
    own committed view.
    """
    import threading

    from django.db import connections

    cousin, first, second = _who(world, "cousin"), _pod(world, "first"), _pod(world, "second")
    owner = _who(world, "owner")
    PodMembership.objects.create(member=cousin, pod=second)  # two households, both removable
    at_the_same_moment = threading.Barrier(2, timeout=10)
    errors: list[Exception] = []

    def take_out(pod: Pod) -> None:
        try:
            at_the_same_moment.wait()
            households.remove_from_household(actor=owner, member=cousin, pod=pod)
        except Exception as exc:  # noqa: BLE001 — collected and asserted on below
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=take_out, args=(pod,)) for pod in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert _households(cousin), (
        "both removals landed and the member is in no household at all — the one state this "
        f"refusal exists to prevent (errors={errors})"
    )
    assert len(errors) == 1 and isinstance(errors[0], households.HouseholdChangeRefused), (
        f"exactly one of the two must be refused, not {errors}"
    )


# --------------------------------------------------------------------------------------
# One side of the family is not a list (walk 2026-09-20).
#
# What the walk saw, signed in as an admin whose whole reach is one side: a page whose
# opening sentence said the households somebody is in "decide which sides of the family
# they can see", and a New Household form with a fieldset legend reading "Sides Of The
# Family" over a single checkbox. Both name a second side to a reader who has never been
# shown one — voice.md rule 8, describe a thing from where the reader stands — and the
# checkbox had the two states a control must never have, "the only possible answer" and "an
# error message".
#
# `core/invite_household.html` cured exactly this on walk item 9. The same shape is applied
# here: one reachable side is STATED and the list is not rendered, so the POST carries no
# `yard_ids` and `household_views._proposal` derives the side from the actor's own reach.
# Two or more sides is untouched, because there it is a real choice — a household can
# belong to both, which is the bridge the whole isolation model is built around.
#
# Nothing about authorization moves. The tests below pin that, too: the side is derived
# from the actor's reach and never from the browser, and a POST naming a side the actor
# cannot see is refused exactly as it was.
# --------------------------------------------------------------------------------------

_PLURAL_IN_BODY = "sides of the family"
_PLURAL_AS_A_LEGEND = "Sides Of The Family"


def _as_rendered(name: str) -> str:
    """A side's name the way the page writes it.

    Families name a side with an apostrophe in it — "Mom's side" is the name the live
    instance uses — and Django escapes it to `Mom&#x27;s side`. Asserting on the raw name
    is a false failure about escaping, not a measurement of what the page says.
    """
    return escape(name)


@pytest.fixture
def one_side() -> dict[str, Member | Pod | Yard]:
    """A Backyard with exactly one side of the family: every fresh install, until somebody
    stands up the second (S-708), and the state the walk was done in.

    The target is in NO household, which is the case this feature exists for — an account
    that already exists and belongs in a household — and the only way an add can hand over
    a side on a Backyard that has one.
    """
    side = Yard.objects.create(name="Mom's side", slug="moms-side")
    home = Pod.objects.create(name="The Fletchers", kind=Pod.HOUSEHOLD)
    home.yards.set([side])
    spare = Pod.objects.create(name="The other Fletchers", kind=Pod.HOUSEHOLD)
    spare.yards.set([side])
    return {
        "side": side,
        "home": home,
        "spare": spare,
        "admin": _member(home, "The Only Admin", Member.INSTANCE_ADMIN),
        "cousin": _member(None, "A Cousin With No Household"),
    }


def test_one_side_is_stated_and_never_offered_as_a_list(
    one_side: dict[str, Member | Pod | Yard],
) -> None:
    body = _client_for(_who(one_side, "admin")).get(_url(_who(one_side, "cousin"))).content.decode()

    assert "This household joins" in body
    assert _as_rendered(_yard(one_side, "side").name) in body, "it must say WHICH side, by name"
    assert _PLURAL_AS_A_LEGEND not in body, "the legend still names sides this admin has not got"
    assert _PLURAL_IN_BODY not in body, "the page still talks about sides in the plural"
    # Scoped by FIELD NAME rather than "no checkbox on the page": the page may grow another
    # control one day, and the property held here is about the sides control alone.
    assert 'name="yard_ids"' not in body, "a lone side checkbox is still on the page"


def test_one_side_creates_the_household_in_that_side_with_no_field_in_the_post(
    one_side: dict[str, Member | Pod | Yard],
) -> None:
    """The browser now sends no `yard_ids` at all, because there is no control to send one.
    The household must still land in the one side, and the confirm step must still name it
    before anything happens."""
    admin, cousin, side = _who(one_side, "admin"), _who(one_side, "cousin"), _yard(one_side, "side")
    client = _client_for(admin)

    shown = _propose(client, cousin, act="create", household_name="The Davis family")
    assert _as_rendered(side.name) in shown.content.decode(), (
        "the confirm step stopped naming the side"
    )
    assert not Pod.objects.filter(name="The Davis family").exists()

    done = _carry_out(client, cousin, act="create", household_name="The Davis family")

    assert done.status_code == 302, done.status_code
    made = Pod.objects.get(name="The Davis family")
    assert {yard.pk for yard in made.yards.all()} == {side.pk}
    assert PodMembership.objects.filter(member=cousin, pod=made).exists()


def test_a_yard_admin_who_reaches_one_side_gets_the_singular_and_their_own_side(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """Two sides EXIST here; this admin reaches one. The reader is what decides the words,
    so they get the statement — and the side derived for them is theirs, not the first row
    in the table."""
    client = _client_for(_who(world, "side_admin"))

    body = client.get(_url(_who(world, "cousin"))).content.decode()
    assert "This household joins" in body
    assert _yard(world, "maternal").name in body
    assert _yard(world, "paternal").name not in body
    assert _PLURAL_AS_A_LEGEND not in body

    done = _carry_out(client, _who(world, "cousin"), act="create", household_name="The Lane family")
    assert done.status_code == 302, done.status_code
    assert {yard.pk for yard in Pod.objects.get(name="The Lane family").yards.all()} == {
        _yard(world, "maternal").pk
    }


def test_a_hand_made_post_naming_an_unreachable_side_is_still_refused(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """The security property the derived side must not cost us. A yard admin's own form now
    submits no side, so the view has a branch that supplies one — and a POST that NAMES the
    far side must never reach it. It is the same byte-identical 404 as a side that does not
    exist (S-202 parity), never a quiet rewrite to the side they are allowed, which would
    turn an attempted scope escape into a success somewhere else."""
    client = _client_for(_who(world, "side_admin"))
    before = Pod.objects.count()

    response = client.post(
        _url(_who(world, "cousin")),
        {
            "act": "create",
            "household_name": "The Cross family",
            "yard_ids": [str(_yard(world, "paternal").id)],
        },
    )

    assert response.status_code == 404
    assert Pod.objects.count() == before
    assert not Pod.objects.filter(name="The Cross family").exists()


def test_two_sides_still_offer_the_choice(world: dict[str, Member | Pod | Yard]) -> None:
    """The bridging-household control is a real choice with two real answers, and it stays
    exactly as it was: a legend, two checkboxes, neither pre-ticked."""
    body = _client_for(_who(world, "owner")).get(_url(_who(world, "cousin"))).content.decode()
    fieldset = body[body.index("<fieldset") : body.index("</fieldset>")]

    assert _PLURAL_AS_A_LEGEND in body
    assert fieldset.count('type="checkbox"') == 2
    assert "checked" not in fieldset, "the product answered a real choice for them"
    assert _yard(world, "maternal").name in fieldset
    assert _yard(world, "paternal").name in fieldset
    assert "This household joins" not in body, "the single-side statement is not for this reader"


def test_the_confirm_page_names_one_side_in_the_singular(
    one_side: dict[str, Member | Pod | Yard],
) -> None:
    body = _propose(
        _client_for(_who(one_side, "admin")),
        _who(one_side, "cousin"),
        act="add",
        pod_id=_pod(one_side, "home").id,
    ).content.decode()
    flat = " ".join(body.split())

    named = _as_rendered(_yard(one_side, "side").name)
    assert f"Every post and photograph on <strong>{named}</strong>" in flat
    assert _block(body, "sides-gained") == "", "a one-item list is still being rendered"
    assert _PLURAL_IN_BODY not in flat


def test_the_confirm_page_still_lists_sides_for_a_reader_who_has_two(
    world: dict[str, Member | Pod | Yard],
) -> None:
    body = _propose(
        _client_for(_who(world, "owner")),
        _who(world, "cousin"),
        act="add",
        pod_id=_pod(world, "far").id,
    ).content.decode()
    flat = " ".join(body.split())

    assert f"Every post and photograph on these {_PLURAL_IN_BODY}" in flat
    assert _yard(world, "paternal").name in _block(body, "sides-gained")


def test_the_confirm_page_says_a_removal_keeps_them_on_the_same_side_and_names_what_it_costs(
    one_side: dict[str, Member | Pod | Yard],
) -> None:
    """Keeping the side is not keeping everything, and this branch used to say it was.

    It ended "so this does not change what they can see", which is false in three measured
    ways: `scoping.visible_posts` resolves an audience-less post through pod membership
    alone, `scoping.visible_media` inherits that post's audience, and
    `profiles._can_see_field` needs a SHARED pod for a field set to My Household. The other
    household keeps none of those.

    The side itself is still not NAMED in either voice — "the same side they are on now"
    stays true for a household that belongs to none — so only the word's number follows the
    reader.
    """
    cousin = _who(one_side, "cousin")
    PodMembership.objects.create(member=cousin, pod=_pod(one_side, "home"))
    PodMembership.objects.create(member=cousin, pod=_pod(one_side, "spare"))

    body = _propose(
        _client_for(_who(one_side, "admin")),
        cousin,
        act="remove",
        pod_id=_pod(one_side, "home").id,
    ).content.decode()
    flat = " ".join(body.split())

    assert "keeps them on the same side of the family" in flat
    assert "kept to itself" in flat
    assert _PLURAL_IN_BODY not in flat


def test_the_confirm_page_names_the_one_side_a_removal_costs(
    one_side: dict[str, Member | Pod | Yard],
) -> None:
    """The losing half of the singular, which on a one-side Backyard needs the second
    household to belong to no side — the shape an instance has while somebody is still
    standing the first side up (S-708). Contrived, and it is the only arrangement in which
    a one-side reader can be told they are losing something: leaving their only household
    is refused outright, and leaving one of two on the same side costs nothing."""
    cousin, side = _who(one_side, "cousin"), _yard(one_side, "side")
    unattached = Pod.objects.create(name="An unattached household", kind=Pod.HOUSEHOLD)
    PodMembership.objects.create(member=cousin, pod=_pod(one_side, "home"))
    PodMembership.objects.create(member=cousin, pod=unattached)

    body = _propose(
        _client_for(_who(one_side, "admin")),
        cousin,
        act="remove",
        pod_id=_pod(one_side, "home").id,
    ).content.decode()
    flat = " ".join(body.split())

    named = _as_rendered(side.name)
    assert f"<strong>{named}</strong> goes away for them as soon as you do this." in flat
    assert _block(body, "sides-lost") == "", "a one-item list is still being rendered"
    assert _PLURAL_IN_BODY not in flat


def test_the_create_confirm_page_names_the_derived_side_even_when_nothing_is_gained(
    one_side: dict[str, Member | Pod | Yard],
) -> None:
    """The ordinary case for a one-side Backyard: a household made for somebody who is
    already on that side, so `proposal.gained` is empty and every sentence about gaining a
    side is skipped. The side was derived by the view from a POST that never named it, and
    it appeared on the confirm page NOWHERE — the one screen whose whole job is to say the
    act back before it happens was confirming a value the admin could not see."""
    admin, side = _who(one_side, "admin"), _yard(one_side, "side")
    # Already on the side, through the household the fixture's admin shares with them.
    cousin = _member(_pod(one_side, "home"), "An Already Placed Cousin")

    body = _propose(
        _client_for(admin), cousin, act="create", household_name="The Davis family"
    ).content.decode()
    flat = " ".join(body.split())

    assert _block(body, "sides-gained") == "", "this case gains no side; the fixture is wrong"
    assert f"This household joins <strong>{_as_rendered(side.name)}</strong>." in flat


def test_an_instance_with_no_sides_says_so_instead_of_an_empty_fieldset(
    world: dict[str, Member | Pod | Yard],
) -> None:
    """`one_side` is `== 1`, not `<= 1`, so an actor who reaches NO side lands in the
    two-or-more branch and used to get a legend over nothing at all. The Family Admin sees
    every side there is, so deleting them all is the reachable shape of it."""
    cousin = _who(world, "cousin")
    Yard.objects.all().delete()

    body = _client_for(_who(world, "owner")).get(_url(cousin)).content.decode()

    assert "No side you can put a household in yet." in body
    assert 'name="yard_ids"' not in body, "a checkbox was rendered for a side that is gone"
    # And the form is still honest on submit: the view refuses, it does not invent a side.
    refused = _propose(
        _client_for(_who(world, "owner")), cousin, act="create", household_name="The Ash family"
    )
    assert "Choose at least one side." in refused.content.decode()
    assert not Pod.objects.filter(name="The Ash family").exists()
