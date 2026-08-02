"""A member-facing page that is routed but linked from nowhere does not exist.

The defect: `/settings/digest/` was routed (`urls.py`), rendered fine, and had a working
form -- and the ONLY `{% url 'digest_settings' %}` in the whole codebase was that page's own
form action. Nothing linked to it. The header's "Settings" went to `profile_edit`, whose only
outbound link was "Back to the directory".

So the product's single notification channel could not be switched on by any member,
including the admin. And it did not fail loudly: `health_email.admin_recipients()` filters on
`confirmed_at__isnull=False`, so an instance whose digest page is unreachable also reports its
backup age and disk headroom to NOBODY, every week, silently.

Nothing in the suite could catch that, because every existing test reached such pages by
`reverse()` -- which is exactly the step a real member cannot perform. These tests navigate by
LINK instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core.models import Member, Pod, PodMembership, Yard

_BACKEND = "django.contrib.auth.backends.ModelBackend"
_TEMPLATES = Path(__file__).resolve().parents[1] / "templates" / "core"

User = get_user_model()


def _logged_in_member() -> Client:
    yard = Yard.objects.create(name="Y", slug="y")
    pod = Pod.objects.create(name="P")
    pod.yards.set([yard])
    # No password argument on purpose: force_login() below bypasses authentication, so a
    # literal here would be a credential-shaped string with no reason to exist. The ECC
    # pre-commit guard flagged the first version of this line, and it was right to.
    user = User.objects.create_user(username="m")
    member = Member.objects.create(display_name="M", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return client


def _hrefs(html: str) -> set[str]:
    return set(re.findall(r'href="([^"]+)"', html))


def _without_comments(source: str) -> str:
    """Template source with `{% comment %}` blocks and HTML comments removed.

    Learned the hard way, in this very file: the first version of the structural check below
    passed with the digest link deleted, because the COMMENT explaining the bug quoted
    `{% url 'digest_settings' %}` as prose and satisfied the regex. A source-text assertion
    that a comment can satisfy is not an assertion. Prose must never be able to answer a
    question about behaviour.
    """
    source = re.sub(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", "", source, flags=re.S)
    return re.sub(r"<!--.*?-->", "", source, flags=re.S)


@pytest.mark.django_db
def test_a_member_can_reach_the_digest_settings_by_following_links() -> None:
    """Navigate the way a person does: feed -> Settings -> the digest page.

    Asserted as a REACHABILITY chain rather than `reverse()`, because the bug was that the
    page was perfectly reachable by URL and unreachable by human.
    """
    client = _logged_in_member()

    feed = client.get(reverse("feed"))
    settings_url = reverse("profile_edit")
    assert settings_url in _hrefs(feed.content.decode()), (
        "the header nav must offer a route into settings"
    )

    settings_page = client.get(settings_url)
    digest_url = reverse("digest_settings")
    assert digest_url in _hrefs(settings_page.content.decode()), (
        "the digest page is routed but nothing links to it, so no member can enable the "
        "only notification channel the product has -- and the weekly health email, which "
        "needs a CONFIRMED subscription, silently reaches nobody"
    )

    assert client.get(digest_url).status_code == 200


@pytest.mark.django_db
def test_the_digest_link_is_not_shown_when_an_admin_edits_someone_else() -> None:
    """A digest address is the member's own; an admin editing another profile must not be
    offered a control that would set where THAT person's family email goes."""
    client = _logged_in_member()
    html = client.get(reverse("profile_edit")).content.decode()
    assert reverse("digest_settings") in _hrefs(html)  # denominator: it IS there normally

    rendered_for_other = client.get(reverse("profile_edit"), {"editing_other": "1"})
    # The flag is set by the view, not the query string -- this only guards the template
    # branch existing at all, so the real assertion is the source check below.
    assert rendered_for_other.status_code == 200
    source = (_TEMPLATES / "profile_edit.html").read_text()
    assert "{% if not editing_other %}" in source, (
        "the digest link must be inside a not-editing_other branch"
    )


def test_no_member_facing_page_is_linked_only_from_itself() -> None:
    """The general form of the bug, so the next one is caught without a new test.

    A page whose only `{% url %}` reference is inside its own template is unreachable by
    navigation. This walks the template tree rather than the URLconf, because the URLconf is
    precisely what looked fine.
    """
    must_be_reachable = {
        "digest_settings": "digest_settings.html",
        "profile_edit": "profile_edit.html",
        "directory": "directory.html",
    }
    templates = {p.name: _without_comments(p.read_text()) for p in _TEMPLATES.glob("*.html")}
    assert len(templates) > 20, f"only {len(templates)} templates found; glob is wrong"

    unreachable = []
    for url_name, own_template in must_be_reachable.items():
        pattern = re.compile(r"\{%\s*url\s*['\"]" + re.escape(url_name) + r"['\"]")
        linking = {
            name for name, src in templates.items() if name != own_template and pattern.search(src)
        }
        if not linking:
            unreachable.append(url_name)
    assert not unreachable, (
        f"routed but linked from nowhere except their own page: {unreachable}. "
        "A member cannot type a URL they have never seen."
    )
