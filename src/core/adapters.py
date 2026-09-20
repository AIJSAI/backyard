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
from allauth.account.models import EmailAddress
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.mfa.adapter import DefaultMFAAdapter
from allauth.mfa.models import Authenticator
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest
from django.urls import reverse
from django.utils.safestring import mark_safe

from core import emailing, handover


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

    def send_mail(self, template_prefix: str, email: str, context: dict[str, Any]) -> None:
        """Every mail allauth composes, with its one action link under one name.

        The shared HTML shell (core/email/_layout.html) prints the action link twice — in
        the button, and again in the fallback line under it that a client refusing to draw
        a button leaves a locked-out reader with — so it needs the link as a value. allauth
        calls it `activate_url` in the confirmation and `password_reset_url` in the reset,
        and normalising that difference here keeps it in one place rather than in each
        template.

        BOTH LINKS ARE RE-BASED ON BASE_URL (TS-DJ-14). allauth builds them from the
        request's Host header; core.emailing mints every other link in this product from
        the configured base and takes no request on purpose, because a Host-poisoned link
        in mail is the classic emailed-link attack. Reconciled here, where the link is
        already in hand, and the .txt part gets the same cure as the button.

        `signup_url` is deliberately NOT mapped: it is the only link in the unknown-account
        reply, signup is closed in this product, and a button pointing at a refusal is
        worse than no button. A message with neither key simply gets no `action_url`, and
        the shell draws none.
        """
        rebased = {
            key: emailing.rebase_url(context[key])
            for key in ("activate_url", "password_reset_url")
            if context.get(key)
        }
        link = rebased.get("activate_url") or rebased.get("password_reset_url")
        super().send_mail(
            template_prefix,
            email,
            {**context, **rebased, "action_url": link} if link else context,
        )

    def confirm_email(self, request: HttpRequest, email_address: EmailAddress) -> bool:
        """A confirmation link proves control of a MAILBOX. It must not prove an ACCOUNT.

        core/join.py stores the address a relative types as `verified=False` "so a typo
        cannot silently hand recovery of this account to whoever owns the address that was
        actually typed", and core.forms.ResetPasswordForm mails a reset link only to a
        confirmed address. Both are undone if the stranger who receives the join-time
        confirmation mail can flip `verified` himself: allauth's confirmation view is
        `login_not_required`, so he could confirm, ask for a reset, and receive the link in
        his own inbox. Measured end to end on 2026-09-19, in a throwaway database: a
        password was set by a session that never signed in as anybody, and nothing was
        mailed to the member it belonged to.

        So the flip requires a session already signed in as the address's own user.
        Anybody else is sent to sign in and lands back on this same link: it costs the
        honest relative who opens the mail on another device one sign-in, with a password
        they chose minutes ago, and it costs the stranger everything, because he cannot
        sign in at all. A visitor signed in as somebody ELSE has already been signed out by
        the view's own logout_other_user on the GET before this runs.

        ImmediateHttpResponse rather than a False return: allauth's AccountMiddleware turns
        it into this response, and ATOMIC_REQUESTS rolls the request back on the way out, so
        a refused confirmation writes nothing and says nothing.

        This covers every path that flips `verified` in THIS configuration: the link and
        verification by code both arrive here. allauth's `verify_email_indirectly` bypasses
        this hook, and it is reached only from ACCOUNT_LOGIN_BY_CODE_ENABLED and
        ACCOUNT_PASSWORD_RESET_BY_CODE_ENABLED. Both are off, a test holds them off, and
        they must stay off (or grow their own check) for this guarantee to hold.

        It also protects Email Updates: core/signals.py starts them when a PRIMARY address
        is confirmed, so a stranger's tap used to start family posts flowing to his mailbox.
        """
        if request.user.is_authenticated and request.user.pk == email_address.user_id:
            return bool(super().confirm_email(request, email_address))
        raise ImmediateHttpResponse(
            redirect_to_login(request.get_full_path(), reverse("account_login"))
        )


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
        # A COUNT IS NOT A NAME. Counting reuses a number the moment a key is removed, so
        # losing a phone and enrolling its replacement produced two rows called "Passkey 2",
        # and on Remove This Passkey? the name is the only thing telling them apart. Take
        # the lowest number no existing key of this type is using.
        taken = {
            # .data.get, not .wrap().name: the authenticator-app and recovery-code wrappers
            # carry no name at all and this hook accepts any type. A row with no name takes
            # part in nothing rather than 500-ing the Add A Passkey page.
            authenticator.data.get("name")
            for authenticator in Authenticator.objects.filter(user_id=user.pk, type=type)
        }
        number = 1
        while f"Passkey {number}" in taken:
            number += 1
        return f"Passkey {number}"

    def build_totp_svg(self, url: str) -> str:
        """The authenticator-app QR as INLINE SVG: one of the two audited mark_safe sites over
        qr_svg output (the other, and the reasoning, is core/handover.py).

        allauth's template puts this SVG in an <img> as a `data:` URI, and this product's
        Content-Security-Policy is `img-src 'self' blob:` on purpose (core/middleware.py
        says why `data:` stays out). So the page said "Scan this QR code" above an empty
        box. The hand-over pages already draw their QR inline, which needs no img-src at
        all; this is the same function. The only input is the otpauth URL, rendered as
        qrcode's own path geometry and never as text, so nothing a person typed reaches
        the markup. The view still base64-encodes the return value for the data URI it no
        longer uses; a SafeString is a str, so that keeps working.
        """
        return mark_safe(handover.qr_svg(url))  # noqa: S308  # nosec
