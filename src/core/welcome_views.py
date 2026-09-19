"""The welcome, shown once, right after someone joins (owner direction 7).

What was there before: join asked for a name, a username, a password and an email,
dropped the newcomer on the feed, and a green card at the top of it explained which
sides of the family they were in. It never said what this place IS, never offered the
Family email, and never helped with a first post — so the three things a relative
actually needs on day one were the three things nobody told them.

Three screens, in the order a person asks the questions:

  1. what this is          — two sentences, and nothing else on the screen
  2. the Family email      — weekly, monthly, or no thanks, address already filled in
  3. say hello             — a composer with a line already written, entirely optional

Every screen is skippable, and skipping is a real control with a real target, not a
small grey word in a corner. Nothing here is a tour: there are no dots, no step counts
and no way to be chased back into it.

SEEN-ONCE is `Member.orientation_dismissed_at`, reused rather than joined by a second
column (owner direction: "Reuse orientation_dismissed_at as the 'has seen the welcome'
marker"). Migration 0022 backfilled it for everyone who already existed, so the family
that is already here never sees this. It is stamped when somebody skips out, and when
screen three renders — by then they have seen all three, which is what the column is
claiming. It is NOT stamped on arrival: a refresh of screen one would then bounce them
to the feed mid-sentence.

These pages are deliberately not guarded on that stamp. A member who opens /welcome/
again gets the welcome again; nothing links to it, so this only happens if they went
looking, and an explainer is not something to be refused.
"""

from __future__ import annotations

from typing import cast

from allauth.account.models import EmailAddress
from allauth.core import ratelimit
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import digesting, scoping
from .feed_views import _acting_member
from .join import email_errors
from .models import DigestSubscription, Member, Pod

# What screen two offers. Daily is deliberately absent (owner direction 2): a family
# that posts occasionally has no use for it, and the model keeps the value valid for
# anyone who already chose it.
_CADENCES = {"weekly": DigestSubscription.WEEKLY, "monthly": DigestSubscription.MONTHLY}

# The line already in the box on screen three. A blank required textarea in front of
# somebody who has been in the product for ninety seconds is a test; a sentence they can
# change or delete is an invitation.
SUGGESTED_FIRST_LINE = "Hi everyone, I just joined."


def _mark_welcomed(member: Member) -> None:
    """They have seen it. Idempotent and non-re-stamping, exactly like the orientation
    dismissal this column used to serve: stamping twice would rewrite a truthful record
    of when they were first shown it."""
    Member.objects.filter(pk=member.pk, orientation_dismissed_at__isnull=True).update(
        orientation_dismissed_at=timezone.now()
    )


def _known_address(member: Member) -> str:
    """The address they typed at join, so screen two is already filled in.

    Both stores, because allauth writes one and `create_user` writes the other, and the
    join view sets both when an address is given. Never a guess: an empty string means
    the box is empty and they can type one or move on.
    """
    if member.user is None:
        return ""
    address = EmailAddress.objects.filter(user=member.user).order_by("-primary", "pk").first()
    if address is not None:
        return str(address.email)
    return str(member.user.email or "")


@login_required
def welcome(request: HttpRequest) -> HttpResponse:
    """Screen one: what this place is. Two sentences and two buttons."""
    member = _acting_member(request)
    return render(request, "core/welcome_what.html", {"member": member})


@login_required
@require_POST
def welcome_skip(request: HttpRequest) -> HttpResponse:
    """The Skip control on screens one and two. POST-only, so a link prefetch cannot
    dismiss the one thing a newcomer has not read yet — the same rule the orientation
    card was already under."""
    _mark_welcomed(_acting_member(request))
    return redirect("feed")


@login_required
def welcome_family_email(request: HttpRequest) -> HttpResponse:
    """Screen two: the Family email, offered once, at the only moment anyone is thinking
    about it.

    Choosing weekly or monthly enrolls through the ordinary opt-in path, so the address
    still gets its one content-free confirmation email and nothing from the family flows
    until they tap it (T-EMAIL-6). Choosing "No thanks" writes nothing at all and is
    never raised again; Settings can turn it on later.
    """
    member = _acting_member(request)
    context: dict[str, object] = {"member": member, "address": _known_address(member)}
    if request.method != "POST":
        return render(request, "core/welcome_email.html", context)

    choice = request.POST.get("choice", "")
    if choice == "no":
        return redirect("welcome_hello")
    cadence = _CADENCES.get(choice)
    if cadence is None:
        # Neither a cadence nor a refusal: a hand-made or half-submitted form. Ask again
        # rather than guessing which answer they meant about their own inbox.
        context["error"] = "Choose how often you would like it, or choose No thanks."
        return render(request, "core/welcome_email.html", context)

    # NOT truncated, and not checked for a bare "@". This is the address a Family email
    # will be sent to and the one that gets them back in if they forget their password, so
    # it goes through the join form's validator — the same words, the same rules, and a
    # refusal rather than a quiet rewrite of what they typed.
    address = request.POST.get("address", "").strip()
    problems = email_errors(address) if address else ["Tell us where to send it."]
    if problems:
        context["address"] = address
        context["error"] = problems[0]
        return render(request, "core/welcome_email.html", context)
    # Enrolling sends mail to an address the member typed, so it rides the same
    # outbound-shaped limit as the settings page and the join view: per IP and per
    # member, so no one account can make this instance send.
    if not ratelimit.consume(request, action="reset_password", key=str(member.pk)):
        return cast(HttpResponse, ratelimit.respond_429(request))  # allauth is untyped
    digesting.subscribe(member, address=address, cadence=cadence)
    return redirect("welcome_hello")


@login_required
def welcome_hello(request: HttpRequest) -> HttpResponse:
    """Screen three: say hello, or do not.

    The composer posts to the ordinary compose endpoint — one way to write a post, with
    one set of limits and one audience rule, and this screen is not allowed a second.
    Rendering this screen is what marks the welcome as seen: all three have now been in
    front of them, whether or not they write anything.
    """
    member = _acting_member(request)
    _mark_welcomed(member)
    households = list(scoping.visible_pods(member).filter(kind=Pod.HOUSEHOLD))
    if not households:
        # A member with no household pod yet (an unusual hand-made setup). Offer whatever
        # they can post to rather than a composer whose Post button would 404.
        households = list(scoping.visible_pods(member))
    return render(
        request,
        "core/welcome_hello.html",
        {
            "member": member,
            "households": households,
            "suggested_body": SUGGESTED_FIRST_LINE,
        },
    )
