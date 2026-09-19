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

from core import elder_tokens, invites, recovery
from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_NAME = "Jim Whitfield"
_FIRST = "Jim"


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
    assert "A relative set this up and looks after it." in html
    assert "ask the person who invited you" in html


# --- the readers who have been let in -------------------------------------------------


def test_a_signed_in_member_is_told_who_to_ask() -> None:
    pod, _admin = _family()
    user = User.objects.create_user(username="cousin")
    member = Member.objects.create(display_name="Cousin Reed", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)

    assert f"Stuck? Ask {_FIRST}." in client.get(reverse("feed")).content.decode()
    # ...and on the public pages too, once they are signed in.
    assert f"Ask {_FIRST}" in client.get(reverse("how_it_works")).content.decode()


def test_the_grandparents_no_login_page_still_names_him() -> None:
    """She has no account and no nav, she is the likeliest person in this family to be
    stuck, and the relative who sent her the link already told her who he was."""
    pod, _admin = _family()
    nana = Member.objects.create(display_name="Nana")
    PodMembership.objects.create(member=nana, pod=pod)

    client = Client()
    client.get(reverse("elder_enter", args=[elder_tokens.mint(nana)]))
    html = client.get(reverse("elder_feed")).content.decode()
    assert f"Stuck? Ask {_FIRST}." in html


def test_an_invite_page_names_him() -> None:
    pod, admin = _family()
    _invite, raw = invites.mint_invite(pod, admin)
    html = Client().get(reverse("join", args=[raw])).content.decode()
    assert f"Stuck? Ask {_FIRST}." in html, (
        "somebody opening an invite a relative sent them is not a stranger"
    )


def test_a_get_back_in_link_names_him() -> None:
    """The one page read by somebody who is already locked out. Taking the name off THIS
    page would be the expensive half of item 12 done to the wrong reader."""
    pod, admin = _family()
    user = User.objects.create_user(username="locked-out")
    member = Member.objects.create(display_name="Sam Reed", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    raw = recovery.issue(member, issued_by=admin)

    html = Client().get(reverse("recover", args=[raw])).content.decode()
    assert f"Stuck? Ask {_FIRST}." in html


def test_the_gate_is_a_prefix_match_on_the_real_token_routes() -> None:
    """Guard the guard: a path that merely STARTS LIKE a token route must not qualify, and
    the list must not have rotted into matching nothing."""
    from django.contrib.auth.models import AnonymousUser
    from django.test import RequestFactory

    from core.context_processors import may_name_the_admin

    factory = RequestFactory()

    # A request that never went through AuthenticationMiddleware has no `.user` at all —
    # a bare RequestFactory here, an error page raised before the stack finishes there.
    # This runs from a context processor on every render, so it must answer rather than
    # raise; naming nobody is the right answer when there is no resolvable reader.
    bare = factory.get("/about/")
    assert not hasattr(bare, "user")
    assert may_name_the_admin(bare) is False

    for path, expected in (
        ("/t/abc/", True),
        ("/e/", True),
        ("/d/abc/", True),
        ("/join/abc/", True),
        ("/get-back-in/abc/", True),
        ("/accounts/confirm-email/abc/", True),
        ("/", False),
        ("/about/", False),
        ("/accounts/login/", False),
        ("/accounts/password/reset/", False),
        ("/feed/", False),  # login_required anyway, but the PATH alone must not qualify
    ):
        request = factory.get(path)
        request.user = AnonymousUser()
        assert may_name_the_admin(request) is expected, path
