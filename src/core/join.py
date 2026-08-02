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

import logging
from typing import cast

from allauth.account.models import EmailAddress
from allauth.core import ratelimit
from django.contrib.auth import get_user_model, login
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from . import invites, posting
from .models import Member

logger = logging.getLogger(__name__)
User = get_user_model()
_username_validator = UnicodeUsernameValidator()
_MODEL_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _validate(display_name: str, username: str, password: str, email: str) -> list[str]:
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
    # Email stays OPTIONAL (ACCOUNT_EMAIL_VERIFICATION = "optional"): an invite-token member
    # may genuinely not have one, which is the reason this custom view exists at all. But a
    # typo is worse than a blank, because it is a recovery path the member believes they have
    # and does not, so a value that IS given must parse.
    if email:
        if len(email) > 254:
            errors.append("That email address is too long (max 254 characters).")
        else:
            try:
                validate_email(email)
            except ValidationError:
                errors.append("That does not look like an email address.")
    return errors


def _create_account(
    token: str, display_name: str, username: str, password: str, email: str
) -> Member:
    """Create the User, redeem the invite, and post the arrival card, in one
    transaction (property 4, extended by S-905).

    The card is inside the transaction on purpose. Its only realistic failure is a
    database error, which would fail the join anyway — and a card written outside
    the transaction is a card that can silently not happen, which is the whole
    class of defect this project keeps finding. Either the member exists with an
    arrival card or neither exists.
    """
    with transaction.atomic():
        user = User.objects.create_user(username=username, password=password, email=email)
        if email:
            # WITHOUT this row, "Forgot your password?" is a dead end: allauth resolves a
            # reset against EmailAddress, not User.email, so a member who joined by invite
            # had no recovery path at all -- and ACCOUNT_PREVENT_ENUMERATION (correctly)
            # makes the reset page say "sent" either way, so they get no signal that they
            # are locked out. There is also no admin control to fix it afterwards.
            #
            # verified=False on purpose: the address is unconfirmed until they follow the
            # confirmation link, so a typo cannot silently hand recovery of this account to
            # whoever owns the address that was actually typed.
            EmailAddress.objects.create(user=user, email=email, primary=True, verified=False)
        # Read the invite's pod BEFORE consuming it: that is the household the card
        # belongs in, and it is the only source that cannot be wrong. If this peek
        # loses the race, redeem_invite raises on the next line and nothing lands.
        pod = invites.peek_invite(token).pod
        member = invites.redeem_invite(token, display_name=display_name, user_id=user.id)
        posting.announce_arrival(member, pod)
        return member


def join(request: HttpRequest, token: str) -> HttpResponse:
    # An already-signed-in member does not burn an invite by re-hitting the link; send
    # them to their feed, the member's landing surface (S-101), not the bare root.
    if request.user.is_authenticated:
        return redirect("feed")

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
        email = request.POST.get("email", "").strip()[:254]
        errors = _validate(display_name, username, password, email)
        if not errors:
            try:
                member = _create_account(token, display_name, username, password, email)
            except invites.InviteInvalid as exc:
                # The invite was consumed between the GET and now: still a 404.
                raise Http404 from exc
            except IntegrityError:
                errors.append("That username is already taken. Pick another.")
            else:
                login(request, member.user, backend=_MODEL_BACKEND)
                if email:
                    # AFTER the transaction, never inside it: a confirmation sent from within
                    # would survive a rollback and point at an account that does not exist.
                    # A mail failure must not undo a completed join either -- they are signed
                    # in and in the feed; an unconfirmed address is recoverable, a lost join
                    # is not.
                    try:
                        address = EmailAddress.objects.get(user=member.user, email=email)
                        address.send_confirmation(request, signup=True)
                    except Exception:  # noqa: BLE001 -- provider/transport, not our logic
                        logger.warning(
                            "join: confirmation email failed for member %s; the address is "
                            "saved but unverified",
                            member.pk,
                        )
                # S-101 acceptance: completing signup lands DIRECTLY in the pod feed, the
                # member's home surface, never a community-setup screen or a bare root.
                return redirect("feed")
    return render(request, "core/join.html", {"errors": errors})
