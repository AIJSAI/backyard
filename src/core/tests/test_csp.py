"""Baseline Content-Security-Policy (S-724, TS-DJ-9).

Properties under test: every response carries a tight default-src 'self' policy; script-src
is nonce-based and NOT 'unsafe-inline' (the control that actually blocks an injected inline
script); style-src keeps 'unsafe-inline' for the templates' inline style attributes; and the
nonce in the header matches the nonce on the page's inline <script> tags, with no bare
(nonce-less) inline script slipping through — which the browser would refuse to execute.
"""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_PW = "a-Strong-passphrase-9"
_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _logged_in_member() -> Client:
    yard = Yard.objects.create(name="Y", slug="y")
    pod = Pod.objects.create(name="P")
    pod.yards.set([yard])
    user = User.objects.create_user(username="m", password=_PW)
    member = Member.objects.create(display_name="M", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return client


def _directive(csp: str, name: str) -> str:
    return next(part.strip() for part in csp.split(";") if part.strip().startswith(name))


def test_csp_header_is_a_tight_nonce_based_baseline() -> None:
    csp = _logged_in_member().get(reverse("feed"))["Content-Security-Policy"]
    assert _directive(csp, "default-src") == "default-src 'self'"
    assert _directive(csp, "object-src") == "object-src 'none'"
    assert _directive(csp, "base-uri") == "base-uri 'self'"
    assert _directive(csp, "form-action") == "form-action 'self'"
    assert _directive(csp, "frame-ancestors") == "frame-ancestors 'none'"
    script_src = _directive(csp, "script-src")
    assert "'unsafe-inline'" not in script_src  # the lever that matters: injected scripts don't run
    assert re.search(r"'nonce-[A-Za-z0-9_-]+'", script_src), "script-src must carry a nonce"
    # Inline style attributes/blocks are covered by unsafe-inline; the XSS lever is script.
    assert "'unsafe-inline'" in _directive(csp, "style-src")


def test_the_inline_scripts_carry_the_header_nonce_and_none_are_bare() -> None:
    resp = _logged_in_member().get(reverse("feed"))
    body = resp.content.decode()
    match = re.search(r"'nonce-([A-Za-z0-9_-]+)'", resp["Content-Security-Policy"])
    assert match
    header_nonce = match.group(1)
    # The feed's inline scripts (service-worker registration + client-side resize) carry it.
    assert body.count(f'<script nonce="{header_nonce}">') >= 1
    # No inline <script> without a nonce slipped through (the browser would refuse to run it).
    assert re.search(r"<script(?![^>]*\bnonce=)[^>]*>", body) is None


def test_a_fresh_nonce_per_request() -> None:
    client = _logged_in_member()
    first = re.search(
        r"'nonce-([A-Za-z0-9_-]+)'", client.get(reverse("feed"))["Content-Security-Policy"]
    )
    second = re.search(
        r"'nonce-([A-Za-z0-9_-]+)'", client.get(reverse("feed"))["Content-Security-Policy"]
    )
    assert first and second and first.group(1) != second.group(1)  # not reused across requests


def test_csp_is_present_even_on_an_anonymous_response() -> None:
    # The middleware stamps the policy on every response, including a bare 404, so no surface
    # is left without it.
    assert "default-src 'self'" in Client().get("/does-not-exist/")["Content-Security-Policy"]
