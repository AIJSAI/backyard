"""Cross-cutting signal handlers.

ONE TAP CONFIRMS BOTH (walk item 24): when a member verifies their sign-in address,
the Family email going to that same address is confirmed with it — see
`confirm_the_family_email_at_the_same_address` below for the whole argument.

Name hygiene (S3, review L3): every name a family reads — a member's display and kinship
name, a household's or group's name and house rule, and a side of the family's name, which
is the weekly email's subject line — is stripped of control and format characters on its
way into the database. A receiver, not a check in the profile editor,
because a display name is written from FIVE places — the first-run wizard, invite
redemption, the supervised-child form, the new-elder flow and the profile editor — and
the one that matters is whichever one a future change forgets. It matters because
`core/email/digest.txt` is a PLAIN-TEXT template and therefore renders with autoescape
off, so a bidi override in a name reversed the line it sat in for every recipient.

Elder-key cleanup on login (#42 review, the reverse direction of the HIGH):
Django's login() only flushes the session when a DIFFERENT auth user already
owned it, so an elder session that precedes a real login on the same browser
keeps its elder_* keys in the now-authenticated session. Those keys grant
nothing to an authenticated request (the elder views 404 a request whose
member has a login-backed path only through _elder_member, which still works,
but the point is hygiene: a logged-in session should carry no elder capability
state). Drop them on every login so the two session identities never overlap.
"""

from __future__ import annotations

from typing import Any

from allauth.account.signals import email_confirmed
from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.http import HttpRequest

from . import emailing
from .models import Member, Pod, Yard

_ELDER_KEYS = ("elder_member_id", "elder_generation", "elder_big_text")
# The two name columns a family actually reads: the display name on every byline and in
# every directory row, and the kinship name beside it ("Nana").
_NAME_FIELDS = ("display_name", "kinship_name")
# The other two names a family reads. A side of the family and a household are named by
# an admin typing into a form, they render in `email/digest.txt` beside the display names
# — which is autoescape off, being plain text — and one of them is the digest's SUBJECT.
_POD_NAME_FIELDS = ("name", "house_rule")
_YARD_NAME_FIELDS = ("name",)


@receiver(pre_save, sender=Member, dispatch_uid="core.signals.strip_control_from_names")
def strip_control_from_names(sender: Any, instance: Member, **kwargs: Any) -> None:
    """Strip control and format characters from a member's names before they are stored.

    On the instance rather than in a service call, so it covers `Member.objects.create`
    as well as `save(update_fields=...)`. `Member.objects.update()` bypasses signals by
    design — nothing in this product writes a name that way, and the two places that use
    `update()` on Member write `token_generation` (revocation) and nothing else.
    """
    _strip_fields(instance, _NAME_FIELDS)


@receiver(pre_save, sender=Pod, dispatch_uid="core.signals.strip_control_from_pod_names")
def strip_control_from_pod_names(sender: Any, instance: Pod, **kwargs: Any) -> None:
    """The same rule for a household's or a group's name and its one-line house rule."""
    _strip_fields(instance, _POD_NAME_FIELDS)


@receiver(pre_save, sender=Yard, dispatch_uid="core.signals.strip_control_from_yard_names")
def strip_control_from_yard_names(sender: Any, instance: Yard, **kwargs: Any) -> None:
    """And for a side of the family, which is the digest's subject line."""
    _strip_fields(instance, _YARD_NAME_FIELDS)


def _strip_fields(instance: object, fields: tuple[str, ...]) -> None:
    for field in fields:
        value = getattr(instance, field, "")
        if value:
            setattr(instance, field, emailing.strip_control(value))


@receiver(user_logged_in)
def clear_elder_session_keys(
    sender: Any, request: HttpRequest | None = None, **kwargs: Any
) -> None:
    if request is None or not hasattr(request, "session"):
        return
    for key in _ELDER_KEYS:
        request.session.pop(key, None)


@receiver(email_confirmed)
def confirm_the_family_email_at_the_same_address(
    sender: Any, email_address: Any = None, **kwargs: Any
) -> None:
    """One tap on the account confirmation also starts the Family email (walk item 24).

    A relative who gave an address at join and then chose "weekly" on the welcome screen
    used to receive two messages a minute apart with the identical subject "Is this your
    email address?", threaded together by their mail client. Both asked for a tap; neither
    said which was which. `digesting.subscribe` now sends none of its own when the two
    addresses are the same, and this is the other half: the one confirmation they DID get
    turns the Family email on too.

    WHAT THIS IS ALLOWED TO CONCLUDE, and it is deliberately narrow. allauth's signal
    fires only after a confirmation link that was mailed TO `email_address.email` was
    opened, and that row is bound to one user. So the only fact established is "the person
    holding this link controls this address, and this address belongs to this user". This
    function therefore touches exactly one subscription — the one belonging to THAT user's
    member — and only when that subscription's own address is the same address, compared
    case-insensitively because a mailbox is.

    Which closes the two ways this could have gone wrong, both of which have tests:

      * CROSS-MEMBER: confirming my address can never start the Family email for anybody
        else, because the subscription is looked up by my member and nothing else.
      * CROSS-ADDRESS: confirming one of my addresses can never start a Family email
        pointed at a DIFFERENT address of mine — the very thing the confirmation exists to
        prevent, since family content would then follow an address nobody proved.

    It is also deliberately one-directional. Confirming the Family email does NOT verify
    the sign-in address: that tap proves the same fact, but sign-in verification is what
    "Forgot your password?" trusts, and widening what can set it is blast radius this item
    does not need.

    Silent when there is nothing to do, and never raises: this runs inside allauth's
    confirmation view, and a member's Family email preference must not be able to turn
    their address confirmation into an error page.
    """
    if email_address is None or getattr(email_address, "user_id", None) is None:
        return
    from django.utils import timezone

    from .models import DigestSubscription, Member

    member = Member.objects.filter(user_id=email_address.user_id).first()
    if member is None:
        return
    DigestSubscription.objects.filter(
        member=member,
        address__iexact=email_address.email,
        confirmed_at__isnull=True,
    ).update(
        confirmed_at=timezone.now(),
        # Burn any confirm token the subscription still holds: the address is proven, so a
        # link still sitting in an old mail must not remain a live credential.
        confirm_token_digest="",  # nosec B105
    )
