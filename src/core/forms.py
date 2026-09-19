"""Project overrides for django-allauth's forms.

Only copy, and only on the two surfaces a family member reaches without being signed
in. They shipped the library's developer-facing strings verbatim: "Login:",
"Password:", "Remember Me:", "Email:", with Django's default colon suffix, on a
product where every other string is written for a relative. Nothing about the fields,
validation, or the auth path changes here; `label_suffix` and the labels do.

The labels are Title Case, like every other form label in the product (the copy pass,
2026-09-19: "Capitalise Every Word" in labels, headings and buttons). A label is a NOUN
and not a question, and it says only what the box wants.

The colon is not a nitpick. "Email:" was the ONLY label in the product with one, on
the password-reset page — the screen somebody reaches when they are already locked
out and least able to shrug off a page that looks like somebody else's software.
"""

from __future__ import annotations

from typing import Any

from allauth.account.forms import AddEmailForm as AllauthAddEmailForm
from allauth.account.forms import LoginForm as AllauthLoginForm
from allauth.account.forms import ResetPasswordForm as AllauthResetPasswordForm
from allauth.account.models import EmailAddress

from core.recovery import take_the_recovered_username


class LoginForm(AllauthLoginForm):  # type: ignore[misc]  # allauth is untyped
    """allauth's login form with the labels a family would write."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Django appends `label_suffix` (":" by default) to every rendered label.
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)
        # `login` is present whichever ACCOUNT_LOGIN_METHODS are configured; the
        # others are unconditional. Assign defensively anyway so an allauth upgrade
        # that renames a field degrades to the library's label rather than a
        # KeyError on the sign-in page.
        if "login" in self.fields:
            self.fields["login"].label = "Username Or Email"
            # WHOEVER JUST USED A GET-BACK-IN LINK ARRIVES HERE WITH AN EMPTY BOX.
            #
            # That link exists for the relatives who have no email address on file — so
            # "Forgot your password?" can never reach them — and a good share of them do
            # not know what username an admin typed for them a year ago. Before this, the
            # recovery flow ended on a blank sign-in form with no message, which is the
            # one screen where "what was my username again?" has no answer in the product.
            #
            # `recovery_views.recover` writes the name into the session only after
            # `recovery.redeem` has returned, which happens only for a live, unused,
            # unexpired link. An invalid or replayed link 404s before that line, so this
            # cannot be made to reveal a username for a token that was not just used.
            #
            # POPPED, not read, and honoured for ten minutes only: it prefills exactly one
            # render, and a stale stamp is dropped rather than used. Leaving it in the
            # session would put somebody's username into the box on every later visit from
            # that browser, including a visit by whoever borrows the tablet.
            request = getattr(self, "request", None)
            session = getattr(request, "session", None)
            if session is not None:
                recovered = take_the_recovered_username(session)
                if recovered:
                    self.fields["login"].initial = recovered
        if "password" in self.fields:
            self.fields["password"].label = "Password"
        if "remember" in self.fields:
            # "on this device" is what a browser checkbox always means, and saying it back
            # to an adult who has used phones for fifteen years is the filler the copy pass
            # was called for.
            self.fields["remember"].label = "Keep Me Signed In"


class AddEmailForm(AllauthAddEmailForm):  # type: ignore[misc]  # allauth is untyped
    """allauth's Add An Email Address form, with the product's label and no colon.

    The last stock Django label a relative reads, and the one this module missed: the
    docstring above names "Email:" as a string it exists to kill, then covers the login and
    reset forms only. ACCOUNT_FORMS overrode those two, so account/email.html — Your
    Sign-In Email, which every member with an address reaches from Settings — went on
    rendering the library's sentence-case label with Django's colon suffix.

    Nothing about the field, its validation or the confirmation flow changes.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)
        if "email" in self.fields:
            self.fields["email"].label = "Email Address"
            # allauth's own placeholder is "Email address", the label word for word. A
            # placeholder is a format example here or it is nothing.
            self.fields["email"].widget.attrs["placeholder"] = "you@example.com"


class ResetPasswordForm(AllauthResetPasswordForm):  # type: ignore[misc]  # allauth is untyped
    """allauth's "forgot your password" form, with a label, no colon, and one rule.

    THE RULE: a reset link is mailed only to an address its owner has CONFIRMED.

    allauth looks the typed address up with `prefer_verified=True`, which prefers a
    confirmed row and falls back to an unconfirmed one. core/join.py stores the address a
    relative types at join as `verified=False` "so a typo cannot silently hand recovery of
    this account to whoever owns the address that was actually typed", and the fallback
    undid exactly that: the stranger who owns the mistyped mailbox first receives the
    confirmation mail, which names this site, and could then ask for a reset of an account
    that is not theirs and be sent one. Measured on 2026-09-19 during the review of #209.

    So the users allauth found are narrowed to those holding a confirmed EmailAddress row
    for this exact address. Nothing else moves, and the page cannot tell the two cases
    apart: with no user left, allauth sends its "unknown account" mail to the typed
    address and redirects to the same "sent" page, which is what ACCOUNT_PREVENT_ENUMERATION
    is for. A member whose only address is unconfirmed confirms it (the mail can be sent
    again from Your Sign-In Email) or asks an admin for a Sign-In Link.
    """

    def clean_email(self) -> str:
        value: str = super().clean_email()
        confirmed = set(
            EmailAddress.objects.filter(email__iexact=value.strip(), verified=True).values_list(
                "user_id", flat=True
            )
        )
        # allauth is untyped, so `users` has no declared type for mypy to narrow from.
        found: list[Any] = list(getattr(self, "users", []))
        self.users = [user for user in found if user.pk in confirmed]
        return value

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)
        if "email" in self.fields:
            self.fields["email"].label = "Email Address"
            # The placeholder repeated the label word for word, which is the shape that
            # leaves somebody staring at a box whose hint vanishes the moment they type.
            self.fields["email"].widget.attrs["placeholder"] = "you@example.com"
