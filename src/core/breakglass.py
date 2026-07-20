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

from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

if TYPE_CHECKING:
    from django.contrib.auth.models import User as UserModel

User = get_user_model()


def _resolve_admin(uidb64: str, token: str) -> UserModel | None:
    """Return the admin iff the uid decodes to an existing superuser AND the token
    is valid for them; else None. Every failure returns None so the 404 is uniform."""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid, is_superuser=True)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return None
    if not default_token_generator.check_token(user, token):
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
