"""How long a sign-in lasts on the device it was made on (S-107).

Before this, every signed-in session was Django's two-week cookie and nothing extended
it, so a relative with Backyard on their home screen was signed out every fortnight —
on iOS, into an app whose storage is separate from Safari's, so the password manager
that filled the form the first time is one app away (ADR-002, the install notes). That
is the difference between "the app" and "a bookmark that keeps logging me out".

The cure is deliberately narrow, because the two wider ones were already rejected in
review (settings.py says so where SESSION_COOKIE_AGE is not set):

* It applies to ONE SESSION, chosen by the member ticking Keep Me Signed In at sign-in.
  Nothing about any other session moves.
* It is refused to ADMINS. An admin session can mint a no-login link, a get-back-in link
  and an invite (T-SESS-2), so its theft is an instance-level event rather than a feed;
  two weeks with no extension is the right life for it, and `permissions.is_admin` is
  re-asked on every refresh so a member PROMOTED after signing in stops being extended.
* It renews at most once a day (`REMEMBERED_SESSION_REFRESH_AFTER`), so the session table
  takes one write per device per day rather than SESSION_SAVE_EVERY_REQUEST's one per
  request.

The No-Login Link sessions are untouched: they carry no `_auth_user_id` and no stamp
here, and `elder_views` keeps its own `set_expiry` (which is a different rule for a
different credential — read that module before changing this one).
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.sessions.backends.base import SessionBase
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from . import permissions
from .models import Member

# The stamp, and the whole switch. A session without this key is not a remembered one and
# the middleware never touches it. The value is the epoch second of the last refresh, so
# "how stale is this" is one subtraction with no second clock to keep.
REMEMBERED_AT = "keep_signed_in_at"


def _stamp(session: SessionBase) -> None:
    session[REMEMBERED_AT] = int(timezone.now().timestamp())
    session.set_expiry(settings.REMEMBERED_SESSION_AGE)


def start(session: SessionBase, member: Member, *, remembered: bool) -> None:
    """Apply the sign-in lifetime for this member on this device.

    Called once, from the sign-in form, AFTER allauth has set its own expiry — allauth
    sets `SESSION_COOKIE_AGE` when the box is ticked and a browser-session cookie when it
    is not, and this either lengthens the first case or leaves the second exactly alone.
    An unticked sign-in still ends when the browser does, which is the right default on a
    borrowed laptop and is not this feature's to change.
    """
    if not remembered or permissions.is_admin(member):
        # Belt for the promotion case in the other direction: a member who was remembered,
        # then became an admin, then signed in again must not keep a stale stamp that the
        # middleware would read as permission to extend.
        session.pop(REMEMBERED_AT, None)
        return
    _stamp(session)


def refresh_if_due(session: SessionBase, member: Member) -> None:
    """Renew a remembered session that has not been renewed today.

    The caller (RememberedSessionMiddleware) has already established that the stamp is
    older than the floor, so this always writes; keeping the decision there is what makes
    the ordinary request cost zero queries and zero session writes.
    """
    if permissions.is_admin(member):
        # Promoted since sign-in. Stop extending, and let the session run out on whatever
        # remains of its current expiry rather than cutting a working admin off mid-act.
        session.pop(REMEMBERED_AT, None)
        return
    _stamp(session)


def member_of(user: object) -> Member | None:
    """The Member behind a request's user, or None.

    `user.member` is a reverse one-to-one, so it RAISES for a User with no Member row
    rather than returning None — and a bare `getattr` would let that exception out of the
    middleware and 500 the request. A superuser created at a shell (`createsuperuser`) is
    exactly that shape, and so is an account mid-way through the first-run wizard.
    """
    try:
        member = user.member  # type: ignore[attr-defined]
    except (AttributeError, ObjectDoesNotExist):
        return None
    return member if isinstance(member, Member) else None


def is_due(session: SessionBase, *, now: float) -> bool:
    """Whether this session is a remembered one whose daily refresh has come round.

    Split out from the middleware so the floor is testable without a request, and so the
    hot path is one dict lookup on a session Django has already decoded.
    """
    stamped = session.get(REMEMBERED_AT)
    if not isinstance(stamped, int):
        return False
    return now - stamped >= settings.REMEMBERED_SESSION_REFRESH_AFTER
