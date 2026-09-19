"""Cross-cutting signal handlers.

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
