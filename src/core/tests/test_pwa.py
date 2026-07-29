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


def test_the_installed_identity_matches_the_shipped_design_system() -> None:
    """S-103: the PWA's colours must be the app's colours.

    They were not. The manifest kept the design-v2 navy (#234a78) and its cool near-white
    ground after the founder REJECTED v2 and every surface moved to sign green — so the
    one artefact a member sees every day WITHOUT opening the app, the home-screen icon and
    its splash screen, matched nothing in the product.

    Read out of base.html rather than hardcoded here, so this fails when the two drift
    again rather than pinning a second copy of the palette that can rot independently.
    """
    import json
    import re
    from pathlib import Path

    from django.test import Client
    from django.urls import reverse

    base = (Path(__file__).resolve().parents[1] / "templates" / "core" / "base.html").read_text()
    light = base[base.index(":root") :]
    green = re.search(r"--green:\s*(#[0-9a-fA-F]{6})", light)
    paper = re.search(r"--paper:\s*(#[0-9a-fA-F]{6})", light)
    assert green and paper, "could not read --green/--paper out of the design system"

    manifest = json.loads(Client().get(reverse("manifest")).content)
    assert manifest["theme_color"] == green.group(1), (
        f"the PWA theme colour {manifest['theme_color']} is not the app's brand green "
        f"{green.group(1)} — an installed icon that matches nothing in the product"
    )
    assert manifest["background_color"] == paper.group(1)


def test_no_surface_still_carries_a_rejected_ground_or_accent() -> None:
    """The founder rejected design v2 by name. A stray rejected colour anywhere is a piece
    of an identity he already turned down, still shipping.

    WIDENED 2026-07-29. This guard pinned exactly one value — the v2 navy #234a78 — and
    that narrowness cost a review cycle: the v3.2 visual pass warmed the page ground to a
    linen cream chasing "warmth" from the brief, the founder rejected it on sight as
    belonging to the same run he had already turned down, and nothing in the suite said a
    word, because the cream is not the navy. A guard that names ONE value from a rejected
    direction implies the direction is covered when only that value is. Each entry below
    is a colour a founder has rejected; add to the list rather than narrowing it."""
    import re as _re
    from pathlib import Path

    def _strip_comments(text: str, suffix: str) -> str:
        """Prose is allowed to NAME the old colour — several comments record the v2->v3
        migration deliberately. Only a live value is a defect, so comments come out first
        rather than the guard being weakened with a file allowlist that would rot."""
        text = _re.sub(r"<!--.*?-->", "", text, flags=_re.S)
        text = _re.sub(r"/\*.*?\*/", "", text, flags=_re.S)
        text = _re.sub(r"\{#.*?#\}", "", text, flags=_re.S)
        text = _re.sub(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", "", text, flags=_re.S)
        if suffix == ".py":
            text = _re.sub(r'"""(?:.|\n)*?"""', "", text)
            text = "\n".join(
                line for line in text.splitlines() if not line.lstrip().startswith("#")
            )
        return text

    # hex (no leading #) -> what it was and who rejected it
    rejected = {
        "234a78": "design-v2 navy",
        "f7f4ed": "the v3.2 linen-cream page ground",
        "efeade": "the v3.2 linen-cream sunk surface",
    }

    src = Path(__file__).resolve().parents[2]
    offenders = []
    for path in list(src.rglob("*.py")) + list(src.rglob("*.html")):
        if "__pycache__" in str(path) or path.name == "test_pwa.py":
            continue
        live = _strip_comments(path.read_text(errors="ignore"), path.suffix)
        for hexval, what in rejected.items():
            if hexval in live:
                offenders.append(f"{path.relative_to(src)}: #{hexval} ({what})")
    assert not offenders, f"a rejected colour is still shipping as a LIVE value in: {offenders}"


def test_the_rejected_colour_guard_is_non_vacuous() -> None:
    """Guard the guard, twice over. The comment-stripper must not swallow a live value,
    and the list must actually contain the colour whose absence it is asserting — a typo
    in a hex would make the loop above pass over a shipping defect in silence."""
    import re as _re
    from pathlib import Path

    source = Path(__file__).read_text()
    # The rejected map is real and holds more than the one value it started with.
    hexes = _re.findall(r'"([0-9a-f]{6})": "', source)
    assert len(hexes) >= 3, f"the rejected-colour list collapsed to {hexes}"
    for h in ("234a78", "f7f4ed"):
        assert h in hexes, f"{h} fell out of the rejected list"
    # And the live palette really is the accepted one, so the guard has something to hold.
    base = (Path(__file__).resolve().parents[1] / "templates" / "core" / "base.html").read_text()
    paper = _re.search(r"--paper:\s*(#[0-9a-fA-F]{6})", base)
    assert paper and paper.group(1).lower() == "#fbfcfb", (
        f"--paper is {paper.group(1) if paper else 'missing'}, not the accepted ground"
    )
