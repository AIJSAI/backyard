"""Project overrides for django-allauth's forms.

Only copy, and only on the sign-in page — the first surface a family member ever
sees and the one they see most. It shipped the library's developer-facing strings
verbatim: "Login:", "Password:", "Remember Me:", with Django's default colon
suffix, on a product where every other string is written for a relative ("Share
something with your family", "Your backyard", "Stuck? Ask whoever in the family
set this up"). Nothing about the fields, validation, or the auth path changes
here; `label_suffix` and three labels do.
"""

from __future__ import annotations

from typing import Any

from allauth.account.forms import LoginForm as AllauthLoginForm


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
