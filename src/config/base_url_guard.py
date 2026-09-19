"""Boot-time validation of the link base URL (TS-DJ-14).

Every link this product hands out is built from `BACKYARD_BASE_URL` and never from
the request's Host header (TS-DJ-14, `core/emailing.py`): the household invite, the
elder link, every digest deep link. That makes one environment variable the single
point of failure for the whole hand-over, and it fails silently. If it is unset or
stale, the admin is shown a link that looks fine, texts it, prints its QR, reads it
down the phone — and the person holding it gets the same bare 404 a revoked link
gets. Nothing in the app is wrong-looking, nothing is logged, and the family finds
out socially, days later, if at all.

So a real deployment refuses to boot on it, the same hard-fail shape as the
SECRET_KEY check and the email transport guard. This lives outside the settings
module so the rule is a plain function the test suite exercises directly;
settings.py calls it once at import.

The production signal is `DJANGO_ALLOWED_HOSTS` naming a host that is not loopback.
Django will not serve a domain missing from that list, so an instance a family can
reach HAS its domain there, and an instance that does not is the documented local
path — `docker-compose.yml` with no `.env`, and the test settings — where the
localhost default is correct and must keep working. DEBUG is deliberately NOT the
signal: the local compose runs `DJANGO_DEBUG=0` too, so keying off it would refuse
to boot the clean-machine repro this repo tells people to start with.
"""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlsplit

# The loopback names, compared as whole hostnames and never as substrings. `"localhost"
# in url` is true for `http://localhost.evil.com` and `"127.0.0.1" in url` for
# `http://127.0.0.1.evil.com`: an attacker-registrable domain that merely CONTAINS the
# word would be classified local and would bypass every guard keyed off this. settings.py
# takes its own local check from here, so there is one definition rather than two.
_LOCAL_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})


def is_local_url(url: str) -> bool:
    """True iff the URL's parsed HOSTNAME is a loopback name."""
    return (urlsplit(url).hostname or "").lower() in _LOCAL_HOSTNAMES


def _public_hosts(allowed_hosts: Sequence[str]) -> list[str]:
    """The ALLOWED_HOSTS entries that are not loopback, i.e. the evidence that somebody
    other than this machine is meant to reach the instance. A leading dot is Django's
    subdomain wildcard, so `.localhost` is still local; `*` is not, and an operator who
    opens the host check that wide is certainly not serving only themselves."""
    return [
        host.strip()
        for host in allowed_hosts
        if host.strip() and host.strip().lower().lstrip(".") not in _LOCAL_HOSTNAMES
    ]


def validate_base_url(*, base_url: str, allowed_hosts: Sequence[str], debug: bool) -> None:
    """Refuse to boot an instance that serves a real host while its links point at
    localhost or at nothing.

    A local-only instance passes: there the localhost default is the correct answer and
    the documented clean-machine path depends on it. A DEBUG instance passes: it is a
    developer's own machine, and the two guards in settings.py already refuse the
    dangerous DEBUG combinations.
    """
    if debug:
        return
    public = _public_hosts(allowed_hosts)
    if not public:
        return
    if not base_url.strip():
        problem = "BACKYARD_BASE_URL is not set"
    elif is_local_url(base_url):
        problem = f"BACKYARD_BASE_URL is a localhost address ({base_url})"
    else:
        return
    raise RuntimeError(
        f"{problem}, but DJANGO_ALLOWED_HOSTS says this instance serves "
        f"{', '.join(public)}. Every invite link, elder link and digest link is built "
        "from BACKYARD_BASE_URL, so every one handed out would open nowhere for the "
        "person who received it, and nothing would say so. Set BACKYARD_BASE_URL to "
        "this instance's own https address; docker-compose.prod.yml derives it from "
        "BACKYARD_DOMAIN for you. See docs/security/threat-model.md TS-DJ-14."
    )
