"""A voluntary leave is a membership SHRINK, and fires the one revocation act (S9).

TM-1's promise is that every membership-lifecycle transition runs the same revocation
handler over the same registry. `households.remove_from_household` does. `pods.leave_pod`
did not: it deleted the membership, voided that pod's reply addresses, and handed the
group on to its longest-standing member — and left every other credential the member held
alive across a scope that had just narrowed.

Whether a leave narrows anything at all is a question about the code, and the answer is
not "no". `scoping.member_yard_ids` is the union of the sides of ALL a member's pods, ad-hoc
groups included, so a member in a household on one side and an ad-hoc group on the other —
which is what an admin creates by taking somebody out of a household they also had a group
in — loses a whole side of the family by pressing Leave. And a member holding no household
at all is stranded by it: they resolve nobody through the guard, including themselves.

So: the same registry, under the same lock, in the same order, plus a refusal with a plain
sentence for the stranding case. Pod-leaves-yard and the deceased flow are STILL NOT BUILT
and are named as such in `leave_pod`'s docstring and in TM-1.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import elder_tokens, pods
from core.models import (
    DigestSubscription,
    ElderToken,
    Invite,
    Member,
    Pod,
    PodMembership,
    Yard,
)

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _yard(name: str) -> Yard:
    return Yard.objects.create(name=name, slug=name.lower().replace(" ", "-"))


def _household(name: str, yard: Yard) -> Pod:
    pod = Pod.objects.create(name=name, kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    return pod


def test_leaving_a_group_that_drops_a_side_of_the_family_runs_the_shrink_registry() -> None:
    """The transition TM-1 names, on the leave path.

    Fails without the `revoke_for_membership_shrink` call in `pods.leave_pod`: the
    generation is unchanged, so every credential minted under it — the elder link most of
    all — still resolves for a member who can no longer see that side.
    """
    kept, lost = _yard("Kept side"), _yard("Lost side")
    home = _household("Their household", kept)
    member = Member.objects.create(display_name="Cousin")
    PodMembership.objects.create(member=member, pod=home)

    group = Pod.objects.create(name="The cousins", kind=Pod.ADHOC, owner=member)
    group.yards.set([lost])
    PodMembership.objects.create(member=member, pod=group)

    raw = elder_tokens.mint(member)
    member.refresh_from_db()
    generation_before = member.token_generation
    # A live invite reaching the side they are about to lose: the T-AUTH-G3 re-entry route.
    into_lost = Invite.objects.create(
        pod=_household("Other house", lost),
        created_by=member,
        token_digest="a-digest-reaching-the-side-they-are-leaving",
        expires_at=timezone.now() + timedelta(days=7),
    )

    pods.leave_pod(member=member, pod=group)

    member.refresh_from_db()
    assert member.token_generation > generation_before, "the generation was never bumped"
    with pytest.raises(elder_tokens.ElderTokenInvalid):
        elder_tokens.resolve(raw)
    assert not ElderToken.objects.filter(member=member).exists()
    into_lost.refresh_from_db()
    assert into_lost.revoked_at is not None, (
        "an invite into the side they just left is a live way back in"
    )


def test_the_revocation_runs_while_the_membership_still_exists() -> None:
    """The H-1 ordering contract. The shrink's invite step resolves its scope from LIVE
    memberships, so revoking after the delete would silently miss every invite reaching
    the side just left — and the miss is invisible, because the act still 'succeeds'."""
    kept, lost = _yard("Kept"), _yard("Lost")
    home = _household("Home", kept)
    member = Member.objects.create(display_name="Cousin")
    PodMembership.objects.create(member=member, pod=home)
    group = Pod.objects.create(name="Group", kind=Pod.ADHOC, owner=member)
    group.yards.set([lost])
    PodMembership.objects.create(member=member, pod=group)

    # Created by somebody else, so only the YARD arm of the shrink's invite scope can
    # reach it — and that arm is resolved from the member's live memberships.
    other = Member.objects.create(display_name="Aunt")
    reachable = Invite.objects.create(
        pod=_household("Far house", lost),
        created_by=other,
        token_digest="a-digest-somebody-else-minted",
        expires_at=timezone.now() + timedelta(days=7),
    )

    pods.leave_pod(member=member, pod=group)

    reachable.refresh_from_db()
    assert reachable.revoked_at is not None


def test_leaving_a_group_inside_a_side_they_keep_revokes_nothing_extra() -> None:
    """The ordinary case, and the reason this is the SHRINK registry rather than a blanket
    one: leaving the cousins' group inside a side you are still in narrows nothing, so
    nothing should die. Bumping the generation here would kill a grandparent's link every
    time somebody tidied up their groups."""
    side = _yard("One side")
    home = _household("Home", side)
    member = Member.objects.create(display_name="Cousin")
    PodMembership.objects.create(member=member, pod=home)
    group = Pod.objects.create(name="Group", kind=Pod.ADHOC, owner=member)
    group.yards.set([side])
    PodMembership.objects.create(member=member, pod=group)

    raw = elder_tokens.mint(member)
    member.refresh_from_db()
    generation_before = member.token_generation

    pods.leave_pod(member=member, pod=group)

    member.refresh_from_db()
    assert member.token_generation == generation_before
    assert elder_tokens.resolve(raw).member_id == member.id


def test_the_digest_subscription_survives_a_leave_that_shrinks() -> None:
    """The narrowing that makes this the shrink registry and not the removal one. An elder
    has no login by design (TM-10) and the digest page is login-required and self-only, so
    disabling their subscription ends their only content channel with no route back for
    any person on the instance — the silent severing S-501 forbids."""
    kept, lost = _yard("Kept"), _yard("Lost")
    member = Member.objects.create(display_name="Gran")
    PodMembership.objects.create(member=member, pod=_household("Home", kept))
    group = Pod.objects.create(name="Group", kind=Pod.ADHOC, owner=member)
    group.yards.set([lost])
    PodMembership.objects.create(member=member, pod=group)
    subscription = DigestSubscription.objects.create(
        member=member, address="gran@example.com", enabled=True
    )

    pods.leave_pod(member=member, pod=group)

    subscription.refresh_from_db()
    assert subscription.enabled is True


def test_a_leave_that_would_strand_somebody_is_refused_in_plain_words() -> None:
    """A member left in no household resolves nobody through the guard, including
    themselves, and there is no self-service way back.

    Fails without the `is_their_last_household` refusal in `pods.leave_pod`: the
    membership is deleted and the member is stranded.
    """
    side = _yard("Only side")
    member = Member.objects.create(display_name="Alone")
    group = Pod.objects.create(name="Group", kind=Pod.ADHOC, owner=member)
    group.yards.set([side])
    PodMembership.objects.create(member=member, pod=group)

    with pytest.raises(pods.PodLeaveRefused) as caught:
        pods.leave_pod(member=member, pod=group)

    assert PodMembership.objects.filter(member=member, pod=group).exists()
    sentence = str(caught.value)
    assert "household" in sentence
    # Whole words: "Backyard" is the product's name and contains "yard", which a bare
    # substring check calls a violation — the kind of guard that gets deleted rather than
    # fixed. The rule is about the family's vocabulary, not about letters.
    words = set(re.findall(r"[a-z]+", sentence.lower()))
    for jargon in ("pod", "pods", "yard", "yards", "token", "instance", "digest"):
        assert jargon not in words, f"the refusal says {jargon!r} to a relative"


def test_the_refusal_is_true_for_somebody_in_two_groups(caplog: pytest.LogCaptureFixture) -> None:
    """Review L1. The first wording said "it is the only one you are in", which is FALSE
    for a member of two groups and no household: they can see the other one on the same
    page while being told this is their only one, and the sentence they are asked to act
    on is wrong about their own situation.

    What is actually missing is a HOUSEHOLD, which is also the only thing that answers it.
    Red against the old wording.
    """
    side = _yard("Only side")
    member = Member.objects.create(display_name="Alone")
    for name in ("The cousins", "Birthday planning"):
        group = Pod.objects.create(name=name, kind=Pod.ADHOC, owner=member)
        group.yards.set([side])
        PodMembership.objects.create(member=member, pod=group)
    leaving = Pod.objects.filter(kind=Pod.ADHOC, name="The cousins").get()

    with pytest.raises(pods.PodLeaveRefused) as caught:
        pods.leave_pod(member=member, pod=leaving)

    sentence = str(caught.value)
    assert "only one you are in" not in sentence, (
        "they are in two groups; the sentence is false as written"
    )
    assert "not in a household" in sentence, sentence


def test_the_refusal_names_the_admin_from_the_database_not_from_this_repository() -> None:
    """The footer's helper, for the same reason the footer uses it: this repository is
    public and a relative's name does not belong in it. With no instance admin the
    impersonal fallback stands."""
    side = _yard("Only side")
    member = Member.objects.create(display_name="Alone")
    group = Pod.objects.create(name="Group", kind=Pod.ADHOC, owner=member)
    group.yards.set([side])
    PodMembership.objects.create(member=member, pod=group)

    with pytest.raises(pods.PodLeaveRefused) as caught:
        pods.leave_pod(member=member, pod=group)
    assert "whoever looks after your family's Backyard" in str(caught.value)

    keeper_user = User.objects.create_user(username="keeper")
    Member.objects.create(display_name="Alex Keeper", user=keeper_user, role=Member.INSTANCE_ADMIN)
    with pytest.raises(pods.PodLeaveRefused) as caught:
        pods.leave_pod(member=member, pod=group)
    assert "Ask Alex to put you in a household" in str(caught.value), caught.value


def test_the_person_who_pressed_leave_is_not_signed_out_of_their_own_family() -> None:
    """Review M4. The shrink registry's FIRST step deletes every session belonging to the
    member — including the one that pressed the button — so a leave that drops a side
    threw the relative onto the sign-in page on the next click, with no explanation.

    Red without the re-login in `pod_views.pod_leave`: the follow-up request redirects to
    the sign-in page.
    """
    kept, lost = _yard("Kept side"), _yard("Lost side")
    home = _household("Their household", kept)
    user = User.objects.create_user(username="cousin")
    member = Member.objects.create(display_name="Cousin", user=user)
    PodMembership.objects.create(member=member, pod=home)
    group = Pod.objects.create(name="The cousins", kind=Pod.ADHOC, owner=member)
    group.yards.set([lost])
    PodMembership.objects.create(member=member, pod=group)

    client = Client()
    client.force_login(user, backend=_BACKEND)
    response = client.post(reverse("pod_leave", args=[group.id]))

    assert response.status_code == 302
    assert not PodMembership.objects.filter(member=member, pod=group).exists()
    # The half that matters to the person: they are still signed in.
    assert client.get(reverse("pod_list")).status_code == 200, (
        "leaving a group signed the member out of their own family"
    )


def test_their_other_devices_are_still_signed_out_by_the_leave() -> None:
    """The other half. Re-issuing THIS session must not resurrect the rest: the whole
    point of the shrink is that every credential reaching the side they left is dead."""
    kept, lost = _yard("Kept side"), _yard("Lost side")
    home = _household("Their household", kept)
    user = User.objects.create_user(username="cousin")
    member = Member.objects.create(display_name="Cousin", user=user)
    PodMembership.objects.create(member=member, pod=home)
    group = Pod.objects.create(name="The cousins", kind=Pod.ADHOC, owner=member)
    group.yards.set([lost])
    PodMembership.objects.create(member=member, pod=group)

    phone = Client()
    phone.force_login(user, backend=_BACKEND)
    assert phone.get(reverse("pod_list")).status_code == 200

    laptop = Client()
    laptop.force_login(user, backend=_BACKEND)
    laptop.post(reverse("pod_leave", args=[group.id]))

    # The device that did NOT press Leave is signed out, which is what revocation means.
    assert phone.get(reverse("pod_list")).status_code == 302
    # And the generation bump still killed the no-login link.
    member.refresh_from_db()
    assert not ElderToken.objects.filter(member=member).exists()


def test_leaving_a_household_is_still_refused_outright() -> None:
    """The property that was already here stays: household membership changes through an
    admin, never self-service, because there is no way back from the other side."""
    side = _yard("Side")
    member = Member.objects.create(display_name="Cousin")
    home = _household("Home", side)
    PodMembership.objects.create(member=member, pod=home)
    second = _household("Second home", side)
    PodMembership.objects.create(member=member, pod=second)

    with pytest.raises(pods.PodActionNotAllowed):
        pods.leave_pod(member=member, pod=home)
