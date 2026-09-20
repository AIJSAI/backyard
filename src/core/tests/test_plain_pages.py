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
# A throwaway passphrase for the one test that drives the real sign-in form. Named
# rather than inlined, the way the rest of the suite does it: an inline
# `password="..."` reads as a credential assignment to the pre-commit secret scanner.
_TEST_PASSPHRASE = "aX9!mnpq2ffz"
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


def _a_relative_signed_in(pod: Pod, username: str = "cousin") -> Client:
    """Somebody who has been let in.

    Since walk item 12 the admin's first name is printed only for a reader the family has
    already introduced them to — a signed-in member, or somebody holding a link a relative
    sent them. So every test about what the help line SAYS needs a reader, where it used
    to be able to use the sign-in page. `test_a_stranger_is_never_told_a_relatives_name`
    in test_a_stranger_is_told_no_names.py is the other direction.
    """
    user = User.objects.create_user(username=username)
    member = Member.objects.create(display_name="Cousin Reed", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return client


# --- how this works -------------------------------------------------------------------


def test_it_opens_without_signing_in() -> None:
    """Linked from the sign-in page on purpose: somebody who cannot get in is exactly the
    person who needs to know who to ask."""
    page = Client().get(reverse("how_it_works"))
    assert page.status_code == 200
    assert reverse("how_it_works") in Client().get(reverse("account_login")).content.decode()


def test_it_answers_the_questions_the_owner_listed() -> None:
    """The six of owner direction 8, plus the two the 2026-09-19 copy pass added because
    a sceptical relative asks them before joining: what an admin can do, and how to get
    out. Markers are whitespace-normalised — where a sentence wraps in the template is
    not something a test should pin."""
    body = " ".join(Client().get(reverse("how_it_works")).content.decode().split())
    for question, marker in (
        ("what this is for", "keeps everyone connected and up to date in one private place"),
        ("who can see what I post", "A post goes to your household unless you choose more people"),
        ("who can join and how", "Backyard is invitation only."),
        ("what an admin can and cannot do", "They see only the posts shared with them"),
        ("what email updates are", "Email Updates"),
        ("how to stop email updates", "every email has a link to stop them"),
        ("what happens to my photos", "Delete Post removes it and its photos for good"),
        ("if I forget my password", "Forgot Your Password?"),
        ("how to leave", "Your posts can stay, stay without your name, or be deleted"),
    ):
        assert marker in body, f"the page does not answer: {question}"


def test_it_carries_the_privacy_disclosure_the_threat_model_promises() -> None:
    """GAP-7. The ONE per-person thing this instance keeps is a yes/no weekly presence,
    and the family is owed that in words they will actually read — not only in a markdown
    file in the repository.

    The repo note is asserted alongside it so the two cannot drift into saying different
    things about the same promise.
    """
    body = " ".join(Client().get(reverse("how_it_works")).content.decode().split())
    # The DISCLOSURE, not its punctuation: the sentence opened "One more thing, once a
    # week:" until the judge walk of 2026-09-19 cut the presenter's tic in front of it.
    assert "Once a week it also notes whether you visited, yes or no" in body
    assert "so admins can see how many people are using it" in body
    assert "It doesn't track what you read or tap." in body

    note = " ".join(_PRIVACY_NOTE.read_text(encoding="utf-8").split())
    assert "once a week, whether each of us stopped by" in note, (
        "docs/family-privacy-note.md no longer makes the promise this page repeats"
    )


def test_it_names_the_person_to_ask_when_there_is_one() -> None:
    pod = _family()
    _instance_admin(pod, "Jim Whitfield")
    # Signed in: /how-this-works/ is public, and since walk item 12 a public page names
    # nobody. What is asserted here is the naming path itself, which is unchanged.
    page = _a_relative_signed_in(pod).get(reverse("how_it_works")).content.decode()
    body = " ".join(page.split())
    assert "To get someone invited, ask Jim." in body, "the page does not name who to ask"
    assert "ask Jim to remove you" in body, "the page does not name who removes you"
    assert "Whitfield" not in body, "the help line uses the first name only"


def test_it_falls_back_to_a_sentence_when_nobody_is_named() -> None:
    """A fresh instance, or an operator account created by the setup wizard with no
    display name. The sentence must still read as a sentence.

    Whitespace-normalised since R2-1: this page's own three fallbacks wrap across lines in
    the template, so the un-normalised form of this assertion was only ever passing on the
    shared footer — which is a different sentence on a different surface.

    The copy pass of 2026-09-19 replaced "whoever in the family set this up" with the
    product's one public help phrase, which the shared footer also uses — so the page is
    now sliced at the footer before counting, rather than counting a phrase that was
    unique only by accident.
    """
    html = Client().get(reverse("how_it_works")).content.decode()
    body = " ".join(html[: html.index("<footer")].split())
    assert body.count("the person who invited you") == 3, (
        "this page's own three fallbacks are what it is about; the footer is asserted separately"
    )


# --- the footer's help line -----------------------------------------------------------


def test_the_footer_names_the_person_who_runs_this_backyard() -> None:
    """Read from the DATABASE at render time. This repository is public and a relative's
    name is never written into it; the test proves the path by creating one."""
    pod = _family()
    _instance_admin(pod, "Jim Whitfield")
    html = _a_relative_signed_in(pod).get(reverse("feed")).content.decode()
    footer = html[html.index("<footer") : html.index("</footer>")]
    assert "Need help? Contact Jim." in footer
    # The HELP AFFORDANCE is never a link — that is the SC 3.2.6 invariant, and it used to
    # be stated as "the footer has no links" because the footer held nothing else. Sign out
    # joined it for signed-in readers on 2026-09-19 (walk item 11), and the copy pass the
    # same day brought How It Works and About into the signed-out footer. All of them sit
    # AFTER the help line, so the help mechanism keeps its position on every surface, and
    # the span is what is asserted rather than its neighbours.
    help_line = footer[footer.index('class="help"') : footer.index("</span>")]
    assert "<a " not in help_line, "the help affordance became a link; SC 3.2.6 depends on it"


def test_the_grandparents_page_carries_the_same_help_line() -> None:
    """Owner direction 1, "same on the elder page" — she is the person most likely to be
    stuck and least likely to guess who to ring. Text, never a link: S-601 allows this
    surface no href but its own.

    ONE SENTENCE, ONE FILE. The elder page is standalone, so it inherits no footer, and it
    used to hand-write its own copy of this line — which is how it went on reading
    "Stuck? Ask Jim." after every other surface had been rewritten. It now includes
    core/_footer.html in the `standalone=True` shape, so "same help line" means the same
    words as well as the same person, and this assertion reads like the footer's above.
    """
    pod = _family()
    _instance_admin(pod, "Jim Whitfield")
    nana = Member.objects.create(display_name="Nana")
    PodMembership.objects.create(member=nana, pod=pod)
    raw = elder_tokens.mint(nana)

    client = Client()
    client.get(reverse("elder_enter", args=[raw]))
    html = client.get(reverse("elder_feed")).content.decode()
    assert "Need help? Contact Jim." in html
    assert 'href="https://github' not in html


def test_the_help_line_a_logged_out_reader_gets_names_the_person_who_invited_them() -> None:
    """R2-1. Walk item 12 empties the name for anybody who has not been let in, so the
    FALLBACK is what a stranger, a locked-out relative and a grandmother on a bare
    instance actually read. It said "Ask whoever in the family set this up", which the
    owner read back on the walk and called strange: it names a role no family uses, and
    nobody a relative could ring. Everyone who reaches this product reached it through a
    person who sent them a link, so the sentence says that person.

    Asserted on the sign-in page, which is the one screen a locked-out member reads, and
    on the footer specifically — the other pages carry their own longer sentences and are
    not this line.
    """
    _family()
    footer_pages = (reverse("account_login"), reverse("account_reset_password"))
    for route in footer_pages:
        html = Client().get(route).content.decode()
        footer = html[html.index("<footer") : html.index("</footer>")]
        assert "Need help? Contact the person who invited you." in footer, (
            f"{route} does not carry the fallback help line: {footer}"
        )
        assert "whoever in the family set this up" not in footer


def test_the_grandparents_page_falls_back_to_the_same_sentence() -> None:
    """The elder page is not inside the shared footer — S-601 gives it its own — so its
    copy of the help line is a second place the old wording could survive."""
    pod = _family()
    nana = Member.objects.create(display_name="Nana")
    PodMembership.objects.create(member=nana, pod=pod)
    raw = elder_tokens.mint(nana)

    client = Client()
    client.get(reverse("elder_enter", args=[raw]))
    html = client.get(reverse("elder_feed")).content.decode()
    assert "Need help? Contact the person who invited you." in html
    assert "whoever in the family set this up" not in html


def test_the_help_line_survives_an_admin_with_a_one_word_name() -> None:
    """A display name with no space in it is already its own first name; splitting on one
    would be how this ends up rendering "Need help? Contact ."."""
    pod = _family()
    _instance_admin(pod, "Nana")
    html = _a_relative_signed_in(pod).get(reverse("feed")).content.decode()
    assert "Need help? Contact Nana." in html


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


# --- what a returning member lands on ------------------------------------------------


@pytest.mark.django_db
def test_signing_in_greets_the_person_and_never_the_username() -> None:
    """allauth announces "Successfully signed in as priya." — the least important event
    in the product, in its loudest component, naming the login rather than the person.

    Driven through the real sign-in form, because the message is rendered by allauth at
    the moment it is added and a template read would not prove what lands on the page.
    """
    pod = _family()
    user = User.objects.create_user(username="priya", password=_TEST_PASSPHRASE)
    member = Member.objects.create(display_name="Priya Whitfield", user=user)
    PodMembership.objects.create(member=member, pod=pod)

    client = Client()
    response = client.post(
        reverse("account_login"),
        {"login": "priya", "password": _TEST_PASSPHRASE},
        follow=True,
    )
    body = response.content.decode()
    assert "Signed in as Priya." in body
    assert "Successfully signed in" not in body
    assert "priya." not in body.replace("Signed in as Priya.", ""), (
        "the flash still prints the username"
    )


@pytest.mark.django_db
def test_a_returning_member_lands_on_the_family_and_not_on_a_stack_of_notices() -> None:
    """The first screen of a phone used to carry four things above the composer: a flash,
    the orientation card, a loose "adding people is an admin's job" paragraph, and the
    add-an-email card. Three of the four are gone or moved; the fourth is dismissible and
    only reaches a member with no address at all.

    Asserted on a member who HAS an address and has already been welcomed — the returning
    relative, which is everybody, most days.
    """
    from allauth.account.models import EmailAddress
    from django.utils import timezone

    pod = _family()
    user = User.objects.create_user(username="priya")
    member = Member.objects.create(
        display_name="Priya Whitfield", user=user, orientation_dismissed_at=timezone.now()
    )
    PodMembership.objects.create(member=member, pod=pod)
    EmailAddress.objects.create(user=user, email="priya@example.com", primary=True)

    client = Client()
    client.force_login(user, backend=_BACKEND)
    body = client.get(reverse("feed")).content.decode()

    assert 'class="orientation"' not in body
    assert "Adding people is an admin" not in body
    assert 'class="prompt"' not in body
    assert 'id="compose-body"' in body  # the composer is what they get


@pytest.mark.django_db
def test_a_removed_instance_admin_is_never_the_person_to_ask() -> None:
    """Removal keeps the Member row and deactivates the account, so a lookup by role
    alone would go on telling relatives to ask somebody who can no longer sign in — on
    the footer of every page, on About, and in the password-reset guidance, which is the
    one screen read by somebody who is already locked out.

    The fallback sentence stands when nobody is left to name.
    """
    from core import removal

    pod = _family()
    admin = _instance_admin(pod, "Jim Whitfield")
    successor_user = User.objects.create_user(username="successor")
    successor = Member.objects.create(
        display_name="Ada Whitfield", user=successor_user, role=Member.INSTANCE_ADMIN
    )
    PodMembership.objects.create(member=successor, pod=pod)

    # Signed in, because a public page names nobody at all since walk item 12 — which
    # would make every assertion below pass for the wrong reason.
    reader = _a_relative_signed_in(pod)

    # Denominator: the first admin by pk is the one named while they are still here.
    assert "Need help? Contact Jim." in reader.get(reverse("feed")).content.decode()

    removal.remove_member(admin, content=removal.KEEP)

    html = reader.get(reverse("feed")).content.decode()
    assert "Need help? Contact Jim." not in html, "the footer still names a removed admin"
    assert "Need help? Contact Ada." in html

    removal.remove_member(successor, content=removal.KEEP)
    html = reader.get(reverse("feed")).content.decode()
    assert "Need help? Contact the person who invited you." in html
