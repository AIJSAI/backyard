"""The break-glass reset view (S-805): consumes a console-minted token only.

This view sets a new password for an admin, gated by a token that ONLY the
break_glass management command produces. There is deliberately no view that mints
such a token, so there is no web or email "recover admin" path (T-AUTH-G1). A
valid token proves the operator ran the console command, which proves server
shell access, the same trust anchor as first-run setup.

On success the reset revokes the admin's other sessions (a stolen session cannot
survive a recovery) and the token itself dies (Django's generator hashes the
password, so the new password invalidates it).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.crypto import constant_time_compare
from django.utils.encoding import force_str
from django.utils.http import base36_to_int, urlsafe_base64_decode

if TYPE_CHECKING:
    from django.contrib.auth.models import User as UserModel

User = get_user_model()


class BreakGlassTokenGenerator(PasswordResetTokenGenerator):
    """Django's reset token, but with a much shorter lifetime than the global
    PASSWORD_RESET_TIMEOUT (security review MEDIUM-1). A console-minted admin reset
    URL is meant to be opened within minutes, not the 3-day default, and it must
    not couple to allauth's member password-reset link lifetime. The one-time
    binding is inherited unchanged (the parent folds the password hash and
    last_login into the token, so the reset itself and any later login kill it);
    only the timeout differs, so this overrides check_token's final age check.
    """

    timeout = 30 * 60  # 30 minutes

    def check_token(self, user: Any, token: str | None) -> bool:
        if not (user and token):
            return False
        try:
            ts_b36, _ = token.split("-")
            ts = base36_to_int(ts_b36)
        except ValueError:
            return False
        for secret in [self.secret, *self.secret_fallbacks]:
            if constant_time_compare(self._make_token_with_timestamp(user, ts, secret), token):
                break
        else:
            return False
        return (self._num_seconds(self._now()) - ts) <= self.timeout


break_glass_tokens = BreakGlassTokenGenerator()


def _resolve_admin(uidb64: str, token: str) -> UserModel | None:
    """Return the admin iff the uid decodes to an existing superuser AND the token
    is valid for them; else None. Every failure returns None so the 404 is uniform."""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid, is_superuser=True)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return None
    if not break_glass_tokens.check_token(user, token):
        return None
    return user


def break_glass(request: HttpRequest, uidb64: str, token: str) -> HttpResponse:
    user = _resolve_admin(uidb64, token)
    if user is None:
        raise Http404  # unknown, tampered, or expired token: one uniform 404

    errors: list[str] = []
    if request.method == "POST":
        password = request.POST.get("password", "")
        try:
            validate_password(password, user)
        except ValidationError as exc:
            errors.extend(exc.messages)
        if not errors:
            user.set_password(password)
            user.save(update_fields=["password"])
            # Changing the password rotates the session auth hash, so EVERY existing
            # session for this admin (including one an attacker may hold) is invalid on
            # its next request (T-RECOV-1: reset revokes all sessions). The recovering
            # admin signs in fresh with the new password and re-enrolls a second factor.
            return redirect("account_login")
    return render(request, "core/break_glass.html", {"errors": errors})
