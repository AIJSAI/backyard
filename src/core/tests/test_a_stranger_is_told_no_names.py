"""A stranger is never told a relative's name.

Walk item 12, 2026-09-19. "Stuck? Ask Jim." was in the footer of every page this product
serves, including the ones anybody on the internet can open: the sign-in screen, both
password-reset pages, About, How this works — and every 404, which in this product is the
answer to every authorization denial, so a stranger probing URLs collected it too. On
/about/ the name was printed three times on one page, and on /how-this-works/ four.

It is not a secret, and that is deliberately not the argument. The argument is that a
family's private network should not volunteer a family member's first name — and that they
run this server — to somebody nobody invited, and that the name buys such a reader nothing,
because every public page that printed it is a page they reached without being let in.

WHO STILL GETS IT, and this half matters as much:

  * a signed-in member, who knows these people already; and
  * a reader on a TOKEN-GATED page — the no-login link, the Family email's web view, an
    invite, a get-back-in link, an e-mail confirmation — because the relative who sent
    that link already said who they were, and these are exactly the readers most likely to
    be stuck. A grandmother on her no-login page is the person in this whole product least
    able to work out who to ring.

Both directions are asserted here, because a fix that just deleted the name would pass a
one-sided test and break the thing the name was added for.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core import digesting, elder_tokens, invites, recovery
from core.models import DigestSubscription, Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_NAME = "Jim Whitfield"
_FIRST = "Jim"
# The shared footer's help line, as the copy pass of 2026-09-19 rewrote it. Its words are
# core/_footer.html's; what this file is about is WHO is named in it.
_HELP = f"Need help? Contact {_FIRST}."
# ONE CONSTANT AGAIN. The grandparent's page is standalone (S-601 gives it no href but its
# own, so it inherits no footer) and used to hand-write its own copy of this sentence,
# which is how it came to read "Stuck? Ask Jim." for as long as it did. It now includes
# core/_footer.html in the `standalone=True` shape, so there is one sentence in one file
# and this file has no second constant to keep in step.


def _family() -> tuple[Pod, Member]:
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    admin = Member.objects.create(
        display_name=_NAME,
        user=User.objects.create_user(username="theadmin"),
        role=Member.INSTANCE_ADMIN,
    )
    PodMembership.objects.create(member=admin, pod=pod)
    return pod, admin


# --- the public surfaces --------------------------------------------------------------


@pytest.mark.parametrize(
    "route",
    [
        "account_login",
        "account_reset_password",
        "about",
        "how_it_works",
    ],
)
def test_a_logged_out_stranger_is_never_told_a_relatives_first_name(route: str) -> None:
    _family()
    html = Client().get(reverse(route)).content.decode()
    assert html  # non-vacuity: the page rendered
    assert _FIRST not in html, (
        f"{route} prints a relative's first name to somebody who has not been let in"
    )


def test_a_404_does_not_leak_it_either() -> None:
    """In this product a 404 is not an edge case — it is the answer to every authorization
    denial (TM-2), so it is the page a prober sees most of."""
    _family()
    page = Client().get("/no-such-thing-here/")
    assert page.status_code == 404
    assert _FIRST not in page.content.decode()


def test_the_public_pages_still_say_who_to_ask_in_other_words() -> None:
    """Deleting the name must not delete the help. The affordance is what WCAG 2.2
    SC 3.2.6 is pinned on, and a locked-out relative reads the reset page."""
    _family()
    for route in ("account_login", "account_reset_password", "about"):
        html = Client().get(reverse(route)).content.decode()
        assert (
            "whoever in the family set this up" in html or "the person who invited you" in html
        ), f"{route} names nobody AND offers no other way to ask"


def test_about_says_a_relative_runs_it_without_saying_which_one() -> None:
    _family()
    # Whitespace-normalised: the sentence wraps across lines in the template, which is how
    # it should be written and not something a test should pin.
    html = " ".join(Client().get(reverse("about")).content.decode().split())
    assert "A relative set this up and runs it." in html
    assert "Contact the person who invited you" in html


# --- the readers who have been let in -------------------------------------------------


def test_a_signed_in_member_is_told_who_to_ask() -> None:
    pod, _admin = _family()
    user = User.objects.create_user(username="cousin")
    member = Member.objects.create(display_name="Cousin Reed", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)

    assert _HELP in client.get(reverse("feed")).content.decode()
    # ...and on the public pages too, once they are signed in.
    assert f"ask {_FIRST}" in client.get(reverse("how_it_works")).content.decode()


def test_the_grandparents_no_login_page_still_names_him() -> None:
    """She has no account and no nav, she is the likeliest person in this family to be
    stuck, and the relative who sent her the link already told her who he was."""
    pod, _admin = _family()
    nana = Member.objects.create(display_name="Nana")
    PodMembership.objects.create(member=nana, pod=pod)

    client = Client()
    client.get(reverse("elder_enter", args=[elder_tokens.mint(nana)]))
    html = client.get(reverse("elder_feed")).content.decode()
    assert _HELP in html


def test_an_invite_page_names_him() -> None:
    pod, admin = _family()
    _invite, raw = invites.mint_invite(pod, admin)
    html = Client().get(reverse("join", args=[raw])).content.decode()
    assert _HELP in html, "somebody opening an invite a relative sent them is not a stranger"


def test_a_get_back_in_link_names_him() -> None:
    """The one page read by somebody who is already locked out. Taking the name off THIS
    page would be the expensive half of item 12 done to the wrong reader."""
    pod, admin = _family()
    user = User.objects.create_user(username="locked-out")
    member = Member.objects.create(display_name="Sam Reed", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    raw = recovery.issue(member, issued_by=admin)

    html = Client().get(reverse("recover", args=[raw])).content.decode()
    assert _HELP in html


def test_a_bogus_token_on_every_token_surface_names_nobody() -> None:
    """THE PROPERTY, not the URL shape — and this test is the inverse of the one it
    replaces.

    That one pinned the old implementation: a tuple of URL PREFIXES, with
    `('/join/abc/', True)` asserting that anything under /join/ counted as a reader who
    had been introduced. The reviewer measured what that bought and it was wrong in both
    directions at once: an anonymous GET of /join/garbage/, /d/garbage/, /t/garbage/,
    /get-back-in/garbage/, /e/ and /accounts/confirm-email/garbage/ all printed the
    admin's first name, while somebody holding a REAL /digest/confirm/<token>/ link got
    the anonymous fallback because that route was not in the tuple.

    A URL prefix is not a capability. Only the view knows whether the string in the path
    was a live token. So: garbage names nobody anywhere, and the answer stays the bare
    byte-identical 404 that S-202 isolation depends on.
    """
    _family()
    client = Client()
    bodies = set()
    for path in (
        "/join/garbage/",
        "/d/garbage/",
        "/t/garbage/",
        "/get-back-in/garbage/",
        "/digest/confirm/garbage/",
        "/digest/unsubscribe/garbage/",
    ):
        page = client.get(path)
        assert page.status_code == 404, (path, page.status_code)
        assert _FIRST not in page.content.decode(), f"{path} named a relative to a stranger"
        bodies.add(page.content)

    # ...and every one of them is the SAME 404, indistinguishable from an unknown route.
    unknown = client.get("/no-such-route-at-all/")
    assert unknown.status_code == 404
    bodies.add(unknown.content)
    assert len(bodies) == 1, "the dead token surfaces no longer answer identically"


def test_the_elder_surface_with_no_session_names_nobody() -> None:
    """/e/ has no token IN the path — it reads a session minted at /t/. Typing it names
    nobody, which the prefix version got wrong."""
    _family()
    page = Client().get(reverse("elder_feed"))
    assert page.status_code == 404
    assert _FIRST not in page.content.decode()


def test_an_account_confirmation_link_names_nobody() -> None:
    """allauth's own view, which sets nothing — and that is the right answer rather than a
    gap. A confirmation link proves control of a mailbox; it does not mean a relative
    introduced anybody."""
    _family()
    page = Client().get("/accounts/confirm-email/garbage/")
    assert _FIRST not in page.content.decode()


def test_a_real_token_on_every_token_surface_does_name_them() -> None:
    """The other direction, walked with LIVE tokens on each surface. Without this the
    whole gate could be satisfied by naming nobody ever, which would take the help line
    away from the readers it was added for."""
    pod, admin = _family()

    # An invite.
    _invite, invite_raw = invites.mint_invite(pod, admin)
    assert _HELP in Client().get(reverse("join", args=[invite_raw])).content.decode()

    # A get-back-in link.
    locked = Member.objects.create(
        display_name="Sam Reed", user=User.objects.create_user(username="sam")
    )
    PodMembership.objects.create(member=locked, pod=pod)
    recovery_raw = recovery.issue(locked, issued_by=admin)
    assert _HELP in Client().get(reverse("recover", args=[recovery_raw])).content.decode()

    # The no-login link, and the session it becomes.
    nana = Member.objects.create(display_name="Nana")
    PodMembership.objects.create(member=nana, pod=pod)
    elder = Client()
    elder.get(reverse("elder_enter", args=[elder_tokens.mint(nana)]))
    assert _HELP in elder.get(reverse("elder_feed")).content.decode()

    # The Email Updates confirm link — the surface the reviewer measured as wrong the
    # other way round, where a real holder used to get the anonymous fallback.
    subscription = DigestSubscription.objects.create(
        member=locked,
        address="sam@example.com",
        cadence=DigestSubscription.WEEKLY,
        enabled=True,
        confirm_token_digest=digesting._digest("raw-confirm"),
        unsubscribe_token_digest=digesting._digest("raw-unsub"),
    )
    assert subscription.pk
    confirm = Client().get(reverse("digest_confirm", args=["raw-confirm"]))
    assert confirm.status_code == 200
    assert _HELP in confirm.content.decode()

    unsub = Client().get(reverse("digest_unsubscribe", args=["raw-unsub"]))
    assert unsub.status_code == 200
    assert _HELP in unsub.content.decode()


def test_the_flag_is_off_until_a_view_sets_it() -> None:
    """Guard the guard. A request that never went through AuthenticationMiddleware has no
    `.user` at all — a bare RequestFactory here, an error page raised before the stack
    finishes there — and this runs from a context processor on every render, so it must
    answer rather than raise."""
    from django.contrib.auth.models import AnonymousUser
    from django.test import RequestFactory

    from core.context_processors import may_name_the_admin, note_the_reader_holds_a_link

    factory = RequestFactory()
    bare = factory.get("/join/abc/")
    assert not hasattr(bare, "user")
    assert may_name_the_admin(bare) is False, "a URL path alone still qualifies"

    anon = factory.get("/join/abc/")
    anon.user = AnonymousUser()
    assert may_name_the_admin(anon) is False
    note_the_reader_holds_a_link(anon)
    assert may_name_the_admin(anon) is True
