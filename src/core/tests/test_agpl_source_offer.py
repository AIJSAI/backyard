"""AGPL section 13 offers the source to a NETWORK user, so the running program must say so.

Backyard is AGPL-3.0-or-later and told a remote user nothing: no licence, no repository link,
nothing in any served page. The obligation is not discharged by the repository — the person
owed the offer is the one using the software over a network, and she may never see the
repository. That is the entire point of section 13 as distinct from section 4.

The elder surface is asserted separately and deliberately. `elder_feed.html` is STANDALONE by
design (it does not extend `base.html`, so it carries no session-bearing chrome), which means
a footer added to the base template renders on every page EXCEPT the one an elder actually
uses — and she is exactly the network user this clause exists for.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from core import elder_tokens
from core.models import Member, Pod, PodMembership, Yard

_REPO = "github.com/AIJSAI/backyard"


def _family() -> tuple[Yard, Pod]:
    yard = Yard.objects.create(name="Y", slug="y")
    pod = Pod.objects.create(name="P")
    pod.yards.set([yard])
    return yard, pod


@pytest.mark.django_db
def test_the_login_page_offers_the_source() -> None:
    """The surface an unauthenticated stranger reaches, which is most network users."""
    html = Client().get(reverse("account_login")).content.decode()
    assert _REPO in html, "a network user is offered no route to the source (AGPL section 13)"
    assert "AGPL" in html


@pytest.mark.django_db
def test_the_elder_surface_offers_the_source() -> None:
    """The one that would have been missed: standalone template, no base.html."""
    _, pod = _family()
    member = Member.objects.create(display_name="Nana")
    PodMembership.objects.create(member=member, pod=pod)
    raw = elder_tokens.mint(member)

    client = Client()
    client.get(reverse("elder_enter", args=[raw]))  # exchanges the token for a cookie
    page = client.get(reverse("elder_feed"))
    assert page.status_code == 200, page.status_code
    html = page.content.decode()

    assert _REPO in html, (
        "the elder path renders no source offer. It does not extend base.html, so a footer "
        "added there reaches every page except the one an elder actually uses — and she is "
        "the network user AGPL section 13 exists for."
    )
    assert "AGPL" in html


@pytest.mark.django_db
def test_the_offer_is_not_only_on_one_template() -> None:
    """Denominator: both surfaces, so a single shared fixture cannot make this vacuous.

    If the two assertions above ever pass because some middleware injects the string
    globally, this still holds — but it also means the templates could each lose their line
    without a failure. Asserted on the template sources so the offer is where it is claimed
    to be, not merely present in a response by accident.
    """
    from pathlib import Path

    templates = Path(__file__).resolve().parents[1] / "templates" / "core"
    for name in ("base.html", "elder_feed.html"):
        source = (templates / name).read_text()
        # Comments stripped first: prose about the offer must not satisfy a check for it.
        import re

        source = re.sub(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", "", source, flags=re.S)
        assert _REPO in source, f"{name} carries no source offer outside its comments"
