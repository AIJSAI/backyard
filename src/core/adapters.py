"""allauth adapters: account creation is invite-only (S-101).

allauth mounts an open signup view by default. Backyard never lets a stranger
create an account: the only path that mints a member is the invite redemption
(core/invites.py), which lands as a custom view. Closing allauth's signup here
means the open form renders a "closed" page and any signup POST creates nothing,
so there is no self-serve account surface for a scanner or curious teen to hit
(T-INVITE-1, T-YARD-G1).
"""

from __future__ import annotations

from typing import Any

from allauth.account.adapter import DefaultAccountAdapter
from allauth.mfa.adapter import DefaultMFAAdapter
from allauth.mfa.models import Authenticator
from django.contrib.auth.base_user import AbstractBaseUser

from core import emailing


class AccountAdapter(DefaultAccountAdapter):  # type: ignore[misc]  # allauth is untyped
    # The words a relative reads when something goes wrong. allauth's own are written for
    # an account system — "The username and/or password you specified are not correct." is
    # the commonest failure in the whole product, and it audits the reader instead of
    # telling them what to do next. Only the four they can actually hit are replaced; the
    # rest of the library's messages stand.
    #
    # Overriding the TEXT changes nothing about the behaviour: the two mismatch messages
    # stay identical to each other and to the unknown-account case, so
    # ACCOUNT_PREVENT_ENUMERATION still gives one answer for a wrong password and for a
    # username nobody has.
    error_messages = {
        **DefaultAccountAdapter.error_messages,
        # The control is quoted by its own name: the sign-in page's reset link reads
        # "Forgot Your Password?" (account/password_reset_help_text.html), and an error
        # that tells somebody to use a control spells it the way the screen spells it.
        "username_password_mismatch": (
            'That username or password is not correct. Use "Forgot Your Password?" to reset it.'
        ),
        "email_password_mismatch": (
            "That email address or password is not correct. "
            'Use "Forgot Your Password?" to reset it.'
        ),
        "incorrect_password": "That password is not correct.",
        "too_many_login_attempts": "Too many sign-in attempts. Wait a few minutes and try again.",
    }

    def is_open_for_signup(self, request: Any) -> bool:  # noqa: ARG002
        return False

    def get_from_email(self) -> str:
        """The same From identity the rest of the product sends under (walk item 23).

        allauth composes its own mail — the address confirmation at join, the password
        reset — and does NOT go through core.emailing.send_family_email, so these two were
        the only messages a family receives that arrived with a bare address and no name.
        The first of them is often the very first thing this product ever sends anybody.

        One line, delegating to the one function that builds the header, rather than
        reading the settings again here: a second place that assembles a From address is
        a second place for the two to disagree.
        """
        return emailing.from_address()


class MFAAdapter(DefaultMFAAdapter):  # type: ignore[misc]  # allauth is untyped
    """The name prefilled in the Add A Passkey box.

    The last stock allauth string a relative reads on the passkey screens, and the only one
    not in a template: allauth prefills "Master key", then "Backup key", then "Key nr. 3".
    Two of those are claims about a key's importance that nothing in this product enforces
    — any passkey signs you in — and all three use the library's word for the object where
    every screen here says passkey. It is also STORED, so it is what the Passkeys list
    shows for ever after.

    The field stays optional, exactly as the package leaves it: the WebAuthn ceremony
    completes before the POST, so a blank name must still save.
    """

    # The library's words on the two-step screens, and the siblings of the four
    # AccountAdapter replaces above. One of them is captured on a real screen: "You cannot
    # activate two-factor authentication until you have verified your email address." is
    # the loudest thing on the page, and it breaks three rules at once. "Two-factor
    # authentication" appears on no screen in this product — the page is called Passkeys
    # And Sign-In Codes — an address here is CONFIRMED and never "verified", and an error
    # is what is wrong PLUS the fix, where all five of allauth's state a rule and stop.
    # Same treatment as the account errors, and nothing about the behaviour changes: these
    # are the text of a refusal, not the refusal.
    error_messages = {
        **DefaultMFAAdapter.error_messages,
        "add_email_blocked": (
            "Remove your passkeys and authenticator app before adding an email address."
        ),
        "cannot_delete_authenticator": "That sign-in method cannot be turned off.",
        "cannot_generate_recovery_codes": (
            "Add a passkey or an authenticator app before creating recovery codes."
        ),
        "incorrect_code": "That code is not correct.",
        "unverified_email": (
            "Confirm your email address first. Open Your Sign-In Email in Settings."
        ),
    }

    def generate_authenticator_name(self, user: AbstractBaseUser, type: Authenticator.Type) -> str:
        count = Authenticator.objects.filter(user_id=user.pk, type=type).count()
        return f"Passkey {count + 1}"
