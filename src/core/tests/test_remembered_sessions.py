"""How long a sign-in lasts, per case (S-107, T-SESS-3).

Four cases, and each exists because getting it wrong is a different defect:

* an ordinary member who ticks Keep Me Signed In gets 60 days, or an installed
  home-screen app signs the whole family out every fortnight;
* an ADMIN never does, whatever they tick, because an admin session mints no-login links,
  get-back-in links and invites (T-SESS-2);
* an unticked sign-in is left exactly as allauth left it, because tightening or loosening
  it is not this feature's to do;
* and the refresh is capped at once a day, because `SESSION_SAVE_EVERY_REQUEST` — a
  session row write on every request in the product — is the thing review rejected.

The No-Login Link path is asserted here too. `elder_views` has its own `set_expiry` rule
for a different credential, and this middleware must not touch it.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core import elder_tokens, sessions
from core.models import Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_PW = "a-Strong-passphrase-9"
_DAY = 60 * 60 * 24


def _member(*, role: str = Member.MEMBER) -> Member:
    tag = secrets.token_hex(4)
    yard, _ = Yard.objects.get_or_create(name="Maternal", slug="maternal")
    pod, _ = Pod.objects.get_or_create(name="The cousins", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = User.objects.create_user(username=f"m-{tag}", password=_PW)
    member = Member.objects.create(display_name="Ann Poster", user=user, role=role)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _sign_in(member: Member, *, remember: bool) -> Client:
    """Sign in through the REAL form, so the override in core/forms.py is what runs.

    `force_login` would prove nothing here: the whole question is what allauth's own
    login flow leaves the expiry at, and force_login never goes near it.
    """
    assert member.user is not None
    client = Client()
    data: dict[str, Any] = {"login": member.user.username, "password": _PW}
    if remember:
        data["remember"] = "on"
    response = client.post(reverse("account_login"), data)
    assert response.status_code == 302, "the sign-in did not succeed"
    return client


def _expiry_age(client: Client) -> int | None:
    return client.session.get_expiry_age()


# --- the four cases ----------------------------------------------------------------------


def test_a_member_who_ticks_keep_me_signed_in_gets_sixty_days() -> None:
    member = _member()
    client = _sign_in(member, remember=True)
    age = _expiry_age(client)
    assert age is not None
    # Within a second of the configured age: the clock moves between set and read.
    assert settings.REMEMBERED_SESSION_AGE - 5 <= age <= settings.REMEMBERED_SESSION_AGE
    assert sessions.REMEMBERED_AT in client.session


def test_an_admin_stays_at_two_weeks_even_when_they_tick_the_box() -> None:
    """An admin session mints no-login links, get-back-in links and invites, so its theft
    is an instance-level event rather than one relative's feed (T-SESS-2)."""
    for role in (Member.YARD_ADMIN, Member.INSTANCE_ADMIN):
        member = _member(role=role)
        client = _sign_in(member, remember=True)
        age = _expiry_age(client)
        assert age is not None
        assert age <= settings.SESSION_COOKIE_AGE, f"{role} was given a long session"
        assert sessions.REMEMBERED_AT not in client.session


def test_an_unticked_sign_in_is_left_exactly_as_allauth_left_it() -> None:
    """A browser-session cookie, which is the right default on a borrowed laptop and is
    not this feature's to change."""
    member = _member()
    client = _sign_in(member, remember=False)
    assert client.session.get_expire_at_browser_close() is True
    assert sessions.REMEMBERED_AT not in client.session


def test_using_the_app_renews_a_remembered_session_once_the_day_has_passed() -> None:
    member = _member()
    client = _sign_in(member, remember=True)
    # Age the stamp by a day and a minute, the way a member coming back tomorrow does.
    session = client.session
    session[sessions.REMEMBERED_AT] = int(time.time()) - _DAY - 60
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key or ""

    assert client.get(reverse("feed")).status_code == 200
    refreshed = client.session[sessions.REMEMBERED_AT]
    assert time.time() - refreshed < 5  # re-stamped now
    age = _expiry_age(client)
    assert age is not None
    assert age > settings.REMEMBERED_SESSION_AGE - 60  # the full 60 days again


def test_a_second_request_inside_the_day_writes_nothing() -> None:
    """The whole reason this is a middleware and not SESSION_SAVE_EVERY_REQUEST: a member
    scrolling the feed for an hour writes one session row, not two hundred."""
    member = _member()
    client = _sign_in(member, remember=True)
    stamped = client.session[sessions.REMEMBERED_AT]
    for _ in range(3):
        assert client.get(reverse("feed")).status_code == 200
    assert client.session[sessions.REMEMBERED_AT] == stamped


def test_a_member_promoted_to_admin_stops_being_extended() -> None:
    """`permissions.is_admin` is re-asked at every refresh rather than only at sign-in, so
    a member who becomes a side admin does not keep a 60-day session for two months."""
    member = _member()
    client = _sign_in(member, remember=True)
    session = client.session
    session[sessions.REMEMBERED_AT] = int(time.time()) - _DAY - 60
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key or ""

    member.role = Member.YARD_ADMIN
    member.save(update_fields=["role"])
    assert client.get(reverse("feed")).status_code == 200
    assert sessions.REMEMBERED_AT not in client.session
    age = _expiry_age(client)
    assert age is not None and age <= settings.SESSION_COOKIE_AGE, (
        "a promoted admin kept the remembered session's remaining life"
    )


# --- everybody else ----------------------------------------------------------------------


def test_the_no_login_link_session_is_untouched() -> None:
    """The elder surface has its own rule for its own credential (core/elder_views.py).
    This middleware must be invisible to it: an elder session carries no stamp, so the
    first `session.get` in the middleware ends the matter."""
    yard = Yard.objects.create(name="Paternal", slug="paternal")
    pod = Pod.objects.create(name="Nana", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    nana = Member.objects.create(display_name="Nana", kinship_name="Nana")
    PodMembership.objects.create(member=nana, pod=pod)
    Post.objects.create(author=nana, pod=pod, body="a post")

    client = Client()
    client.get(reverse("elder_enter", args=[elder_tokens.mint(nana)]))
    assert client.get(reverse("elder_feed")).status_code == 200
    assert sessions.REMEMBERED_AT not in client.session
    age = client.session.get_expiry_age()
    # elder_views' own 180-day rule, untouched by anything in this change.
    assert age is not None and age > settings.REMEMBERED_SESSION_AGE


def test_an_anonymous_request_never_reaches_the_member_lookup(
    django_assert_num_queries: Any,
) -> None:
    """The cost argument, actually MEASURED. This test requested the fixture and then
    never used it, so it asserted a status code and claimed a measurement.

    TWO is the measured number, and neither is the middleware's: they are the SAVEPOINT
    and RELEASE that `ATOMIC_REQUESTS` opens around the request, which `django_db` sees
    because the whole test already runs inside a transaction. Zero real statements — the
    page names no member, and `RememberedSessionMiddleware` stops at one dictionary lookup
    on a session with no stamp. If somebody makes the middleware touch `request.user` on
    every request, this goes to three or more and says so.
    """
    with django_assert_num_queries(2):
        assert Client().get(reverse("how_it_works")).status_code == 200
    assert sessions.is_due({}, now=time.time()) is False  # type: ignore[arg-type]


def test_a_stamp_that_is_not_an_integer_is_ignored() -> None:
    """A session is client-influenced only through code, but a stamp written by an older
    release, or by a hand-edited row, must not make the middleware raise."""
    assert sessions.is_due({sessions.REMEMBERED_AT: "yesterday"}, now=time.time()) is False  # type: ignore[arg-type]
    assert sessions.is_due({sessions.REMEMBERED_AT: None}, now=time.time()) is False  # type: ignore[arg-type]


def test_the_refresh_floor_is_the_setting_and_not_a_hardcoded_day() -> None:
    now = time.time()
    just_under = {sessions.REMEMBERED_AT: int(now) - settings.REMEMBERED_SESSION_REFRESH_AFTER + 5}
    just_over = {sessions.REMEMBERED_AT: int(now) - settings.REMEMBERED_SESSION_REFRESH_AFTER - 5}
    assert sessions.is_due(just_under, now=now) is False  # type: ignore[arg-type]
    assert sessions.is_due(just_over, now=now) is True  # type: ignore[arg-type]


def test_a_user_with_no_member_row_does_not_crash_the_middleware() -> None:
    """`user.member` is a reverse one-to-one, so it RAISES rather than returning None for
    a superuser made at a shell. A bare getattr would 500 every request they make."""
    shell_admin = User.objects.create_user(username="from-a-shell", password=_PW)
    assert sessions.member_of(shell_admin) is None
    assert sessions.member_of(None) is None
