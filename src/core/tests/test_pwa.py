"""The PWA install surface (S-103) and the Safari eviction rule (ADR-002).

Properties under test: the manifest is valid and installable (name, standalone,
192 and 512 icons, a start_url); the icons are real PNGs at the declared sizes;
the service worker is served as JavaScript with a fetch handler and caches
nothing; member pages link the manifest and register the worker; and the elder
token surface references NEITHER the manifest NOR the worker, because an elder
on a bare token link is exactly the intermittent visitor Safari evicts a worker
from (ADR-002).
"""

from __future__ import annotations

import io
import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from PIL import Image

from core import digest_links, elder_tokens
from core.models import DigestIssue, Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_TEST_PW = "a-Strong-passphrase-9"


def test_manifest_is_valid_and_installable() -> None:
    response = Client().get(reverse("manifest"))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/manifest+json"
    data = json.loads(response.content)
    assert data["name"] and data["short_name"]
    assert data["display"] == "standalone"
    assert data["start_url"] == "/feed/"
    sizes = {icon["sizes"] for icon in data["icons"]}
    assert "192x192" in sizes and "512x512" in sizes  # Chrome's installability bar
    assert any(icon["purpose"] == "maskable" for icon in data["icons"])  # adaptive launchers


@pytest.mark.parametrize(
    ("name", "expected"),
    [("icon_192", 192), ("icon_512", 512), ("icon_maskable_512", 512)],
)
def test_icons_are_real_pngs_at_the_declared_size(name: str, expected: int) -> None:
    response = Client().get(reverse(name))
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    image = Image.open(io.BytesIO(response.content))
    assert image.format == "PNG"
    assert image.size == (expected, expected)


def test_service_worker_is_minimal_javascript_that_caches_nothing() -> None:
    response = Client().get(reverse("service_worker"))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/javascript"
    assert response["Cache-Control"] == "no-cache"  # always re-checked for updates
    body = response.content.decode()
    assert "addEventListener('fetch'" in body  # the installability requirement
    # Minimal by design (ADR-002): no cache API use anywhere.
    assert "caches.open" not in body and "cache.put" not in body and "cache.add" not in body


def test_member_pages_link_the_manifest_and_register_the_worker() -> None:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Cousins")
    pod.yards.set([yard])
    user = User.objects.create_user(username="mom", password=_TEST_PW)
    member = Member.objects.create(display_name="Mom", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")

    body = client.get(reverse("feed")).content.decode()
    assert reverse("manifest") in body  # the manifest link
    assert reverse("service_worker") in body  # the registration
    assert "serviceWorker" in body


def test_the_digest_token_surface_is_worker_free(world_dates: None = None) -> None:
    """#44 review MEDIUM: the /d/ digest surface shares base.html with member
    pages but mints no session, so it must NOT plant a root-scope worker on an
    intermittent digest recipient (the Safari eviction rule applies to every
    token surface, not only the elder one)."""
    import datetime

    from django.utils import timezone

    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Cousins")
    pod.yards.set([yard])
    member = Member.objects.create(display_name="Nana")
    PodMembership.objects.create(member=member, pod=pod)
    now = timezone.now()
    issue = DigestIssue.objects.create(
        member=member, yard=yard, window_start=now - datetime.timedelta(days=7), window_end=now
    )
    raw = digest_links.mint(issue)
    body = Client().get(reverse("digest_web", args=[raw])).content.decode()
    assert "serviceWorker" not in body
    assert "service-worker.js" not in body
    assert "manifest" not in body  # anonymous /d/ recipient gets no worker or manifest


def test_the_elder_surface_never_depends_on_the_service_worker() -> None:
    """The Safari eviction rule (ADR-002): the elder page is standalone HTML with
    no manifest and no worker, so an intermittent elder is never left with an
    evicted worker serving a broken surface."""
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Cousins")
    pod.yards.set([yard])
    nana = Member.objects.create(display_name="Nana", kinship_name="Nana")
    PodMembership.objects.create(member=nana, pod=pod)
    Post.objects.create(author=nana, pod=pod, body="a post")
    raw = elder_tokens.mint(nana)

    client = Client()
    client.get(reverse("elder_enter", args=[raw]))
    body = client.get(reverse("elder_feed")).content.decode()
    assert "serviceWorker" not in body
    assert "service-worker.js" not in body
    assert "manifest" not in body  # neither the link nor the word
