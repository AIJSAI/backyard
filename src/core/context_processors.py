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

    "Need help? Contact the person who invited you." is true and impersonal, and on a
    family's app it reads like a support page. The person is a relative and has a name, so
    the footer says it: "Need help? Contact <first name>."

    Read from the DATABASE at render time, never hardcoded — this repository is public,
    and a relative's name does not belong in it. Empty when there is no instance admin
    with a display name (a bare instance, or an operator account created by the setup
    wizard with a username only), and the template falls back to the impersonal sentence,
    which is the string WCAG SC 3.2.6 is pinned on.

    One indexed query on the hottest path in the app, so it is kept to the single column
    it needs. If that ever shows up in a profile it wants caching, not removing.
    """
    # `user__is_active=True` is the load-bearing clause. Removal keeps the Member row and
    # deactivates the account (removal.py step 3), so without it the footer, the About page
    # and the password-reset guidance would go on telling relatives to ask somebody who can
    # no longer sign in — on the one screen a locked-out member reads. It also excludes a
    # row with no user at all, which cannot be running anything either.
    admin = (
        Member.objects.filter(role=Member.INSTANCE_ADMIN, user__is_active=True)
        .exclude(display_name="")
        .order_by("pk")
        .only("display_name")
        .first()
    )
    return admin.short_name if admin is not None else ""


# THE READER HOLDS A LINK, and the only thing that may set this is a view that has
# RESOLVED the token it was given.
#
# This used to be a tuple of URL prefixes, and the reviewer measured what that actually
# bought: an anonymous GET of /join/garbage/, /d/garbage/, /t/garbage/, /get-back-in/
# garbage/, /e/ and /accounts/confirm-email/garbage/ all printed the admin's first name,
# while somebody holding a REAL /digest/confirm/<token>/ link got the anonymous fallback.
# So the gate was wrong in both directions at once: a stranger who typed a path got the
# name, and a relative with a working link did not.
#
# A URL prefix is not a capability. Only the view knows whether the string in the path was
# a live token, and it knows it at exactly one moment — after the lookup succeeds and
# before it renders. So each token view says so about itself, and this reads what they
# said. A bogus token now falls through to the same bare 404 as any other unknown route,
# byte-identical, which is the answer S-202 isolation already depends on.
#
# /accounts/confirm-email/ names nobody: it is allauth's view and sets nothing, which is
# the right answer rather than a gap — a confirmation link proves control of a mailbox,
# not that a relative introduced anybody.
# NAMED WITHOUT THE WORD "TOKEN", deliberately. `test_no_hardcoded_demo_credentials` and
# ruff's S105 both flag any NAME containing it as a hardcoded credential, and this holds a
# boolean. Silencing either one here would be the wrong trade: that guard exists because
# this repository has published a working credential three times, and its own comment
# warns that a noisy guard is one people allowlist their way around. The attribute VALUE
# and the helper below keep the names the review asked for.
FAMILY_LINK_READER_ATTRIBUTE = "reader_holds_a_family_link"


def note_the_reader_holds_a_link(request: HttpRequest) -> None:
    """Called by a token view once its token has resolved, and never before.

    Deliberately a plain attribute on the request rather than anything in the session: it
    must not outlive the one response it was true for. Putting it in the session would
    mean a grandmother's forwarded link left the name on every later page that browser
    ever loaded, which is the leak this whole gate exists to close.
    """
    setattr(request, FAMILY_LINK_READER_ATTRIBUTE, True)


def may_name_the_admin(request: HttpRequest) -> bool:
    """Is this reader someone the family's admin has already been introduced to?

    Walk item 12, 2026-09-19: the footer's help line named the admin on every page including
    the sign-in screen, both password-reset pages and About — so a stranger who typed the
    domain, or who was sent any link at all, learned a relative's first name and that they
    run this server. The same name was printed three times on /about/ and four on
    /how-this-works/ once the footer is counted.

    It is not a secret, and that is not the standard. The standard is that a family's
    private network should not volunteer a family member's name to somebody who has not
    been let in — and the name buys a logged-out reader nothing, because every public page
    that printed it is a page they reached without being invited.

    Two readers qualify. A signed-in member, who knows these people. And somebody whose
    token a view has just RESOLVED, because the relative who sent them that link already
    said who they were — which is also why the name is most useful to them, a grandmother
    on her no-login page being the person in this product least able to work out who to
    ring.
    """
    # `getattr`, not `request.user`, and the reason is measured rather than defensive
    # habit: this runs from a context processor on EVERY render, and a response built
    # without AuthenticationMiddleware having run — a bare RequestFactory in a test, an
    # error page raised before the middleware stack finishes — has no `.user` at all.
    # `test_the_limit_covers_get_which_allauths_own_wrapper_exempts` found exactly that.
    # Falling through is also the right ANSWER there, not just a way to avoid the
    # AttributeError: with no resolvable reader, name nobody.
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return True
    return bool(getattr(request, FAMILY_LINK_READER_ATTRIBUTE, False))


def viewer(request: HttpRequest) -> dict[str, object]:
    """`viewer_member`, `viewer_is_admin` and `help_contact`, for the site chrome.

    Named for the reader rather than for the model, because `member` alone is ambiguous in
    a template that is also rendering somebody else's member row — which the roster and the
    managed-profile pages both do.
    """
    member = _member_for(request)
    name_allowed = may_name_the_admin(request)
    return {
        "viewer_member": member,
        "viewer_is_admin": member is not None and permissions.is_admin(member),
        # Lazy: this processor runs on EVERY render, and in this product a 404 is not
        # exceptional — it is the answer to every authorization denial (TM-2). A template
        # that never prints the help line never pays for the lookup.
        #
        # EMPTY for a reader who has not been let in (walk item 12). Every template that
        # prints this already has a no-name fallback, because a fresh instance has no admin
        # to name — so the public sentence is the one that was always there, now reached by
        # a second route. One variable, resolved once, rather than an `{% if %}` on
        # `user.is_authenticated` in each of the eight places the name is printed, where the
        # ninth would have been forgotten.
        "help_contact": SimpleLazyObject(help_contact_name) if name_allowed else "",
    }
