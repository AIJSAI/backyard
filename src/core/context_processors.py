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

from django.http import HttpRequest

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
    return Member.objects.filter(user=user).first()


def viewer(request: HttpRequest) -> dict[str, object]:
    """`viewer_member` and `viewer_is_admin`, for the site header.

    Named for the reader rather than for the model, because `member` alone is ambiguous in
    a template that is also rendering somebody else's member row — which the roster and the
    managed-profile pages both do.
    """
    member = _member_for(request)
    return {
        "viewer_member": member,
        "viewer_is_admin": member is not None and permissions.is_admin(member),
    }
