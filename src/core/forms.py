"""Project overrides for django-allauth's forms.

Only copy, and only on the two surfaces a family member reaches without being signed
in. They shipped the library's developer-facing strings verbatim: "Login:",
"Password:", "Remember Me:", "Email:", with Django's default colon suffix, on a
product where every other string is written for a relative ("Share something with
your family", "Your backyard", "Stuck? Ask ..."). Nothing about the fields,
validation, or the auth path changes here; `label_suffix` and the labels do.

The colon is not a nitpick. "Email:" was the ONLY label in the product with one, on
the password-reset page — the screen somebody reaches when they are already locked
out and least able to shrug off a page that looks like somebody else's software.
"""

from __future__ import annotations

from typing import Any

from allauth.account.forms import LoginForm as AllauthLoginForm
from allauth.account.forms import ResetPasswordForm as AllauthResetPasswordForm


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
            self.fields["login"].label = "Your username or email"
        if "password" in self.fields:
            self.fields["password"].label = "Password"
        if "remember" in self.fields:
            self.fields["remember"].label = "Keep me signed in on this device"


class ResetPasswordForm(AllauthResetPasswordForm):  # type: ignore[misc]  # allauth is untyped
    """allauth's "forgot your password" form, with a label and no colon.

    The field stays `email` and the enumeration-safe behaviour is untouched: this
    changes what the label says and nothing about what the form does.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)
        if "email" in self.fields:
            self.fields["email"].label = "Email address"
            # The placeholder repeated the label word for word, which is the shape that
            # leaves somebody staring at a box whose hint vanishes the moment they type.
            self.fields["email"].widget.attrs["placeholder"] = "you@example.com"
