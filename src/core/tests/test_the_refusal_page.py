"""A refused action answers the product's own page, not Django's bare one.

Until 2026-09-19 there was no `src/templates/403.html`. Django's default handler403
(`django.views.defaults.permission_denied`) looks the template up BY NAME and, not
finding it, falls back to `ERROR_PAGE_TEMPLATE`: an unstyled Times-New-Roman document
reading "403 Forbidden" above an empty paragraph, with no header, no footer and no way
back. That is what a family member got for tapping something they may not do, on a
product whose 404 page is careful and calm.

No `handler403` is registered in `src/config/urls.py`, and none is needed: adding the
file is the whole fix, which is exactly why the absence was so easy to miss. These tests
hold both halves of it — the file is REACHED on a real refusal, and it renders for a
reader with no session, because a template that only works signed in is a 500 waiting on
the one request that reaches it.

The exception message is asserted ABSENT on purpose. The default handler passes
`{"exception": str(exception)}` into the template, and the refusals raised across this
product name people and households ("‹first name› is not in ‹household›") or say an
internal noun out loud ("You can only post to a pod you belong to"). Printing them would
turn a copy fix into a disclosure.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import Client, RequestFactory
from django.urls import reverse
from django.views.defaults import permission_denied

from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
# The sentence the product refuses with today, quoted so the "never printed" assertion
# below is about a real string and not a hypothetical one.
_RAW_REFUSAL = "You cannot edit this person's profile."


def _two_cousins() -> tuple[Member, Member]:
    """Two plain members of one household. Neither may edit the other's profile, and
    both can SEE each other — which is what makes this a 403 rather than the
    byte-identical 404 a cross-side attempt answers (S-202)."""
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds")
    pod.yards.set([yard])
    cousins = []
    for username, name in (("cousin", "Cousin Reed"), ("other", "Other Reed")):
        member = Member.objects.create(
            display_name=name, user=User.objects.create_user(username=username)
        )
        PodMembership.objects.create(member=member, pod=pod)
        cousins.append(member)
    return cousins[0], cousins[1]


def test_a_refused_action_renders_the_products_own_403_page() -> None:
    """Walked through a real route rather than rendered directly: what is under test is
    that Django's handler FINDS the file, which is the part that was missing."""
    actor, other = _two_cousins()
    assert actor.user is not None
    client = Client()
    client.force_login(actor.user, backend=_BACKEND)

    response = client.get(reverse("managed_profile_edit", args=[other.pk]))
    assert response.status_code == 403
    assert "403.html" in [template.name for template in response.templates if template.name]

    body = response.content.decode()
    assert "You Do Not Have Access" in body
    assert "Your account does not have permission to do that." in body
    # Django's bare fallback, which is what this page replaced.
    assert "<h1>403 Forbidden</h1>" not in body


def test_the_refusal_page_carries_the_site_chrome_and_a_way_back() -> None:
    """The bare page had no header, no footer and no link out. A refusal is a dead end
    only if the page makes it one."""
    actor, other = _two_cousins()
    assert actor.user is not None
    client = Client()
    client.force_login(actor.user, backend=_BACKEND)

    body = client.get(reverse("managed_profile_edit", args=[other.pk])).content.decode()
    assert "<footer" in body, "the refusal page does not inherit the site footer"
    assert 'href="/"' in body, "the refusal page offers no way back"


def test_the_refusal_page_never_prints_the_exception_message() -> None:
    """`permission_denied` hands the template `str(exception)`. Rendering it would put an
    internal sentence — and in several cases a relative's name and their household — in
    front of whoever tripped the refusal."""
    actor, other = _two_cousins()
    assert actor.user is not None
    client = Client()
    client.force_login(actor.user, backend=_BACKEND)

    body = client.get(reverse("managed_profile_edit", args=[other.pk])).content.decode()
    assert _RAW_REFUSAL not in body
    assert "PermissionDenied" not in body


def test_it_renders_for_a_reader_with_no_session() -> None:
    """A page that raises when rendered signed out is a 500 on the one request that
    reaches it. Driven straight through Django's handler, because every route that can
    refuse is behind a login redirect, so a client walk can never reach this state."""
    factory = RequestFactory()
    request = factory.get("/directory/1/edit/")
    request.user = AnonymousUser()

    response = permission_denied(request, PermissionDenied(_RAW_REFUSAL))
    assert response.status_code == 403
    body = response.content.decode()
    assert "You Do Not Have Access" in body
    assert _RAW_REFUSAL not in body
    # The footer's public help sentence, which is what a signed-out reader is owed here.
    assert "Need help? Contact the person who invited you." in body
