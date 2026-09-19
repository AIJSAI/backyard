"""What the site header needs to know about the person reading it.

The header could not previously offer an admin link, because a template has no way to ask
"is this person an admin?" — `Member` is reachable as `user.member` through the O2O's
`related_name`, but the ROLE LADDER is not a field comparison. It is
`permissions._ADMIN_ROLES`, and writing `{% if user.member.role == 'yard_admin' %}` in a
template would fork that ladder into a fifth place, one the permission tests do not read.

So the ladder is asked, once, here.

The cost of not having this was not cosmetic. `/members/` and the ten routes behind it —
invite a household, add a grandparent, create a side of the family, outstanding invites,
elder links, set role — had **zero inbound links from anywhere a signed-in person already
was**. The nav offered Feed, Pods, Directory, Settings. Every template that links to
`members` is itself inside that cluster, so the component linked to itself and to nothing
else: a delegate could only get in by being told the literal URL out of band, and
`docs/runbooks/setting-up-your-side.md` told them "Members → Invite a household" as though
it were a menu item.
"""

from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest
from django.utils.functional import SimpleLazyObject

from core import permissions
from core.models import Member


def _member_for(request: HttpRequest) -> Member | None:
    """The Member behind the request, or None.

    Deliberately tolerant: this runs on EVERY template render, including error pages and
    the signed-out entrance, so it must never raise. An authenticated user with no Member
    is not supposed to happen for a real account, and it must not blank the header if it
    does.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None
    try:
        # The reverse one-to-one, not a fresh queryset. Django caches it on the instance, so
        # a view that has already touched `request.user.member` pays nothing here — and this
        # runs on EVERY render, including 404s. In this product a 404 is not exceptional: it
        # is the answer to every authorization denial (TM-2, `scoping._require`), and
        # `404.html` extends `base.html`, so an unconditional query here would be a query on
        # the hottest error path there is.
        #
        # `Member.objects.filter(user=user).first()` also raises on an authenticated but
        # unsaved user ("Model instances passed to related filters must be saved"), which
        # this form does not.
        member: Member = user.member
        return member
    except ObjectDoesNotExist:
        # An authenticated user with no Member. Not supposed to happen for a real account,
        # and it must not blank the header if it does.
        return None


def help_contact_name() -> str:
    """The first name of whoever runs this Backyard, for the footer's help line.

    "Stuck? Ask whoever in the family set this up." is true and impersonal, and on a
    family's app it reads like a support page. The person is a relative and has a name,
    so the footer says it: "Stuck? Ask Jim."

    Read from the DATABASE at render time, never hardcoded — this repository is public,
    and a relative's name does not belong in it. Empty when there is no instance admin
    with a display name (a bare instance, or an operator account created by the setup
    wizard with a username only), and the template falls back to the old sentence, which
    is the string WCAG SC 3.2.6 is pinned on.

    One indexed query on the hottest path in the app, so it is kept to the single column
    it needs. If that ever shows up in a profile it wants caching, not removing.
    """
    admin = (
        Member.objects.filter(role=Member.INSTANCE_ADMIN)
        .exclude(display_name="")
        .order_by("pk")
        .only("display_name")
        .first()
    )
    return admin.short_name if admin is not None else ""


def viewer(request: HttpRequest) -> dict[str, object]:
    """`viewer_member`, `viewer_is_admin` and `help_contact`, for the site chrome.

    Named for the reader rather than for the model, because `member` alone is ambiguous in
    a template that is also rendering somebody else's member row — which the roster and the
    managed-profile pages both do.
    """
    member = _member_for(request)
    return {
        "viewer_member": member,
        "viewer_is_admin": member is not None and permissions.is_admin(member),
        # Lazy: this processor runs on EVERY render, and in this product a 404 is not
        # exceptional — it is the answer to every authorization denial (TM-2). A template
        # that never prints the help line never pays for the lookup.
        "help_contact": SimpleLazyObject(help_contact_name),
    }
