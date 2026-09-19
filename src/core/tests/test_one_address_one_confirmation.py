"""One address, one proof: the Family email and the sign-in address stop asking twice.

Walk item 24, 2026-09-19. A new relative who gave an e-mail address at join and then
picked "weekly" on the welcome screen received TWO messages inside a minute — one from
allauth for the sign-in address, one from `digesting` for the Family email — with the
IDENTICAL subject "Is this your email address?", from the same sender, threaded together
by their mail client into what looked like one message sent twice. Both asked for a tap.
Neither said which was which, and tapping one left the other apparently unanswered.

They were proving the same fact about the same mailbox.

THE SECURITY PROPERTY THIS FILE IS MOSTLY ABOUT. A confirmation may only ever establish
that the person holding the link controls THE ADDRESS IT WAS MAILED TO, for THE MEMBER WHO
ASKED. Collapsing two confirmations into one is exactly the kind of change that quietly
widens what a single tap can prove, so the tests below try to make it prove too much:

  * a confirmation must not start the Family email for another member (cross-member);
  * a confirmation of one of my addresses must not start a Family email pointed at a
    DIFFERENT address of mine (cross-address) — family content would then follow a mailbox
    nobody proved;
  * and it must not run backwards: confirming the Family email must not verify a sign-in
    address, because that is the credential "Forgot your password?" trusts.
"""

from __future__ import annotations

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail

from core import digesting
from core.models import DigestSubscription, Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()


def _member(username: str, display_name: str, *, pod: Pod) -> Member:
    member = Member.objects.create(
        display_name=display_name, user=User.objects.create_user(username=username)
    )
    PodMembership.objects.create(member=member, pod=pod)
    return member


@pytest.fixture
def pod() -> Pod:
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    return pod


def _confirm_the_signin_address(address_row: EmailAddress) -> None:
    """What allauth's confirmation view does, at the seam our receiver listens on."""
    from allauth.account.signals import email_confirmed

    address_row.verified = True
    address_row.save(update_fields=["verified"])
    email_confirmed.send(sender=EmailAddress, request=None, email_address=address_row)


# --- one mail ------------------------------------------------------------------------


def test_the_same_address_sends_no_second_confirmation(pod: Pod) -> None:
    member = _member("cousin", "Cousin Reed", pod=pod)
    EmailAddress.objects.create(
        user=member.user, email="cousin@example.com", primary=True, verified=False
    )
    mail.outbox.clear()

    subscription = digesting.subscribe(member, address="cousin@example.com", cadence="weekly")

    assert mail.outbox == [], [m.subject for m in mail.outbox]
    assert subscription.confirmed_at is None, "family content would flow unproven"


def test_one_tap_on_the_account_confirmation_starts_the_family_email(pod: Pod) -> None:
    member = _member("cousin", "Cousin Reed", pod=pod)
    row = EmailAddress.objects.create(
        user=member.user, email="cousin@example.com", primary=True, verified=False
    )
    digesting.subscribe(member, address="cousin@example.com", cadence="weekly")

    _confirm_the_signin_address(row)

    subscription = DigestSubscription.objects.get(member=member)
    assert subscription.confirmed_at is not None, "the one tap did not start the Family email"
    assert subscription.confirm_token_digest == "", "a live confirm token survived"


def test_an_already_verified_address_needs_no_tap_at_all(pod: Pod) -> None:
    """Control is already proven for this member and this address. Asking them to prove it
    again is a nag, and a nag that stops the Family email until they answer it."""
    member = _member("cousin", "Cousin Reed", pod=pod)
    EmailAddress.objects.create(
        user=member.user, email="cousin@example.com", primary=True, verified=True
    )
    mail.outbox.clear()

    subscription = digesting.subscribe(member, address="cousin@example.com", cadence="weekly")

    assert mail.outbox == []
    assert subscription.confirmed_at is not None


def test_case_does_not_make_it_a_different_mailbox(pod: Pod) -> None:
    """A relative who typed `Rose@` at join and `rose@` here has not given the product a
    second address to prove anything about."""
    member = _member("rose", "Rose Reed", pod=pod)
    EmailAddress.objects.create(
        user=member.user, email="Rose@example.com", primary=True, verified=True
    )
    mail.outbox.clear()

    subscription = digesting.subscribe(member, address="rose@example.com", cadence="weekly")
    assert mail.outbox == []
    assert subscription.confirmed_at is not None


# --- a different address is a different fact ------------------------------------------


def test_a_different_address_still_gets_its_own_confirmation(pod: Pod) -> None:
    member = _member("cousin", "Cousin Reed", pod=pod)
    EmailAddress.objects.create(
        user=member.user, email="cousin@example.com", primary=True, verified=True
    )
    mail.outbox.clear()

    subscription = digesting.subscribe(
        member, address="somewhere-else@example.com", cadence="weekly"
    )

    assert len(mail.outbox) == 1, [m.subject for m in mail.outbox]
    assert mail.outbox[0].to == ["somewhere-else@example.com"]
    assert subscription.confirmed_at is None, (
        "a verified address proved nothing about a DIFFERENT mailbox, and the Family email "
        "is now pointed at the unproven one"
    )


def test_a_member_with_no_login_is_unaffected(pod: Pod) -> None:
    """An elder or a supervised child has no sign-in address, so there is nothing to
    collapse and the ordinary confirmation stands."""
    nana = Member.objects.create(display_name="Rose Reed", kinship_name="Nana")
    PodMembership.objects.create(member=nana, pod=pod)
    mail.outbox.clear()

    subscription = digesting.subscribe(nana, address="nana@example.com", cadence="weekly")
    assert len(mail.outbox) == 1
    assert subscription.confirmed_at is None


# --- what one tap must NOT prove ------------------------------------------------------


def test_confirming_my_address_never_starts_somebody_elses_family_email(pod: Pod) -> None:
    """CROSS-MEMBER. Two relatives in one household share a mailbox — a couple, or a
    parent and a child — which is the ordinary case, not a contrived one."""
    mine = _member("cousin", "Cousin Reed", pod=pod)
    theirs = _member("sam", "Sam Reed", pod=pod)
    shared = "thereeds@example.com"

    my_row = EmailAddress.objects.create(user=mine.user, email=shared, primary=True, verified=False)
    EmailAddress.objects.create(user=theirs.user, email=shared, primary=True, verified=False)
    digesting.subscribe(mine, address=shared, cadence="weekly")
    digesting.subscribe(theirs, address=shared, cadence="weekly")

    _confirm_the_signin_address(my_row)

    assert DigestSubscription.objects.get(member=mine).confirmed_at is not None
    assert DigestSubscription.objects.get(member=theirs).confirmed_at is None, (
        "confirming one member's address started another member's Family email"
    )


def test_confirming_one_of_my_addresses_never_starts_a_family_email_at_another(
    pod: Pod,
) -> None:
    """CROSS-ADDRESS. The whole point of the confirmation is that family content follows
    only a mailbox somebody proved. A member can hold two addresses — one at work, one at
    home — and proving the first says nothing about the second."""
    member = _member("cousin", "Cousin Reed", pod=pod)
    work = EmailAddress.objects.create(
        user=member.user, email="work@example.com", primary=True, verified=False
    )
    EmailAddress.objects.create(user=member.user, email="home@example.com", verified=False)
    digesting.subscribe(member, address="home@example.com", cadence="weekly")

    _confirm_the_signin_address(work)

    assert DigestSubscription.objects.get(member=member).confirmed_at is None, (
        "confirming the work address turned on a Family email pointed at the home one"
    )


def test_the_family_email_confirmation_does_not_verify_a_sign_in_address(pod: Pod) -> None:
    """ONE-DIRECTIONAL, deliberately. That tap proves the same fact, but sign-in
    verification is what "Forgot your password?" trusts, and widening what can set it is
    blast radius this item does not need."""
    nana = Member.objects.create(display_name="Rose Reed", kinship_name="Nana")
    PodMembership.objects.create(member=nana, pod=pod)
    nana.user = User.objects.create_user(username="nana")
    nana.save(update_fields=["user"])
    row = EmailAddress.objects.create(
        user=nana.user, email="nana@example.com", primary=True, verified=False
    )
    # A subscription at that address whose confirm token is live, minted before the
    # sign-in row existed — so `subscribe` took the ordinary path and mailed a link.
    subscription = DigestSubscription.objects.create(
        member=nana,
        address="nana@example.com",
        cadence=DigestSubscription.WEEKLY,
        enabled=True,
        confirm_token_digest=digesting._digest("raw-confirm-value"),
        unsubscribe_token_digest=digesting._digest("raw-unsub-value"),
    )

    digesting.confirm("raw-confirm-value")

    subscription.refresh_from_db()
    row.refresh_from_db()
    assert subscription.confirmed_at is not None  # non-vacuity: the tap did land
    assert row.verified is False, "a Family email link verified a sign-in address"


def test_the_receiver_is_silent_rather_than_explosive_on_a_stranger(pod: Pod) -> None:
    """It runs inside allauth's confirmation view. A member's Family email preference must
    never be able to turn somebody's address confirmation into an error page."""
    from core.signals import confirm_the_family_email_at_the_same_address

    orphan = User.objects.create_user(username="no-member")
    row = EmailAddress.objects.create(user=orphan, email="nobody@example.com", verified=True)

    confirm_the_family_email_at_the_same_address(sender=EmailAddress, email_address=row)
    confirm_the_family_email_at_the_same_address(sender=EmailAddress, email_address=None)
