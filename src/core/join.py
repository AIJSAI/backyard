"""The invite signup view (S-101): invite link to standing in a pod.

This is the custom view ADR-002 named, needed because allauth's own passkey
signup forces email verification that invite-token signup (email optional)
cannot meet. It carries the four TS-DJ-5 security properties:

1. The invite is consumed atomically under a row lock (redeem_invite), so a
   one-use invite mints exactly one member even under a race.
2. Every unusable-invite path (unknown, expired, revoked, exhausted) returns the
   same 404 as an unknown route, so the page is not an invite-existence oracle.
3. The endpoint carries allauth's login rate limit, so it cannot be hammered.
4. Account creation and invite consumption are one transaction: if either fails,
   neither lands, so a taken username never burns the invite.

Loading the page (GET) never consumes the invite; only the explicit join POST
does. Passkey enrollment is offered after the account exists (a follow-up); this
view establishes the account with a password so the member can always get back in.
"""

from __future__ import annotations

from typing import cast

from allauth.core import ratelimit
from django.contrib.auth import get_user_model, login
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from . import invites
from .models import Member

User = get_user_model()
_username_validator = UnicodeUsernameValidator()
_MODEL_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _validate(display_name: str, username: str, password: str) -> list[str]:
    errors: list[str] = []
    if not display_name:
        errors.append("Tell us the name your family will see.")
    elif len(display_name) > 100:
        # Guard length before the DB: the model field caps at 100 and an over-long
        # value would otherwise raise DataError (not IntegrityError) into a 500,
        # like the sibling setup view already guards (security review M1).
        errors.append("That name is too long (max 100 characters).")
    if not username:
        errors.append("Pick a username to sign in with.")
    elif len(username) > 150:
        errors.append("That username is too long (max 150 characters).")
    else:
        try:
            _username_validator(username)
        except ValidationError:
            errors.append("That username uses characters that are not allowed.")
    try:
        validate_password(password, User(username=username))
    except ValidationError as exc:
        errors.extend(exc.messages)
    return errors


def _create_account(token: str, display_name: str, username: str, password: str) -> Member:
    """Create the User and redeem the invite in one transaction (property 4)."""
    with transaction.atomic():
        user = User.objects.create_user(username=username, password=password)
        return invites.redeem_invite(token, display_name=display_name, user_id=user.id)


def join(request: HttpRequest, token: str) -> HttpResponse:
    # An already-signed-in member does not burn an invite by re-hitting the link.
    if request.user.is_authenticated:
        return redirect("home")

    # Property 2: a non-redeemable invite is a 404, identical to an unknown route.
    try:
        invites.peek_invite(token)
    except invites.InviteInvalid as exc:
        raise Http404 from exc

    errors: list[str] = []
    if request.method == "POST":
        # Property 3: the same rate limit as allauth's login endpoint.
        if not ratelimit.consume(request, action="login"):
            return cast(HttpResponse, ratelimit.respond_429(request))  # allauth is untyped

        display_name = request.POST.get("display_name", "").strip()
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        errors = _validate(display_name, username, password)
        if not errors:
            try:
                member = _create_account(token, display_name, username, password)
            except invites.InviteInvalid as exc:
                # The invite was consumed between the GET and now: still a 404.
                raise Http404 from exc
            except IntegrityError:
                errors.append("That username is already taken. Pick another.")
            else:
                login(request, member.user, backend=_MODEL_BACKEND)
                return redirect("home")
    return render(request, "core/join.html", {"errors": errors})
