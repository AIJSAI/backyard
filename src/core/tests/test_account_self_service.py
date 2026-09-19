"""BY-02, BY-03, BY-13: the three things a member could not do or be told.

BY-02: every allauth account page — the sign-in email, the password change, the passkey
and recovery-code set — was routed, styled by this project's own layout overrides, and
linked from NOWHERE. `src/templates/allauth/layouts/manage.html` calls them, in its own
comment, "the account pages a signed-in member reaches from inside the app"; they reached
them from nothing, and `join.html` promises "You can add a passkey once you are in".

BY-03: members who joined before 2026-08-01 have neither an `EmailAddress` row nor
`User.email`, because the join form had no email box. Chained with BY-02 the join-time
decision to skip it was permanent — there was no later surface that collected one.

BY-13: a plain member cannot invite anyone (`can_issue_invite` refuses the role) and no
page they could reach said whose job it is.

The general reachability gate lives in test_member_settings_are_reachable; these are the
specific claims, so that deleting the settings links fails HERE by name rather than only
as a route count.
"""

from __future__ import annotations

import re

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core import invites
from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"

# The three account pages a member must be able to reach from their own settings.
_ACCOUNT_PAGES = ("account_email", "account_change_password", "mfa_index")


def _hrefs(html: str) -> set[str]:
    return set(re.findall(r'href="([^"]+)"', html))


def _world() -> tuple[Yard, Pod]:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Our house")
    pod.yards.set([yard])
    return yard, pod


# A usable password, not the unusable one create_user() leaves when none is given:
# allauth redirects the password-CHANGE page to the password-SET page for an account with
# nothing to change, so a password-less fixture would exercise the wrong route.
_TEST_PW = "a-Strong-passphrase-9"


def _signed_in(pod: Pod, *, username: str = "nana", email: str = "") -> tuple[Member, Client]:
    user = User.objects.create_user(username=username, email=email, password=_TEST_PW)
    member = Member.objects.create(display_name="Nana", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return member, client


# --- BY-02: the account pages have an entrance -------------------------------------


@pytest.mark.parametrize("route", _ACCOUNT_PAGES)
def test_settings_links_each_account_page_and_it_answers(route: str) -> None:
    """Navigated the way a person does — feed, Settings, the link — and then FOLLOWED,
    because a link that 403s or 500s is not an entrance."""
    _, pod = _world()
    _, client = _signed_in(pod)

    settings_url = reverse("profile_edit")
    assert settings_url in _hrefs(client.get(reverse("feed")).content.decode())

    target = reverse(route)
    assert target in _hrefs(client.get(settings_url).content.decode()), (
        f"{route} is routed, styled and linked from nowhere a member can stand"
    )
    assert client.get(target).status_code == 200


def test_an_admin_editing_someone_else_is_not_offered_their_account_pages() -> None:
    """These change THAT person's credentials. An admin standing in for an elder may fix
    a birthday; they may not walk into her password change. The admin's control for a
    locked-out member is the roster's recovery link, which hands the decision back."""
    _, pod = _world()
    admin_user = User.objects.create_user(username="admin")
    admin = Member.objects.create(
        display_name="The Admin", user=admin_user, role=Member.INSTANCE_ADMIN
    )
    PodMembership.objects.create(member=admin, pod=pod)
    other, _ = _signed_in(pod, username="other")

    client = Client()
    client.force_login(admin_user, backend=_BACKEND)
    own = _hrefs(client.get(reverse("profile_edit")).content.decode())
    managed = _hrefs(client.get(reverse("managed_profile_edit", args=[other.pk])).content.decode())

    for route in _ACCOUNT_PAGES:
        # Denominator first: the links ARE there on the admin's own settings, so an
        # absence below is the branch firing rather than the section having been removed.
        assert reverse(route) in own
        assert reverse(route) not in managed


# --- BY-03: the member with no address is told, once -------------------------------


def test_a_member_with_no_address_anywhere_is_prompted() -> None:
    """The pre-#121 join left User.email empty AND created no EmailAddress row, so
    allauth's reset resolves against nothing and its fallback finds nothing either."""
    _, pod = _world()
    member, client = _signed_in(pod)
    assert member.user is not None and not member.user.email
    assert not EmailAddress.objects.filter(user=member.user).exists()

    # Whitespace-normalised: the sentence wraps in the template, which is how it should be
    # written and not something a test should pin.
    body = " ".join(client.get(reverse("feed")).content.decode().split())
    # The sentence changed on 2026-09-19 (walk item 5): this was a screen-tall card ABOVE
    # the composer that said the same thing in two paragraphs, with "Not now" as its
    # loudest button. It is one line under the composer now. What is asserted is the same
    # property — the member is told, and the way to act on it is a tap away.
    assert "so you can reset your own password" in body
    assert reverse("account_email") in _hrefs(body)
    assert reverse("dismiss_email_prompt") in body, "no quiet way to decline"


@pytest.mark.parametrize("store", ["user_email", "email_address_row"])
def test_the_prompt_is_absent_once_an_address_exists_in_either_store(store: str) -> None:
    """BOTH stores are a recovery path, because allauth reads both: it resolves against a
    verified EmailAddress and falls back to User.email when none matched. Prompting
    somebody who already has one would be a nag, and an untrue one."""
    _, pod = _world()
    member, client = _signed_in(pod)
    assert member.user is not None
    if store == "user_email":
        member.user.email = "nana@example.com"
        member.user.save(update_fields=["email"])
    else:
        EmailAddress.objects.create(user=member.user, email="nana@example.com", primary=True)

    assert "forget your password" not in client.get(reverse("feed")).content.decode()


def test_dismissing_the_prompt_makes_it_never_return() -> None:
    _, pod = _world()
    member, client = _signed_in(pod)

    assert client.post(reverse("dismiss_email_prompt")).status_code == 302
    member.refresh_from_db()
    assert member.email_prompt_dismissed_at is not None
    assert "forget your password" not in client.get(reverse("feed")).content.decode()


def test_the_prompt_cannot_be_cleared_by_a_get() -> None:
    """A link prefetch or a mail scanner must not put away the one thing they have not
    read yet — the same rule the orientation card already follows."""
    _, pod = _world()
    member, client = _signed_in(pod)

    assert client.get(reverse("dismiss_email_prompt")).status_code == 405
    member.refresh_from_db()
    assert member.email_prompt_dismissed_at is None


def test_dismissing_twice_keeps_the_first_moment() -> None:
    """The column stays a truthful record of when they said no, not of the last prefetch."""
    _, pod = _world()
    member, client = _signed_in(pod)
    client.post(reverse("dismiss_email_prompt"))
    member.refresh_from_db()
    first = member.email_prompt_dismissed_at

    client.post(reverse("dismiss_email_prompt"))
    member.refresh_from_db()
    assert member.email_prompt_dismissed_at == first


def test_the_prompt_is_independent_of_the_welcome_having_been_seen() -> None:
    """It has to reach the members who joined BEFORE the join form had an email box, and
    those are exactly the ones the S-906 backfill stamped as already oriented. Sharing a
    column would have hidden the prompt from its whole audience."""
    from django.utils import timezone

    _, pod = _world()
    member, client = _signed_in(pod)
    Member.objects.filter(pk=member.pk).update(orientation_dismissed_at=timezone.now())

    body = " ".join(client.get(reverse("feed")).content.decode().split())
    assert "so you can reset your own password" in body  # reworded, walk item 5


# --- BY-13: whose job inviting is ---------------------------------------------------


def test_a_newcomer_is_told_who_can_add_people_and_named_their_inviter() -> None:
    _, pod = _world()
    admin_user = User.objects.create_user(username="admin")
    admin = Member.objects.create(
        display_name="Aunt Ada", user=admin_user, role=Member.INSTANCE_ADMIN
    )
    PodMembership.objects.create(member=admin, pod=pod)

    _, raw = invites.mint_invite(pod, created_by=admin)
    joined = invites.redeem_invite(raw, display_name="New Cousin", user_id=None)
    joined.user = User.objects.create_user(username="newcousin")
    joined.save(update_fields=["user"])

    client = Client()
    client.force_login(joined.user, backend=_BACKEND)
    # The DIRECTORY, not the feed. The sentence used to sit above the composer on every
    # visit forever; it is a standing fact, and this is the page somebody opens when they
    # are thinking about who is here.
    body = client.get(reverse("directory")).content.decode()
    assert "Adding people is an admin" in body
    assert "Aunt Ada" in body
    assert "Adding people is an admin" not in client.get(reverse("feed")).content.decode()


def test_without_a_recorded_inviter_the_sentence_names_nobody_rather_than_blank() -> None:
    """A founder, an elder, or somebody whose issuer has since been removed
    (`Invite.created_by` is SET_NULL). The sentence must still read as a sentence."""
    _, pod = _world()
    _, client = _signed_in(pod)

    body = client.get(reverse("directory")).content.decode()
    assert "Adding people is an admin" in body
    assert "whoever in the family set this up" in body


def test_the_sentence_reaches_a_member_who_has_already_seen_the_welcome() -> None:
    """The one state every current member is already in.

    Nested inside the orientation card the sentence reached nobody who had dismissed it —
    and migration 0022 stamped `orientation_dismissed_at` on every member who existed when
    it ran, which is the whole family, plus everyone who has since been through the
    welcome. BY-13's stated defect would have been unchanged for all of them, and every
    other test here creates a brand-new member, so none of them is in the affected state.
    """
    from django.utils import timezone

    _, pod = _world()
    member, client = _signed_in(pod)
    Member.objects.filter(pk=member.pk).update(orientation_dismissed_at=timezone.now())
    member.refresh_from_db()
    assert member.orientation_dismissed_at is not None

    body = client.get(reverse("directory")).content.decode()
    assert "Adding people is an admin" in body


def test_an_admin_is_not_told_to_ask_somebody_else() -> None:
    """They are the somebody else. The roster's `Invite a household` is theirs already."""
    _, pod = _world()
    admin_user = User.objects.create_user(username="admin")
    admin = Member.objects.create(display_name="The Admin", user=admin_user, role=Member.YARD_ADMIN)
    PodMembership.objects.create(member=admin, pod=pod)

    client = Client()
    client.force_login(admin_user, backend=_BACKEND)
    assert "Adding people is an admin" not in client.get(reverse("directory")).content.decode()


def test_inviter_of_survives_the_issuer_being_removed() -> None:
    """The lookup must degrade, not raise: `created_by` is SET_NULL, so the row outlives
    the person and the caller has to cope with a null."""
    _, pod = _world()
    admin_user = User.objects.create_user(username="admin")
    admin = Member.objects.create(display_name="Gone", user=admin_user, role=Member.YARD_ADMIN)
    PodMembership.objects.create(member=admin, pod=pod)
    _, raw = invites.mint_invite(pod, created_by=admin)
    joined = invites.redeem_invite(raw, display_name="New Cousin", user_id=None)
    assert invites.inviter_of(joined) == admin

    admin.delete()
    assert invites.inviter_of(joined) is None
