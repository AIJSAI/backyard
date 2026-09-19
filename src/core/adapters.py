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
        "username_password_mismatch": (
            'That username or password did not work. Try again, or use '
            '"Forgot your password?" below.'
        ),
        "email_password_mismatch": (
            'That email or password did not work. Try again, or use '
            '"Forgot your password?" below.'
        ),
        "incorrect_password": "That password did not match. Try again.",
        "too_many_login_attempts": (
            "That is a lot of tries in a row. Wait a few minutes and have another go."
        ),
    }

    def is_open_for_signup(self, request: Any) -> bool:  # noqa: ARG002
        return False
