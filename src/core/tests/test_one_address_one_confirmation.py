"""One address, one proof: Email Updates and the sign-in address stop asking twice.

Walk item 24, 2026-09-19. A new relative who gave an e-mail address at join and then
picked "weekly" on the welcome screen received TWO messages inside a minute — one from
allauth for the sign-in address, one from `digesting` for Email Updates — with the
IDENTICAL subject "Is this your email address?", from the same sender, threaded together
by their mail client into what looked like one message sent twice. Both asked for a tap.
Neither said which was which, and tapping one left the other apparently unanswered.

The two subjects are no longer the same line either ("Confirm Your Email Address" and
"Confirm This Address For Email Updates"), so the rare case that still sends both — two
different mailboxes — arrives as two messages a reader can tell apart. The collapse below
is what stops the same mailbox being asked twice at all.

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
from django.test import Client
from django.urls import reverse
from django.utils import timezone

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


# --- the page must not name an e-mail that does not exist -----------------------------
#
# The HIGH finding of the review round. `subscribe` sends no mail on the same-address
# branch, but `digest_settings` decided "sent" from `confirmed_at is None` — which is also
# true on that branch — so the page said "Check <address> for one email" when none had
# been sent, and re-submitting the form took the same branch and sent nothing again. A
# member whose join confirmation failed (`join._send_confirmation` swallows every
# exception) or expired after allauth's three days could never start the Family email, and
# every screen told them to go and look for a message that did not exist.


def _signed_in(member: Member) -> Client:
    client = Client()
    assert member.user is not None
    client.force_login(member.user, backend="django.contrib.auth.backends.ModelBackend")
    return client


def test_the_settings_page_says_which_email_to_look_for_when_it_sent_none(pod: Pod) -> None:
    member = _member("cousin", "Cousin Reed", pod=pod)
    EmailAddress.objects.create(
        user=member.user, email="cousin@example.com", primary=True, verified=False
    )
    mail.outbox.clear()

    page = _signed_in(member).post(
        reverse("digest_settings"), {"address": "cousin@example.com", "cadence": "weekly"}
    )
    body = " ".join(page.content.decode().split())

    assert mail.outbox == []  # non-vacuity: this is the branch that sends nothing
    assert "A confirmation email has been sent to cousin@example.com." not in body, (
        "the page sends the member looking for an email it never sent"
    )
    assert "This is your sign-in address and it is not confirmed yet." in body
    assert "Confirming it starts email updates." in body
    # ...and a way to get another one, which is the only route forward if the join mail
    # failed or has expired.
    assert reverse("account_email") in body


def test_the_settings_page_still_says_check_your_inbox_when_it_did_send(pod: Pod) -> None:
    """Non-vacuity for the test above, on the path that really does send."""
    member = _member("cousin", "Cousin Reed", pod=pod)
    EmailAddress.objects.create(
        user=member.user, email="cousin@example.com", primary=True, verified=True
    )
    mail.outbox.clear()

    page = _signed_in(member).post(
        reverse("digest_settings"),
        {"address": "somewhere-else@example.com", "cadence": "weekly"},
    )
    body = " ".join(page.content.decode().split())

    assert len(mail.outbox) == 1
    assert "A confirmation email has been sent to somewhere-else@example.com." in body
    assert "This is your sign-in address" not in body


def test_a_cadence_tweak_on_a_confirmed_address_says_only_saved(pod: Pod) -> None:
    """The third state, and the one that was already right: nothing was sent and nothing
    is owed, so the page must claim neither."""
    member = _member("cousin", "Cousin Reed", pod=pod)
    EmailAddress.objects.create(
        user=member.user, email="cousin@example.com", primary=True, verified=True
    )
    digesting.subscribe(member, address="cousin@example.com", cadence="weekly")
    mail.outbox.clear()

    page = _signed_in(member).post(
        reverse("digest_settings"), {"address": "cousin@example.com", "cadence": "monthly"}
    )
    body = " ".join(page.content.decode().split())

    assert mail.outbox == []
    assert "Saved." in body
    assert "A confirmation email has been sent to cousin@example.com." not in body
    assert "This is your sign-in address" not in body


# --- store what was PROVEN, and never un-confirm it ------------------------------------


def test_the_subscription_stores_the_proven_spelling_not_the_typed_one(pod: Pod) -> None:
    """A member who signs in as `rose@` and types `ROSE@` has given the product one
    mailbox. Storing the typed string would point the subscription at a spelling nothing
    ever confirmed."""
    member = _member("rose", "Rose Reed", pod=pod)
    EmailAddress.objects.create(
        user=member.user, email="rose@example.com", primary=True, verified=True
    )

    subscription = digesting.subscribe(member, address="ROSE@example.com", cadence="weekly")
    assert subscription.address == "rose@example.com"
    assert subscription.confirmed_at is not None


def test_re_pointing_away_and_back_does_not_stop_the_family_email(pod: Pod) -> None:
    """`update_or_create` wrote `confirmed_at` unconditionally, so a member who changed
    their mind twice — or simply re-saved the form — had a working subscription silently
    set back to unconfirmed, with no token minted and therefore no way to confirm it
    again. Control of this mailbox by this member does not stop being proven because a
    form was submitted twice."""
    member = _member("cousin", "Cousin Reed", pod=pod)
    row = EmailAddress.objects.create(
        user=member.user, email="cousin@example.com", primary=True, verified=False
    )
    digesting.subscribe(member, address="cousin@example.com", cadence="weekly")
    _confirm_the_signin_address(row)
    assert DigestSubscription.objects.get(member=member).confirmed_at is not None

    # Away to a different mailbox (which needs its own proof), then back.
    digesting.subscribe(member, address="elsewhere@example.com", cadence="weekly")
    assert DigestSubscription.objects.get(member=member).confirmed_at is None
    digesting.subscribe(member, address="cousin@example.com", cadence="weekly")

    back = DigestSubscription.objects.get(member=member)
    assert back.address == "cousin@example.com"
    assert back.confirmed_at is not None, (
        "coming back to a mailbox this member already proved turned the Family email off "
        "with no way to turn it on again"
    )


# --- consent: a SECONDARY address is not collapsed ------------------------------------


def test_a_secondary_address_gets_its_own_content_free_confirmation(pod: Pod) -> None:
    """Collapsing the two confirmations is fair for the address a member signs in with and
    was told about at join. It is not fair for one they added later: the account mail for
    it would be the only thing they ever tapped, and nothing would have asked whether
    family content should start flowing there."""
    member = _member("cousin", "Cousin Reed", pod=pod)
    EmailAddress.objects.create(
        user=member.user, email="cousin@example.com", primary=True, verified=True
    )
    EmailAddress.objects.create(
        user=member.user, email="second@example.com", primary=False, verified=True
    )
    mail.outbox.clear()

    subscription = digesting.subscribe(member, address="second@example.com", cadence="weekly")

    assert len(mail.outbox) == 1, [m.subject for m in mail.outbox]
    assert mail.outbox[0].to == ["second@example.com"]
    assert subscription.confirmed_at is None, (
        "a secondary address started the Family email without anybody being asked"
    )


def test_confirming_a_secondary_account_address_starts_nothing(pod: Pod) -> None:
    member = _member("cousin", "Cousin Reed", pod=pod)
    EmailAddress.objects.create(
        user=member.user, email="cousin@example.com", primary=True, verified=True
    )
    second = EmailAddress.objects.create(
        user=member.user, email="second@example.com", primary=False, verified=False
    )
    digesting.subscribe(member, address="second@example.com", cadence="weekly")

    _confirm_the_signin_address(second)

    assert DigestSubscription.objects.get(member=member).confirmed_at is None, (
        "tapping the ACCOUNT link for a secondary address started the Family email"
    )


def test_the_account_mail_says_what_its_link_actually_does(pod: Pod) -> None:
    """A mail that understates what its own link does is a consent defect nobody notices
    until content arrives somewhere it was not expected."""
    from django.template.loader import render_to_string

    body = render_to_string(
        "account/email/email_confirmation_message.txt",
        {"activate_url": "https://example.test/confirm/x/", "current_site": None},
    )
    flat = " ".join(body.split())
    # Conditional, because the link starts Email Updates only for a PRIMARY address that
    # has them turned on; a flat promise was false for a secondary address.
    assert "Confirm this address to use it for password reset." in flat
    assert "If it is your primary address and you turned on email updates, they start too" in flat
    assert "Nothing else will be sent here" not in flat
    assert "Nothing else is sent to this address unless you ask for it" not in flat


def test_re_saving_an_already_confirmed_unverified_mailbox_keeps_it_on(pod: Pod) -> None:
    """The clause `own.verified` cannot cover. A subscription can be confirmed while the
    sign-in row is still unverified — it was confirmed by the digest's own token, minted
    before that row existed. Re-saving the settings form then takes the same-address
    branch, which mints no token, so an unconditional write would have turned the Family
    email off with nothing left to turn it back on."""
    member = _member("cousin", "Cousin Reed", pod=pod)
    subscription = DigestSubscription.objects.create(
        member=member,
        address="cousin@example.com",
        cadence=DigestSubscription.WEEKLY,
        enabled=True,
        confirmed_at=timezone.now(),
        confirm_token_digest="",  # nosec B105 - already burnt by confirming
        unsubscribe_token_digest=digesting._digest("raw-unsub"),
    )
    EmailAddress.objects.create(
        user=member.user, email="cousin@example.com", primary=True, verified=False
    )
    mail.outbox.clear()

    again = digesting.subscribe(member, address="cousin@example.com", cadence="monthly")

    assert mail.outbox == []
    assert again.pk == subscription.pk
    assert again.cadence == DigestSubscription.MONTHLY
    assert again.confirmed_at is not None, "re-saving the form turned the Family email off"
