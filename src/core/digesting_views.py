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
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render

from . import digesting
from .feed_views import _acting_member
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
    # Enrollment can emit an email to an arbitrary address, so it rides the same
    # shared-cache rate limit as the other outbound-shaped endpoints (security
    # review of #35 MEDIUM-2: without this, a logged-in member is an unthrottled
    # bombardment primitive against a third party's mailbox and the instance's
    # own sender reputation). The join view sets the precedent (join.py).
    # reset_password is the email-emitting limit shape: per-IP plus per-key, and
    # keying on the member caps how fast any one account can make us send.
    if not ratelimit.consume(request, action="reset_password", key=str(member.pk)):
        return cast(HttpResponse, ratelimit.respond_429(request))  # allauth is untyped
    address = request.POST.get("address", "").strip()[:254]
    if not address or "@" not in address:
        return render(
            request,
            "core/digest_settings.html",
            {
                "member": member,
                "subscription": subscription,
                "sent": False,
                "error": "That does not look like an email address.",
            },
        )
    subscription = digesting.subscribe(
        member, address=address, cadence=request.POST.get("cadence", "")
    )
    # "sent" is honest: a cadence tweak on a confirmed address sends no email, so
    # the page must not tell the member to go look for one.
    return render(
        request,
        "core/digest_settings.html",
        {
            "member": member,
            "subscription": subscription,
            "sent": subscription.confirmed_at is None,
            "saved": True,
        },
    )


def confirm_digest(request: HttpRequest, token: str) -> HttpResponse:
    """Acknowledge an address (T-EMAIL-6). GET shows the button; POST confirms."""
    try:
        if request.method == "POST":
            digesting.confirm(token)
            return render(request, "core/digest_confirm.html", {"done": True})
        digesting.peek_confirmation(token)
    except digesting.DigestTokenInvalid as exc:
        raise Http404 from exc
    return render(request, "core/digest_confirm.html", {"done": False})


def unsubscribe_digest(request: HttpRequest, token: str) -> HttpResponse:
    """The two-step unsubscribe (S-501): GET asks, POST turns the digest off.
    Membership is untouched; this only stops the email."""
    try:
        if request.method == "POST":
            digesting.unsubscribe(token)
            return render(request, "core/digest_unsubscribe.html", {"done": True})
        digesting.peek_unsubscribe(token)
    except digesting.DigestTokenInvalid as exc:
        raise Http404 from exc
    return render(request, "core/digest_unsubscribe.html", {"done": False})
