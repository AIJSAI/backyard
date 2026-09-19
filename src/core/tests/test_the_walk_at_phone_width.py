"""Five findings from the 2026-09-19 phone-width walk that are about ROOM.

Each one cost a family screen space, a wrong tap, or a silence where the product should
have spoken. They are gathered here because they are the same defect in five places — the
chrome was louder than the thing the person came for — and separating them into five files
would hide that.

  ITEM 5   "Add an email address?" was a full phone screen of card ABOVE the composer,
           saying the same thing in two paragraphs, with "Not Now" as the loudest button
           on the page. After posting, the member's own new post was two screens down.
  ITEM 11  six nav items for an admin wrapped to two rows at 390px, so every screen they
           opened gave a whole band to chrome before the family appeared.
  ITEM 15  the "Who can see my ..." controls were inline for phone and email and stacked
           for address, at three different widths, because of where the label wrapped.
  ITEM 18  after a grandparent's link was made, the empty form was still under it — and on
           a phone the link card pushes the form to where the form used to be, so the
           obvious next tap created a second grandparent by accident.
  ITEM 27  saving your profile landed on the directory and said nothing.
"""

from __future__ import annotations

import html
import re

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _world(role: str = Member.MEMBER) -> tuple[Client, Member, Pod, Yard]:
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = User.objects.create_user(username="cousin")
    member = Member.objects.create(display_name="Cousin Reed", user=user, role=role)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return client, member, pod, yard


def _flat(html: str) -> str:
    return " ".join(html.split())


# --- item 5 ---------------------------------------------------------------------------


def test_the_email_offer_is_one_line_under_the_composer_not_a_card_above_it() -> None:
    client, _member, _pod, _yard = _world()
    html = client.get(reverse("feed")).content.decode()

    assert "to reset your own password" in _flat(html)
    # It is BELOW the composer. Position is the whole item: the offer was never the
    # problem, its place and its volume were.
    assert html.index('class="composer') < html.index('class="email-prompt"'), (
        "the email offer is back above the composer"
    )
    # And it is not a heading-led card any more.
    assert "Add an email address?</h2>" not in html
    assert 'class="prompt"' not in html


def test_not_now_is_the_quietest_thing_on_the_line() -> None:
    """It was the only filled button on the page apart from Post."""
    client, _member, _pod, _yard = _world()
    html = client.get(reverse("feed")).content.decode()
    # The MARKUP, not the stylesheet: `.email-prompt {` appears first, in the <style>
    # block this page carries, and slicing from there reads the CSS instead of the line.
    start = html.index('<div class="email-prompt">')
    prompt = html[start : html.index("</div>", start)]
    assert "Not Now" in prompt
    assert "btn-quiet" in prompt, "the decline is a full-weight button again"


# --- item 11 --------------------------------------------------------------------------


def _nav(html: str) -> str:
    return html[html.index('<nav class="site-nav"') : html.index("</nav>")]


def test_an_admin_has_five_nav_items_not_six() -> None:
    client, member, _pod, _yard = _world(role=Member.INSTANCE_ADMIN)
    nav = _nav(client.get(reverse("feed")).content.decode())
    links = re.findall(r"<a [^>]*>([^<]+)</a>", nav)
    assert links == ["Feed", "Groups", "Directory", "Settings", "Members"], links
    assert "Sign out" not in nav, "Sign out is back in the nav, which is what wrapped it"
    assert member.role == Member.INSTANCE_ADMIN  # non-vacuity: this is the six-item case


def test_an_ordinary_relative_has_four() -> None:
    client, _member, _pod, _yard = _world()
    nav = _nav(client.get(reverse("feed")).content.decode())
    assert "Members" not in nav
    assert "Sign out" not in nav


def test_sign_out_is_still_one_tap_away_from_anywhere() -> None:
    """Moving it must not hide it. Two routes: the footer, which is on every page, and the
    foot of Settings, where the rest of the account controls already are."""
    client, _member, _pod, _yard = _world()
    html = client.get(reverse("feed")).content.decode()
    footer = html[html.index("<footer") : html.index("</footer>")]
    assert reverse("account_logout") in footer, "no way to sign out from the feed"

    settings_page = client.get(reverse("profile_edit")).content.decode()
    account = settings_page[settings_page.index("Your Account") :]
    assert reverse("account_logout") in account


def test_a_signed_out_footer_offers_the_two_public_pages_and_no_sign_out() -> None:
    """The SC 3.2.6 property is unchanged — the help affordance is a sentence — but what
    sits beside it is not.

    This used to assert the signed-out footer held no anchor at all. The copy pass of
    2026-09-19 moved How It Works and About into it: they were a stray paragraph under the
    sign-in card and appeared on no other signed-out surface, which is the "unprofessional
    and unfinished" the owner was reading. They are ordinary navigation, so the assertion
    is now the real property — the two pages are offered, the help line is still text, and
    a footer on a page nobody has signed in to never offers a way to sign out.
    """
    _world()
    html = Client().get(reverse("account_login")).content.decode()
    footer = html[html.index("<footer") : html.index("</footer>")]
    assert reverse("how_it_works") in footer, footer
    assert reverse("about") in footer, footer
    assert reverse("account_logout") not in footer, footer
    help_line = footer[footer.index('class="help"') : footer.index("</span>")]
    assert "<a " not in help_line, help_line


# --- item 15 --------------------------------------------------------------------------


def test_every_who_can_see_this_control_is_the_same_shape() -> None:
    """They were inline for a short label and stacked for a long one, which is a wrap
    point rather than a decision. The label must stay in VISIBLE text — five identical
    accessible names is a form-controls list a screen-reader user cannot navigate, which
    axe does not report (see test_accessibility_modes)."""
    client, _member, _pod, _yard = _world()
    html = client.get(reverse("profile_edit")).content.decode()

    labels = re.findall(r'<div class="visibility">\s*<label[^>]*>([^<]+)</label>', html)
    assert len(labels) == 5, labels
    assert len(set(labels)) == 5, f"two controls read the same: {labels}"
    for label in labels:
        # "Birthday Visibility", not "Who can see my birthday": a label is a noun, and the
        # field's own name is what keeps the five accessible names distinct.
        assert label.strip().endswith(" Visibility"), label


def test_the_stacking_is_in_the_stylesheet_not_left_to_the_wrap_point() -> None:
    client, _member, _pod, _yard = _world()
    css = client.get(reverse("feed")).content.decode()
    rule = css[css.index(".visibility {") : css.index("}", css.index(".visibility {"))]
    assert "flex-direction: column" in rule, rule
    select_rule = css[css.index(".visibility select {") :]
    select_rule = select_rule[: select_rule.index("}")]
    assert "width: 100%" in select_rule, select_rule


# --- item 18 --------------------------------------------------------------------------


def test_after_a_grandparents_link_is_made_the_empty_form_is_gone() -> None:
    client, _member, _pod, yard = _world(role=Member.INSTANCE_ADMIN)

    page = client.post(
        reverse("new_elder"),
        {
            "elder_name": "Rose Reed",
            "kinship_name": "Nana",
            "household_name": "Nana's",
            "yard_id": yard.id,
            "intent": client.get(reverse("new_elder")).context["intent"],
        },
    )
    html = page.content.decode()
    assert "Link Ready To Hand Over" in html, "the link was not minted; this proves nothing"
    assert 'name="elder_name"' not in html, (
        "the empty form is still under the link, so the next tap makes a second grandparent"
    )
    assert "Add Another Grandparent" in html, "there is no way back to making another one"


def test_the_form_is_there_when_there_is_no_link_yet() -> None:
    """Non-vacuity: the form did not simply disappear."""
    client, _member, _pod, _yard = _world(role=Member.INSTANCE_ADMIN)
    html = client.get(reverse("new_elder")).content.decode()
    assert 'name="elder_name"' in html
    assert "Add Another Grandparent" not in html


# --- item 27 --------------------------------------------------------------------------


def test_saving_your_own_profile_says_so() -> None:
    client, _member, _pod, _yard = _world()
    page = client.post(
        reverse("profile_edit"),
        {"display_name": "Cousin Reed", "kinship_name": ""},
        follow=True,
    )
    body = page.content.decode()
    assert "Saved." in body
    assert 'class="messages"' in body and 'role="status"' in body


def test_saving_somebody_elses_profile_says_whose() -> None:
    """An admin can be on this page editing a relative, where a bare "Saved." would not
    say whose profile just changed."""
    client, _admin, pod, _yard = _world(role=Member.INSTANCE_ADMIN)
    nana = Member.objects.create(display_name="Rose Reed", kinship_name="Nana")
    PodMembership.objects.create(member=nana, pod=pod)

    page = client.post(
        reverse("managed_profile_edit", args=[nana.id]),
        {"display_name": "Rose Reed", "kinship_name": "Nana"},
        follow=True,
    )
    # Unescaped: Django autoescapes `{{ message }}`, so the apostrophe arrives as &#x27;
    # and a raw substring search would fail on a page that is exactly right.
    assert "Saved Rose Reed's profile." in html.unescape(page.content.decode())
