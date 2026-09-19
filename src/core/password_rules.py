"""The four password rules, in one plain sentence each.

Django says every rule twice and in two voices: a help text written for a form ("Your
password can't be too similar to your other personal information.") and a refusal written
for a developer ("This password is too short. It must contain at least 8 characters."). A
relative meets those sentences on the join form, the setup form, the get-back-in page, the
emailed reset and the signed-in password change, and none of them is a sentence this
product would write.

WHAT CHANGES HERE IS THE WORDS AND ONLY THE WORDS. Every class below inherits Django's own
`validate`, so the decision to refuse a password is still the library's, byte for byte --
the same comparison, the same 20000-password list, the same similarity ratio, the same
`code` on the raised error. Django 5 routes both sentences through `get_error_message` and
`get_help_text`, which is why this file is two overrides per rule and no re-implemented
check.

The error and the help text are the SAME sentence in each class. Two wordings of one rule
is how somebody ends up reading the rule twice and believing there are two of them.

None of this is read before anybody types: the hint on every form that asks for a password
is "Choose a memorable password." and nothing else, so these four sentences appear only as
the answer to a password that was actually refused.
"""

from __future__ import annotations

from django.contrib.auth import password_validation


class MinimumLength(password_validation.MinimumLengthValidator):
    """Django's length check, saying the length once."""

    def get_error_message(self) -> str:
        return f"Password must be at least {self.min_length} characters."

    def get_help_text(self) -> str:
        return self.get_error_message()


class NotYourOwnDetails(password_validation.UserAttributeSimilarityValidator):
    """Django's similarity check.

    Its own sentence names the field it matched ("too similar to the username"), which
    reads as an accusation and is also a small piece of account information to print on a
    page anybody can reach. The three attributes it compares against are named plainly
    instead, and the reader is told what to do.
    """

    def get_error_message(self) -> str:
        return "Password must be different from your name, username and email address."

    def get_help_text(self) -> str:
        return self.get_error_message()


class NotACommonPassword(password_validation.CommonPasswordValidator):
    """Django's common-password list. The likeliest refusal a first-time relative meets."""

    def get_error_message(self) -> str:
        return "That password is too common. Choose another one."

    def get_help_text(self) -> str:
        return self.get_error_message()


class NotAllNumbers(password_validation.NumericPasswordValidator):
    """Django's all-digits check."""

    def get_error_message(self) -> str:
        return "Password must not be all numbers."

    def get_help_text(self) -> str:
        return self.get_error_message()
