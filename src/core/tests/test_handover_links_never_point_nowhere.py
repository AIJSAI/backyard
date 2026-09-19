"""BACKYARD_BASE_URL is the whole hand-over, and it fails silently (design walk).

Every link the product hands out is built from it (TS-DJ-14): the household invite, the
elder link, every digest deep link. Unset or stale, the admin sees a link that looks
completely normal, texts it, prints its QR — and the family member who opens it gets the
bare 404. No error, no log line, no screen that looks wrong. The two new yard admins hand
out both kinds in one sitting, so this is a first-day failure, not an edge case.

Two mechanisms, tested here together because they are one rule with two audiences:

1. A real deployment refuses to boot on it. The signal is DJANGO_ALLOWED_HOSTS naming a
   non-loopback host — Django cannot serve a domain missing from that list — and NOT
   DEBUG, because the documented clean-machine path (docker-compose.yml with no .env)
   and this very test suite both run with DJANGO_DEBUG=0 and the localhost default.
2. Every mint surface states the host its link opens at, in a plain sentence under the
   link, so a wrong value is caught by a relative at hand-over rather than by the
   grandmother who was texted it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from config.base_url_guard import is_local_url, validate_base_url
from core.models import Member, Pod, PodMembership, Yard

User = get_user_model()
_TEST_PW = "a-Strong-passphrase-9"
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_LOCAL_HOSTS = ["localhost", "127.0.0.1"]
_SERVED_HOSTS = ["family.example", "localhost", "127.0.0.1"]  # the prod overlay's shape


# --- the boot guard, exercised directly so the rule is never vacuous ---


def test_a_served_instance_refuses_to_boot_with_the_localhost_default() -> None:
    """The walked defect: the operator set a domain, never set BACKYARD_BASE_URL, and
    every link handed out pointed at a machine only they can open."""
    with pytest.raises(RuntimeError, match="BACKYARD_BASE_URL"):
        validate_base_url(
            base_url="http://localhost:8000", allowed_hosts=_SERVED_HOSTS, debug=False
        )


def test_a_served_instance_refuses_to_boot_with_an_unset_or_empty_value() -> None:
    for value in ("", "   "):
        with pytest.raises(RuntimeError, match="BACKYARD_BASE_URL is not set"):
            validate_base_url(base_url=value, allowed_hosts=_SERVED_HOSTS, debug=False)


def test_the_error_names_the_variable_and_the_host_it_is_meant_to_be() -> None:
    """Plain enough to act on without reading the source: the variable to set, the host
    the instance is already configured to serve, and what goes wrong if it is left."""
    with pytest.raises(RuntimeError) as raised:
        validate_base_url(
            base_url="http://127.0.0.1:8000", allowed_hosts=_SERVED_HOSTS, debug=False
        )
    message = str(raised.value)
    assert "BACKYARD_BASE_URL" in message
    assert "family.example" in message
    assert "invite link" in message and "elder link" in message


def test_production_keeps_booting() -> None:
    """docker-compose.prod.yml derives BACKYARD_BASE_URL from BACKYARD_DOMAIN, so the
    deployment this guard is written for must sail through it."""
    validate_base_url(
        base_url="https://family.example", allowed_hosts=_SERVED_HOSTS, debug=False
    )  # must not raise


def test_the_local_compose_and_the_test_settings_keep_booting() -> None:
    """Both run DJANGO_DEBUG=0 with the localhost default, which is CORRECT there: the
    links are meant to open on the machine running them. Keying the guard off DEBUG
    alone would have refused to boot the clean-machine path this repo documents."""
    validate_base_url(base_url="http://localhost:8000", allowed_hosts=_LOCAL_HOSTS, debug=False)
    validate_base_url(base_url="", allowed_hosts=_LOCAL_HOSTS, debug=False)
    validate_base_url(base_url="http://localhost:8000", allowed_hosts=[], debug=False)


def test_a_stale_base_url_is_refused_too() -> None:
    """The domain moved and only one of the two variables did. Django serves the new name;
    every minted link points at the old one, and if that name has lapsed each link hands a
    live bearer token to whoever registered it next."""
    with pytest.raises(RuntimeError, match="not a host this instance serves"):
        validate_base_url(
            base_url="https://old.example",
            allowed_hosts=["new.example", "localhost"],
            debug=False,
        )


def test_a_value_that_is_not_an_absolute_address_is_refused() -> None:
    """`family.example` with no scheme parses to a path, so every link minted from it is a
    relative URL: the same dead hand-over, wearing a plausible value."""
    with pytest.raises(RuntimeError, match="not an absolute"):
        validate_base_url(base_url="family.example", allowed_hosts=["family.example"], debug=False)


def test_a_subdomain_wildcard_and_legal_loopback_spellings_are_understood() -> None:
    """Django's own host rules, so the guard never bricks a configuration Django serves."""
    validate_base_url(
        base_url="https://yard.family.example", allowed_hosts=[".family.example"], debug=False
    )
    for local in (["localhost."], ["[::1]"], [".localhost"]):
        validate_base_url(base_url="http://localhost:8000", allowed_hosts=local, debug=False)


def test_the_guard_is_wired_into_settings_boot() -> None:
    """The rule is only real if settings.py calls it: delete that one line and every test
    above still passes. Boot a real settings import with a served host and no base URL."""
    import os
    import subprocess  # noqa: S404
    import sys

    from django.conf import settings as django_settings

    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "PYTHONPATH": str(django_settings.BASE_DIR),
        "DJANGO_SECRET_KEY": "wired-guard-test-not-a-secret-0123456789abcdef",
        "DJANGO_ALLOWED_HOSTS": "family.example",
        "DJANGO_DEBUG": "0",
    }
    env.pop("BACKYARD_BASE_URL", None)
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", "import django; django.setup()"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode != 0, "settings.py booted without calling the guard"
    assert "BACKYARD_BASE_URL" in result.stderr


def test_a_developers_own_machine_is_exempt() -> None:
    validate_base_url(base_url="http://localhost:8000", allowed_hosts=_SERVED_HOSTS, debug=True)


def test_local_is_a_whole_hostname_never_a_substring() -> None:
    """The guards keyed off this classify an attacker-registrable domain, so the check is
    a parsed-hostname comparison: `"localhost" in url` is true of localhost.evil.com."""
    assert is_local_url("http://localhost:8000")
    assert is_local_url("http://127.0.0.1:8010")
    assert not is_local_url("http://localhost.evil.example/")
    assert not is_local_url("http://127.0.0.1.evil.example/")
    assert not is_local_url("https://family.example")
    # And such a domain in ALLOWED_HOSTS is a served host, so the guard still fires.
    with pytest.raises(RuntimeError, match="BACKYARD_BASE_URL"):
        validate_base_url(
            base_url="http://localhost:8000",
            allowed_hosts=["localhost.evil.example"],
            debug=False,
        )


# --- the host is visible at hand-over, on every surface that mints a link ---


@dataclass
class World:
    yard: Yard
    pod: Pod
    admin: Member
    elder: Member


@pytest.fixture
def world() -> World:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Maternal seed", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])

    def member(name: str, role: str) -> Member:
        user = User.objects.create_user(username=name.lower(), password=_TEST_PW)
        made = Member.objects.create(display_name=name, user=user, role=role)
        PodMembership.objects.create(member=made, pod=pod)
        return made

    return World(
        yard=yard,
        pod=pod,
        admin=member("Boss", Member.INSTANCE_ADMIN),
        elder=member("Nana", Member.MEMBER),
    )


def _client_for(member: Member) -> Client:
    assert member.user is not None
    client = Client()
    client.force_login(member.user, backend=_BACKEND)
    return client


def _intent(client: Client, url: str) -> str:
    body = client.get(url).content.decode()
    match = re.search(r'name="intent" value="([^"]+)"', body)
    assert match, "no intent nonce on the page"
    return match.group(1)


@pytest.mark.django_db
def test_the_invite_result_page_states_the_host_the_link_opens_at(
    world: World, settings: pytest.FixtureRequest
) -> None:
    settings.BASE_URL = "https://family.example"  # type: ignore[attr-defined]
    client = _client_for(world.admin)
    url = reverse("invite_household")
    body = client.post(
        url,
        {
            "household_name": "A new household",
            "yard_ids": [str(world.yard.id)],
            "intent": _intent(client, url),
        },
    ).content.decode()
    assert "https://family.example/join/" in body
    assert "This link opens at family.example." in body


@pytest.mark.django_db
def test_the_elder_link_page_states_the_host_the_link_opens_at(
    world: World, settings: pytest.FixtureRequest
) -> None:
    settings.BASE_URL = "https://family.example"  # type: ignore[attr-defined]
    client = _client_for(world.admin)
    url = reverse("provision_elder", args=[world.elder.id])
    body = client.post(url, {"intent": _intent(client, url)}).content.decode()
    assert "https://family.example/t/" in body
    assert "This link opens at family.example." in body


@pytest.mark.django_db
def test_the_stated_host_is_the_one_in_the_link_including_a_wrong_port(
    world: World, settings: pytest.FixtureRequest
) -> None:
    """The walked shape: served on one port, minting links on another. The sentence is
    read back off the minted link, so it shows the port too — which is the whole point,
    since `localhost` alone would have looked fine on the instance that was walked."""
    settings.BASE_URL = "http://localhost:8000"  # type: ignore[attr-defined]
    client = _client_for(world.admin)
    url = reverse("provision_elder", args=[world.elder.id])
    body = client.post(url, {"intent": _intent(client, url)}).content.decode()
    assert "This link opens at localhost:8000." in body


def test_the_stated_host_never_includes_url_userinfo() -> None:
    """`https://localhost@evil.example/...` opens at evil.example. Printing the raw netloc
    would make the one sentence a non-technical admin glances at read as `localhost`."""
    from core.handover import link_artifacts

    shown = link_artifacts("https://localhost:secret@evil.example:8443/t/TOKEN/")["link_host"]
    assert shown == "evil.example:8443"
