"""The two pages of admin-issued password recovery (BY-01).

`issue_recovery` is the admin's: it mints one link for one member and shows it once,
with the shared hand-over block the invite and elder flows already use, because the
channel is the same — the admin texts it or reads it out. `recover` is the member's:
the link they were handed, exchanged for a new password.

Authorization is `permissions.can_manage_member`, which already draws exactly the line
this needs. A yard admin issues only for a plain member of their own yards (never a
peer admin, never the instance admin, never a bridging member who also belongs to the
other side); the instance admin issues for anyone except themselves — and for themselves
there is break-glass, which is console-only on purpose.

Deliberately NOT `can_provision_token`, which the elder link uses. That check is
stricter because an elder link is a credential the ISSUER can open and read the target's
whole scope with. A recovery link is not: it grants one act, setting a password the
issuer does not learn, and using it ends every session the member had — so an admin who
redeemed one themselves would sign the member out rather than read their family quietly.

That signal is real and it is not proof, which the permission matrix now says in the same
words: an issuer can redeem, read, then mint a SECOND link and hand that one over, and the
member sees one unexplained sign-out. The authority rests on the judgement that a yard
admin who can already remove that member and delete their photographs is not held back by
a password reset, not on impersonation being impossible.
"""

from __future__ import annotations

from typing import cast

from allauth.core import ratelimit
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from . import permissions, recovery
from .context_processors import note_the_reader_holds_a_link
from .feed_views import _acting_member
from .handover import apply_token_body_headers, consume_intent, fresh_intent, link_artifacts


@login_required
def issue_recovery(request: HttpRequest, member_id: int) -> HttpResponse:
    """Show, and on demand mint, a one-time "get back in" link for one member."""
    actor = _acting_member(request)
    if not permissions.is_admin(actor):
        raise PermissionDenied
    # The administrable set 404s a member the actor cannot administer at all (any member
    # for the instance admin, yard-scoped for a yard admin), so a cross-yard target is
    # byte-identical to one that does not exist (S-202). can_manage_member then refuses a
    # target they can SEE but may not administer — a peer admin, or a bridging member.
    target = get_object_or_404(permissions.administrable_members(actor), pk=member_id)
    if not permissions.can_manage_member(actor, target):
        raise PermissionDenied
    # Named explicitly rather than left to issue()'s refusal, so this URL cannot mint by
    # hand what the roster does not offer — and named through the SAME predicate the roster
    # and the service read, so the three cannot drift apart. `recovery.is_recoverable`
    # carries the reasons: a supervised child is their parent's (TM-10), an elder holds a
    # token link instead of a password, and a removed member's account is already
    # deactivated, so the link would redeem and then strand them on the sign-in page.
    if not recovery.is_recoverable(target):
        raise Http404

    context: dict[str, object] = {"actor": actor, "target": target}
    if request.method == "POST" and consume_intent(
        request, f"recovery_intent:{target.id}", request.POST.get("intent")
    ):
        # Minting a password-setting capability is rate limited on the same shape as the
        # other credential-emitting endpoints (join, digest enrollment). Keyed on the
        # ACTOR: the thing worth bounding is how fast one admin account — or a session
        # somebody walked away from — can turn the roster into a pile of live links.
        if not ratelimit.consume(request, action="reset_password", key=str(actor.pk)):
            return cast(HttpResponse, ratelimit.respond_429(request))  # allauth is untyped
        raw = recovery.issue(target, issued_by=actor)
        context.update(link_artifacts(f"{settings.BASE_URL}/get-back-in/{raw}/"))
        context["minted"] = True
    # The nonce for the NEXT mint, set after any consume so it never clobbers the one just
    # submitted: a browser refresh replays a spent nonce and re-renders WITHOUT quietly
    # revoking the link the admin has already handed over.
    context["intent"] = fresh_intent(request, f"recovery_intent:{target.id}")

    response = render(request, "core/issue_recovery.html", context)
    # Carries the raw token in its BODY and hosts the mint form: the shared hand-over
    # hygiene set (no-store against a bfcache restore of a walked-away-from admin screen,
    # same-origin so the form POST is not CSRF-rejected on an Origin: null).
    return apply_token_body_headers(response)


def recover(request: HttpRequest, token: str) -> HttpResponse:
    """Set a new password from a handed-over recovery link.

    Unauthenticated by construction: the person opening it cannot sign in, which is why
    they were given it. Loading the page never consumes the link (a link preview or a
    mail scanner must not burn somebody's only way back in); only the explicit POST does.

    Every unusable-link shape answers the same bare 404 as an unknown route, so this is
    not an account-existence oracle.
    """
    # The bearer-surface limit rides `FamilyLinkThrottleMiddleware` (S2) and covers the
    # GET, which the `login` limit below exempts by design. Both apply to the POST: one
    # bounds the credential endpoint, the other bounds the link.
    try:
        live = recovery.resolve(token)
    except recovery.RecoveryInvalid as exc:
        raise Http404 from exc
    # A live get-back-in link, minted by an admin for this one person, so the help line
    # may name them — this is the page somebody reads when they are already locked out.
    note_the_reader_holds_a_link(request)

    errors: list[str] = []
    if request.method == "POST":
        # The same limit the sign-in and invite-join endpoints carry: this endpoint sets a
        # password, so it must not be hammerable.
        if not ratelimit.consume(request, action="login"):
            return cast(HttpResponse, ratelimit.respond_429(request))  # allauth is untyped
        password = request.POST.get("password", "")
        if password != request.POST.get("password_again", ""):
            # Checked BEFORE redeem, so a typo costs a re-type rather than the link. This
            # link is single use and there is no "forgot your password" behind it -- a new
            # password with a typo in it that they cannot reproduce locks them out again
            # and costs another phone call to an admin.
            errors.append("The passwords do not match.")
        else:
            try:
                recovery.redeem(token, password)
            except ValidationError as exc:
                errors.extend(exc.messages)
            except recovery.RecoveryInvalid as exc:
                # Consumed or revoked between the GET and now: still the uniform 404.
                raise Http404 from exc
            else:
                # WHERE THIS USED TO END: a bare redirect to a blank sign-in form. The
                # button said "Save it and sign in", and then the page said nothing at all
                # — no confirmation that the password had saved, and an empty username box
                # in front of somebody who, by construction, has NO EMAIL ON FILE. That is
                # who this link exists for: the relatives who cannot use "Forgot your
                # password?" because there is nothing to send it to. Half of them do not
                # know what username an admin typed for them a year ago.
                #
                # So the sign-in page is told two things, and both are one-shot:
                #   * a flash naming what happened and who to sign in as, and
                #   * the username itself, which core.forms.LoginForm pops out of the
                #     session and prefills.
                #
                # Set HERE and nowhere else, which is the security property: this line is
                # only reachable after `redeem` has returned, and `redeem` returns only for
                # a live, unused, unexpired, un-superseded token. An invalid or replayed
                # link raises above and answers the same bare 404 as an unknown route, so
                # nothing on any failure path can be made to print a username.
                username = live.member.user.username if live.member.user else ""
                if username:
                    recovery.remember_the_recovered_username(request.session, username)
                    # "Password changed." and not "Password saved.": the same act on the
                    # emailed-reset path raises allauth's message from
                    # account/messages/password_changed.txt, which this product overrode to
                    # exactly that sentence. One act, one sentence, whichever way in.
                    messages.success(request, f"Password changed. Sign in as {username}.")
                return redirect("account_login")
    return render(
        request,
        "core/recover.html",
        {"display_name": live.member.display_name, "errors": errors},
    )
