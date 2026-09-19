"""AGPL section 13 offers the source to a NETWORK user, so the running program must say so.

Backyard is AGPL-3.0-or-later and told a remote user nothing: no licence, no repository link,
nothing in any served page. The obligation is not discharged by the repository — the person
owed the offer is the one using the software over a network, and she may never see the
repository. That is the entire point of section 13 as distinct from section 4.

WHERE the offer lives changed on 2026-09-19 (owner direction 1). It used to be a line in the
footer of all thirty-odd screens, including a grandparent's, where it was the second-loudest
sentence on a page of family photographs. Section 13 requires that the source be OFFERED; it
does not require that the offer be printed under every picture. It now lives on /about/, one
tap from Settings and one tap from the sign-in page.

So these tests WALK to it rather than grepping for a string:

* a signed-out stranger — the commonest network user — is offered a route from sign-in;
* a signed-in member is offered a route from Settings;
* and the one surface that cannot link anywhere still carries the offer in its own text.

The grandparent's no-login page is the ruled EXCEPTION, and it has its own test asserting
the absence. It carried the offer until 2026-09-19 because it is standalone and S-601 gives
it no href but its own — but /about/ is public and unauthenticated, so the offer is reachable
by anyone who wants it, and printing a licence name and a GitHub URL on a page of family
photographs was never what section 13 asked for. See walk item 20.
"""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core import elder_tokens
from core.models import Member, Pod, PodMembership, Yard
from core.tests.comment_stripping import without_comments

_REPO = "github.com/AIJSAI/backyard"
_BACKEND = "django.contrib.auth.backends.ModelBackend"
User = get_user_model()


def _family() -> tuple[Yard, Pod]:
    yard = Yard.objects.create(name="Y", slug="y")
    pod = Pod.objects.create(name="P")
    pod.yards.set([yard])
    return yard, pod


def _hrefs(html: str) -> set[str]:
    return set(re.findall(r'href="([^"]+)"', html))


@pytest.mark.django_db
def test_the_about_page_carries_the_offer() -> None:
    """The page the two routes below lead to. Asserted first, so a failure downstream
    reads as "the route is broken" rather than "the offer is gone"."""
    page = Client().get(reverse("about"))
    assert page.status_code == 200
    html = page.content.decode()
    assert _REPO in html, "the About page makes no source offer at all (AGPL section 13)"
    assert "AGPL" in html


@pytest.mark.django_db
def test_a_signed_out_stranger_is_offered_a_route_to_the_source() -> None:
    """The surface an unauthenticated stranger reaches, which is most network users.

    Walked, not grepped: the assertion is that the sign-in page OFFERS the route and the
    route answers. A test that looked for the repository string on the login page would
    have passed on a footer line the owner asked to remove, and would fail here for a
    cosmetic reason rather than a legal one.
    """
    html = Client().get(reverse("account_login")).content.decode()
    about = reverse("about")
    assert about in _hrefs(html), (
        "a network user who cannot sign in is offered no route to the source (AGPL section 13)"
    )
    assert _REPO in Client().get(about).content.decode()


@pytest.mark.django_db
def test_a_signed_in_member_is_offered_a_route_to_the_source() -> None:
    """The other half of the network-user population: somebody already inside. Two hops,
    the way a person walks it — the header's Settings, then the link on that page."""
    _, pod = _family()
    user = User.objects.create_user(username="m")
    member = Member.objects.create(display_name="M", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)

    feed = client.get(reverse("feed")).content.decode()
    settings_url = reverse("profile_edit")
    assert settings_url in _hrefs(feed), "no route into settings from the feed"

    settings_page = client.get(settings_url).content.decode()
    about = reverse("about")
    assert about in _hrefs(settings_page), (
        "a signed-in member is offered no route to the source from anywhere they stand"
    )
    assert _REPO in client.get(about).content.decode()


@pytest.mark.django_db
def test_the_no_login_surface_no_longer_prints_the_licence_at_a_grandparent() -> None:
    """The inverse of what this file used to assert here, and the walk's item 20.

    The offer was kept on this one page while it came off every other, on the reasoning
    that this surface can link nowhere (S-601) and so could reach /about/ by no route.
    The 2026-09-19 walk overruled that: she is not a network user shopping for source
    code, she is a grandmother looking at photographs, and the licence of the software
    was the second-loudest sentence on her page.

    Section 13 is satisfied by /about/, which is PUBLIC and unauthenticated — the
    stranger test above walks a signed-out visitor to it from the sign-in page, and
    anybody who wants the source, including whoever set her link up, has that route. The
    obligation is to offer the source to a network user; it is not to print the offer
    under every photograph.

    The help line stays. It is asserted here too, so removing the licence line can never
    take the one sentence on this page she might actually need along with it.
    """
    _, pod = _family()
    member = Member.objects.create(display_name="Nana")
    PodMembership.objects.create(member=member, pod=pod)
    raw = elder_tokens.mint(member)

    client = Client()
    client.get(reverse("elder_enter", args=[raw]))  # exchanges the token for a cookie
    page = client.get(reverse("elder_feed"))
    assert page.status_code == 200, page.status_code
    html = without_comments(page.content.decode())

    assert _REPO not in html, "the grandparent's page is printing a source-code URL at her"
    assert "AGPL" not in html, "the grandparent's page is printing a licence name at her"
    assert "Need help? Contact" in html, (
        "the help line went with the licence line. It is the one thing on this page she "
        "might need, and it has no route to a help page (S-601), so it lives here."
    )


def test_every_link_less_standalone_page_carries_the_offer_itself() -> None:
    """Denominator, on the template sources.

    A standalone page — a full HTML document that `{% extends %}` nothing — inherits no
    footer and no chrome, so it has to make the offer itself or find a link. 500.html
    cannot link: it is rendered when the app is broken enough that resolving a URL may
    not work, so it says the offer in its own text. `base.html` can: every page built on
    it reaches /about/ from Settings, which the walked tests above prove rather than
    assume. `elder_feed.html` is the third, and it is the deliberate hole — the test
    above it asserts the offer is NOT there and says why.

    Computed rather than declared. The list was once ("base.html", "elder_feed.html") and
    a THIRD standalone page existed — src/templates/500.html — which two named templates
    could not notice.
    """
    from pathlib import Path

    core_templates = Path(__file__).resolve().parents[1] / "templates" / "core"
    project_templates = Path(__file__).resolve().parents[2] / "templates"
    # Read each template ONCE and carry the text with the path: three reads of a file
    # another test may be rewriting are three chances to disagree about what it says.
    sources = {
        path: path.read_text()
        for path in list(core_templates.glob("*.html")) + list(project_templates.glob("*.html"))
    }
    standalone = sorted(
        path for path, text in sources.items() if "{% extends" not in text and "<html" in text
    )
    assert len(standalone) >= 3, (
        f"only {len(standalone)} standalone templates found ({[p.name for p in standalone]}); "
        "the globs are wrong, so this check is inspecting almost nothing"
    )
    # base.html is the shared frame; it reaches the offer by link, and the two walked
    # tests above are what hold that. elder_feed.html is the ruled exception (walk item
    # 20, 2026-09-19): the offer is reachable at /about/ without signing in, and printing
    # it on a grandmother's photo album is not what section 13 asks for. Both are named
    # here so each exemption is visible rather than implied by an absence — and neither is
    # unguarded: `test_the_no_login_surface_no_longer_prints_the_licence_at_a_grandparent`
    # asserts the elder page's side of it in both directions.
    exempt = {"base.html", "elder_feed.html"}
    for path in standalone:
        name = path.name
        if name in exempt:
            continue
        # ALL comment syntaxes, via the shared helper. This test originally stripped only
        # `{% comment %}` -- the identical hole that had already been fixed twice, and both
        # templates use `{# ... #}` too, so the offer could have been moved into one and
        # still satisfied the check.
        source = without_comments(sources[path])
        assert _REPO in source, (
            f"{name} is a standalone page — it extends nothing, so it inherits no footer — "
            "and it cannot link away either. It carries no source offer outside its "
            "comments. AGPL section 13 requires a network user be OFFERED the source; a "
            "page that never makes the offer does not."
        )
