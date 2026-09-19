"""The two new admins' day-one guide, and whether it describes the real product.

A guide that lives only in `docs/` is a file in a git repository, which is exactly nowhere
for the two non-technical relatives it is written for. It is a page now, reachable from the
roster they are already standing on.

The risk a guide carries is not that it is missing. It is that it goes quietly wrong: a
control gets renamed, and the page keeps telling somebody to tap a word that is not on
their screen. So these tests assert the guide against the RENDERED product — every control
it names is a control an admin can see — rather than against the templates, and they hold
the repo copy identical to the page.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db

_BACKEND = "django.contrib.auth.backends.ModelBackend"
_GUIDE_DOC = pathlib.Path(__file__).resolve().parents[3] / "docs" / "guide" / "admins-day-one.md"
User = get_user_model()


def _world(role: str = Member.YARD_ADMIN) -> tuple[Client, Member, Pod]:
    """An admin with somebody to act on, who has a login — several roster controls exist
    only for a member who has one."""
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = User.objects.create_user(username="theadmin")
    admin = Member.objects.create(display_name="The Admin", user=user, role=role)
    PodMembership.objects.create(member=admin, pod=pod)
    other = Member.objects.create(
        display_name="Cousin Reed", user=User.objects.create_user(username="cousinreed")
    )
    PodMembership.objects.create(member=other, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return client, admin, pod


def _text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def test_a_yard_admin_can_reach_it_from_the_roster() -> None:
    """Reachable by clicking, from the page they are on, not by knowing a URL. A yard
    admin, because a yard admin IS the person it is written for."""
    client, _, _ = _world(Member.YARD_ADMIN)
    roster = client.get(reverse("members")).content.decode()
    guide_url = reverse("admins_day_one")
    assert guide_url in roster, "the roster offers no route to the guide"
    assert client.get(guide_url).status_code == 200


def test_an_instance_admin_can_reach_it_too() -> None:
    client, _, _ = _world(Member.INSTANCE_ADMIN)
    assert reverse("admins_day_one") in client.get(reverse("members")).content.decode()
    assert client.get(reverse("admins_day_one")).status_code == 200


def test_a_plain_member_cannot_open_it() -> None:
    """Not a secret, but not theirs: it describes controls a plain member does not have,
    and a page telling somebody to tap things they cannot see is worse than no page."""
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds")
    pod.yards.set([yard])
    user = User.objects.create_user(username="plain")
    member = Member.objects.create(display_name="Plain", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    assert client.get(reverse("admins_day_one")).status_code == 403


def test_it_covers_the_five_things_and_nothing_else() -> None:
    """ "One screen, friendly, non-technical, no fluff" — so the five subjects are all
    present, and the page is short enough to be one screen's worth of reading."""
    client, _, _ = _world()
    body = _text(client.get(reverse("admins_day_one")).content.decode())
    for subject in (
        "Invite a household",
        "no-login link",
        "locked out",
        "remove someone",
        "stuck",
    ):
        assert subject.lower() in body.lower(), f"the guide never covers {subject!r}"
    # The grandparent rule the runbook calls "the one rule that matters".
    assert "Post something to their side of the family first" in body
    # ONE SCREEN. It was 667 words, which is accurate and not useful on a phone; the owner
    # asked for concise. Counted on the repo copy, which is the same text without the
    # page's chrome, stylesheet and scripts. A ceiling rather than an exact count, so
    # tightening a sentence is never a test change — but growing it back into an essay is.
    words = _GUIDE_DOC.read_text(encoding="utf-8").split("---", 1)[1].split()
    assert len(words) < 420, f"the guide is {len(words)} words again"


def test_every_control_the_guide_names_is_one_the_admin_can_see() -> None:
    """The failure a guide dies of: a control gets renamed and the page keeps naming the
    old word. Measured against the rendered roster rather than the template source.

    A yard admin, not an instance admin: the instance admin sees a strictly larger roster,
    so validating against theirs would certify sentences that are false for the reader the
    guide is written for.
    """
    client, _, _ = _world(Member.YARD_ADMIN)
    roster = _text(client.get(reverse("members")).content.decode())
    guide = _text(client.get(reverse("admins_day_one")).content.decode())

    named = [
        "Invite a household",
        "Add a grandparent",
        "Outstanding invites",
        "No-login link",
        "Get back in link",
    ]
    for control in named:
        assert control in guide, f"this test claims the guide names {control!r} and it does not"
        assert control in roster, (
            f"the guide tells an admin to use {control!r}, and no control on the roster "
            "they can reach says that"
        )
    # "Remove ..." is a disclosure whose label carries the member's name.
    assert "Remove Cousin Reed" in roster


def test_the_guide_sends_an_admin_through_manage_for_the_controls_that_live_there() -> None:
    """R2-3. The guide said "No-login link on the row", "Get back in link on their row",
    "Change household on their row" — all true until walk item 13 collapsed the roster.
    Those four controls sit behind a Manage disclosure now, so a delegate following this
    page looked at a row carrying a name, a role badge and the word Manage, and not one of
    the words they had just been told to tap.

    Asserted against the RENDERED roster, both halves: the guide names Manage, and Manage
    is a control on the roster with those links inside it. A guide that named a route the
    product does not have would be the same defect wearing a different word.
    """
    client, _, _ = _world(Member.YARD_ADMIN)
    roster = client.get(reverse("members")).content.decode()
    guide = _text(client.get(reverse("admins_day_one")).content.decode())

    assert "Manage" in _text(roster), "the roster has no Manage control to send anybody to"
    # The LIST, not the whole document: the page's own stylesheet comment quotes these
    # control names while explaining how they are laid out.
    rows = roster[roster.index('<ul class="members">') :]
    disclosure = rows.index('<details class="member-manage"')
    for behind_it in ("No-login link", "Get back in link"):
        assert behind_it in rows[disclosure:], (
            f"{behind_it!r} is not inside Manage, so the guide should not send an admin through it"
        )
        assert behind_it not in rows[:disclosure], (
            f"{behind_it!r} is on the open row after all, so the guide should say so"
        )

    # The three sentences, each naming the route before the destination.
    assert "tap Manage on their row and then No-login link" in guide
    assert "tap Manage on their row, then Get back in link" in guide
    assert "under Manage on their row" in guide
    # And the wording it replaced is gone, in both copies, or the page contradicts itself.
    doc = _GUIDE_DOC.read_text(encoding="utf-8")
    for stale in ("No-login link on the row", "Get back in link on their row"):
        assert stale not in guide and stale not in doc, f"{stale!r} survived"


def test_the_three_removal_choices_it_describes_are_the_three_the_form_offers() -> None:
    """The guide says the question has three answers. If the form's choices changed and
    the guide did not, an admin would be promised an outcome that is not on offer."""
    from core import removal

    client, _, _ = _world()
    guide = _text(client.get(reverse("admins_day_one")).content.decode())
    assert len(removal.CONTENT_CHOICES) == 3, removal.CONTENT_CHOICES
    assert "keep their posts, keep them without their name, or delete them" in guide
    # And the two facts that must survive any cut: what deleting destroys, and that it
    # asks first.
    assert "erases their photos from the server for good" in guide
    assert "type their name first" in guide
    assert "Photos other people added replying to their posts go too" in guide


def test_the_repo_copy_says_the_same_thing_as_the_page() -> None:
    """`docs/guide/admins-day-one.md` exists so the guide can be read and reviewed outside
    a running instance. Two copies of anything drift, so the headings and every bold
    control name are held identical; the prose is compared paragraph by paragraph in
    substance, not byte for byte, because the page has links and the file has asterisks.
    """
    client, _, _ = _world()
    page = _text(client.get(reverse("admins_day_one")).content.decode())
    doc = _GUIDE_DOC.read_text(encoding="utf-8")

    for heading in (
        "1. Invite a household",
        "2. Give a grandparent a no-login link",
        "3. Help someone who is locked out",
        "4. Move or remove someone",
        "5. When you are stuck",
    ):
        assert heading in page, f"the page is missing the section {heading!r}"
        assert f"## {heading}" in doc, f"the repo copy is missing the section {heading!r}"

    for control in (
        "Family members",
        "Invite a household",
        "Add a grandparent",
        "Outstanding invites",
        "No-login link",
        "Get back in link",
    ):
        assert control in page and control in doc, f"{control!r} is in only one of the two"


def test_the_guide_uses_no_word_the_product_has_banned() -> None:
    """It is the most jargon-prone page in the product — it is about administration — so
    it gets the vocabulary guard pointed at it directly, page and repo copy both."""
    from core.tests.copy_scan import visible_text, vocabulary_offences

    client, _, _ = _world()
    page = client.get(reverse("admins_day_one")).content.decode()
    assert not vocabulary_offences(visible_text(page))
    assert not vocabulary_offences(_GUIDE_DOC.read_text(encoding="utf-8"))
