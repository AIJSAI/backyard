"""How this works, About this Backyard, and the help line that names a person.

Owner direction 1 and 8. Three connected changes:

* the footer's help sentence stopped being "Ask whoever in the family set this up" and
  started naming the relative who actually runs it, read from the database at render time;
* the licence and the AGPL source offer left that footer for a quiet About page;
* and the questions a relative asks — who sees what I post, what the Family email is, what
  happens to my photos, what this place keeps about me — got one plain page that is also
  the family's privacy note (S-705, GAP-7).

The privacy disclosure is the part that can rot silently: it is a promise the threat model
makes on the family's behalf, and until now it lived only in `docs/family-privacy-note.md`,
which no relative will ever open.
"""

from __future__ import annotations

import pathlib

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core import elder_tokens
from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db

_BACKEND = "django.contrib.auth.backends.ModelBackend"
_PRIVACY_NOTE = pathlib.Path(__file__).resolve().parents[3] / "docs" / "family-privacy-note.md"
User = get_user_model()


def _family() -> Pod:
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds")
    pod.yards.set([yard])
    return pod


def _instance_admin(pod: Pod, display_name: str = "Jim Whitfield") -> Member:
    user = User.objects.create_user(username="theadmin")
    admin = Member.objects.create(display_name=display_name, user=user, role=Member.INSTANCE_ADMIN)
    PodMembership.objects.create(member=admin, pod=pod)
    return admin


# --- how this works -------------------------------------------------------------------


def test_it_opens_without_signing_in() -> None:
    """Linked from the sign-in page on purpose: somebody who cannot get in is exactly the
    person who needs to know who to ask."""
    page = Client().get(reverse("how_it_works"))
    assert page.status_code == 200
    assert reverse("how_it_works") in Client().get(reverse("account_login")).content.decode()


def test_it_answers_the_six_questions_the_owner_listed() -> None:
    body = Client().get(reverse("how_it_works")).content.decode()
    for question, marker in (
        ("who can see what I post", "goes to <strong>your household</strong>"),
        ("who can join and how", "Only by invitation"),
        ("what the Family email is", "The Family email"),
        ("how to stop the Family email", "stops them"),
        ("what happens to my photos", "removed\n    from the server for good"),
        ("if I forget my password", "Forgot your password?"),
    ):
        assert marker.replace("\n    ", " ") in " ".join(body.split()) or marker in body, (
            f"the page does not answer: {question}"
        )


def test_it_carries_the_privacy_disclosure_the_threat_model_promises() -> None:
    """GAP-7. The ONE per-person thing this instance keeps is a yes/no weekly presence,
    and the family is owed that in words they will actually read — not only in a markdown
    file in the repository.

    The repo note is asserted alongside it so the two cannot drift into saying different
    things about the same promise.
    """
    body = " ".join(Client().get(reverse("how_it_works")).content.decode().split())
    assert "once a week, whether you stopped by" in body
    assert "Just a yes or a no" in body
    assert "does not record what you read" in body
    assert "no per-person activity list" in body

    note = " ".join(_PRIVACY_NOTE.read_text(encoding="utf-8").split())
    assert "once a week, whether each of us stopped by" in note, (
        "docs/family-privacy-note.md no longer makes the promise this page repeats"
    )


def test_it_names_the_person_to_ask_when_there_is_one() -> None:
    pod = _family()
    _instance_admin(pod, "Jim Whitfield")
    body = Client().get(reverse("how_it_works")).content.decode()
    assert "ask Jim." in body or "Ask Jim." in body, "the page does not name who to ask"
    assert "Whitfield" not in body, "the help line uses the first name only"


def test_it_falls_back_to_the_old_sentence_when_nobody_is_named() -> None:
    """A fresh instance, or an operator account created by the setup wizard with no
    display name. The sentence must still read as a sentence."""
    body = Client().get(reverse("how_it_works")).content.decode()
    assert "whoever in the family set this up" in body


# --- the footer's help line -----------------------------------------------------------


def test_the_footer_names_the_person_who_runs_this_backyard() -> None:
    """Read from the DATABASE at render time. This repository is public and a relative's
    name is never written into it; the test proves the path by creating one."""
    pod = _family()
    _instance_admin(pod, "Jim Whitfield")
    html = Client().get(reverse("account_login")).content.decode()
    footer = html[html.index("<footer") : html.index("</footer>")]
    assert "Stuck? Ask Jim." in footer
    assert "<a " not in footer, "the footer carries no links; SC 3.2.6 depends on it"


def test_the_grandparents_page_carries_the_same_help_line() -> None:
    """Owner direction 1, "same on the elder page" — she is the person most likely to be
    stuck and least likely to guess who to ring. Text, never a link: S-601 allows this
    surface no href but its own."""
    pod = _family()
    _instance_admin(pod, "Jim Whitfield")
    nana = Member.objects.create(display_name="Nana")
    PodMembership.objects.create(member=nana, pod=pod)
    raw = elder_tokens.mint(nana)

    client = Client()
    client.get(reverse("elder_enter", args=[raw]))
    html = client.get(reverse("elder_feed")).content.decode()
    assert "Stuck? Ask Jim." in html
    assert 'href="https://github' not in html


def test_the_help_line_survives_an_admin_with_a_one_word_name() -> None:
    """A display name with no space in it is already its own first name; splitting on one
    would be how this ends up rendering "Stuck? Ask ."."""
    pod = _family()
    _instance_admin(pod, "Nana")
    html = Client().get(reverse("account_login")).content.decode()
    assert "Stuck? Ask Nana." in html


# --- about ------------------------------------------------------------------------------


def test_about_is_reachable_from_settings_and_says_who_runs_this() -> None:
    pod = _family()
    admin = _instance_admin(pod, "Jim Whitfield")
    assert admin.user is not None
    client = Client()
    client.force_login(admin.user, backend=_BACKEND)

    settings_page = client.get(reverse("profile_edit")).content.decode()
    assert reverse("about") in settings_page

    about = client.get(reverse("about")).content.decode()
    assert "Jim set this up" in about
    assert "AGPL-3.0-or-later" in about
    assert "github.com/AIJSAI/backyard" in about


def test_the_licence_line_is_no_longer_under_every_photograph() -> None:
    """The change owner direction 1 actually asked for. Asserted on the feed, which is the
    screen the family looks at most."""
    pod = _family()
    admin = _instance_admin(pod)
    assert admin.user is not None
    client = Client()
    client.force_login(admin.user, backend=_BACKEND)
    feed = client.get(reverse("feed")).content.decode()
    assert "AGPL" not in feed
    assert "github.com/AIJSAI/backyard" not in feed
