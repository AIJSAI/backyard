"""Digest lifecycle views (S-501): settings, confirm, unsubscribe.

The settings page is the member's own opt-in/out surface. The confirm and
unsubscribe pages are reached from email links, so they are unauthenticated and
token-resolved: an unknown, voided, or replayed token raises the same bare Http404
as everything else in the guard (no existence signal), and neither link acts on
GET — loading a page never confirms or severs; acting is an explicit POST, which
is also what keeps a mail scanner that prefetches links from acknowledging an
address it does not own (T-EMAIL-6).
"""

from __future__ import annotations

from typing import cast

from allauth.core import ratelimit
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from . import digesting
from .context_processors import note_the_reader_holds_a_link
from .feed_views import _acting_member
from .join import email_errors
from .models import DigestSubscription


@login_required
def digest_settings(request: HttpRequest) -> HttpResponse:
    """Opt in or adjust the digest (S-501): address, cadence, on/off."""
    member = _acting_member(request)
    subscription = DigestSubscription.objects.filter(member=member).first()
    if request.method != "POST":
        return render(
            request,
            "core/digest_settings.html",
            {"member": member, "subscription": subscription, "sent": False},
        )
    # On/off first, and deliberately BEFORE the rate limit below: this branch sends no
    # email, touches neither the address nor the confirmation, and is the control a member
    # reaches for when they want the digest to stop. Throttling it behind the
    # email-emitting limiter would mean "you have changed your address too often, so you
    # may not turn this off", which is the wrong answer to that request.
    action = request.POST.get("action", "")
    if action in {"turn_off", "turn_on"} and subscription is not None:
        subscription = digesting.set_enabled(subscription, enabled=action == "turn_on")
        return render(
            request,
            "core/digest_settings.html",
            {"member": member, "subscription": subscription, "sent": False, "saved": True},
        )

    # Enrollment can emit an email to an arbitrary address, so it rides the same
    # shared-cache rate limit as the other outbound-shaped endpoints (security
    # review of #35 MEDIUM-2: without this, a logged-in member is an unthrottled
    # bombardment primitive against a third party's mailbox and the instance's
    # own sender reputation). The join view sets the precedent (join.py).
    # reset_password is the email-emitting limit shape: per-IP plus per-key, and
    # keying on the member caps how fast any one account can make us send.
    if not ratelimit.consume(request, action="reset_password", key=str(member.pk)):
        return cast(HttpResponse, ratelimit.respond_429(request))  # allauth is untyped
    # THE ONE VALIDATOR, the same one the join form and the welcome step use. `"@" in
    # address` let "nana@gmail" and "a@" through, and the [:254] slice stored a DIFFERENT
    # address from the one typed. Both matter more now that the box is type="text": the
    # browser's own check is deliberately gone, so this is the only one there is.
    address = request.POST.get("address", "").strip()
    problems = email_errors(address) if address else ["Enter your email address."]
    if problems:
        return render(
            request,
            "core/digest_settings.html",
            {
                "member": member,
                "subscription": subscription,
                "sent": False,
                "error": problems[0],
            },
        )
    subscription = digesting.subscribe(
        member, address=address, cadence=request.POST.get("cadence", "")
    )
    # "SENT" IS READ OFF THE TOKEN, not off `confirmed_at`, and that is the whole fix.
    #
    # `subscribe` mints a confirm token only on the path that actually sends a mail. It
    # sends none on two other paths: a cadence tweak on an already-confirmed address, and
    # the same-address branch (walk item 24), where the account confirmation does the job
    # instead. `confirmed_at is None` cannot tell the last of those from a real send, so
    # this page told a member "Check <address> for one email" when no email existed —
    # and re-submitting the form took the same branch and sent nothing again, so the
    # Family email could never start. Reached whenever the join confirmation failed to
    # send (`join._send_confirmation` swallows every exception) or has aged past allauth's
    # three-day expiry. A live token is the only honest evidence that a mail went out.
    waiting_on_the_account_confirmation = (
        subscription.confirmed_at is None and not subscription.confirm_token_digest
    )
    return render(
        request,
        "core/digest_settings.html",
        {
            "member": member,
            "subscription": subscription,
            "sent": bool(subscription.confirm_token_digest),
            # The state that had no words: nothing was sent HERE, and nothing will be,
            # because the tap that starts this is the one already sitting in their inbox.
            # The page has to say which e-mail to look for and how to get another.
            "waiting_on_the_account_confirmation": waiting_on_the_account_confirmation,
            "saved": True,
        },
    )


def confirm_digest(request: HttpRequest, token: str) -> HttpResponse:
    """Acknowledge an address (T-EMAIL-6). GET shows the button; POST confirms.

    TWO PROOFS, NOT ONE. The token proves that whoever holds it controls that mailbox. It
    does not prove the mailbox is the one the member meant to type, and a mistyped address
    is delivered to a stranger, whose tap used to be the whole gate. Posts, names and next
    week's birthdays then went to him on every send, each carrying /d/ links that render
    that slice of the feed, with its replies and photos, to anybody who opens them.
    Measured end to end on 2026-09-19 in a throwaway database.

    So confirming also requires a session signed in as the member whose subscription this
    is. The stranger cannot supply one, so a mistyped address never starts, which is the
    right end for it; the member who typed the address they meant does receive the mail, so
    the honest path costs at most one sign-in. Nobody is locked out by this: `subscribe` has
    two callers and both are behind a sign-in, so no member without a login can have a
    subscription to confirm.

    The same rule, and the same reasoning, as core.adapters.AccountAdapter.confirm_email.
    Unsubscribe deliberately keeps ITS token as the only proof: stopping mail to a mailbox
    needs no more authority than holding that mailbox, and a stranger who wants out must
    always be able to get out.
    """
    # The token resolved (or was just burnt by confirming), so this reader holds a link a
    # relative's instance mailed to them and the help line may name whoever runs it. Set
    # inside the try, after the lookup: /digest/confirm/garbage/ 404s below and names
    # nobody. This is the surface the reviewer measured as WRONG the other way round —
    # a real link got the anonymous fallback because the old gate keyed on a URL prefix
    # that did not include this route.
    try:
        subscription = digesting.peek_confirmation(token)
        owner = subscription.member.user_id
        # SIGNED IN AS SOMEBODY ELSE IS NOT "SIGNED OUT", and bouncing them to sign in is a
        # loop with no exit: allauth sends an already-authenticated reader straight back to
        # `next`, which is this page, whose button bounces them again. Measured, twice
        # round, in silence, with the explanation hidden because it is written for a reader
        # who is signed out. A shared tablet, or a household mailbox one relative's phone is
        # signed into, makes that an ordinary Tuesday here. So they are told, on the page,
        # and nothing is written. Signing in is not their fix; signing OUT is. (The account
        # confirmation never had this problem only because allauth's own view signs the
        # other user out on the GET.)
        signed_in_as_somebody_else = request.user.is_authenticated and (
            owner is None or request.user.pk != owner
        )
        if request.method == "POST":
            if signed_in_as_somebody_else:
                note_the_reader_holds_a_link(request)
                return render(
                    request,
                    "core/digest_confirm.html",
                    {"done": False, "wrong_account": True},
                )
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path(), reverse("account_login"))
            digesting.confirm(token)
            note_the_reader_holds_a_link(request)
            return render(request, "core/digest_confirm.html", {"done": True})
        note_the_reader_holds_a_link(request)
    except digesting.DigestTokenInvalid as exc:
        raise Http404 from exc
    return render(
        request,
        "core/digest_confirm.html",
        {"done": False, "wrong_account": signed_in_as_somebody_else},
    )


def unsubscribe_digest(request: HttpRequest, token: str) -> HttpResponse:
    """The two-step unsubscribe (S-501): GET asks, POST turns the digest off.
    Membership is untouched; this only stops the email."""
    try:
        if request.method == "POST":
            digesting.unsubscribe(token)
            note_the_reader_holds_a_link(request)
            return render(request, "core/digest_unsubscribe.html", {"done": True})
        digesting.peek_unsubscribe(token)
        note_the_reader_holds_a_link(request)
    except digesting.DigestTokenInvalid as exc:
        raise Http404 from exc
    return render(request, "core/digest_unsubscribe.html", {"done": False})
