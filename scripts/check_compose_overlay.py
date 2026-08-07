#!/usr/bin/env python3
"""CI boots the base compose stack. The README tells a stranger to boot the overlay.

`ci.yml`'s live probe runs `docker compose up -d --build` — the base file alone. The install
command in README.md is:

    docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

So the stack CI proves and the stack a self-hoster runs are not the same stack. That is not
fixable by pointing CI at the overlay: it publishes 0.0.0.0:80 and :443 and asks Let's
Encrypt for a certificate for a real domain, none of which a runner can do.

What IS fixable is the size of the untested delta. Measured when this was written, it is 22
lines and every one of them is domain, TLS, ports or the prod Caddyfile:

    caddy   ports 127.0.0.1:8000 -> 0.0.0.0:80 + :443
    caddy   volumes Caddyfile -> Caddyfile.prod
    caddy   environment BACKYARD_DOMAIN, ACME_EMAIL
    web     environment DJANGO_DEBUG, DJANGO_ALLOWED_HOSTS, BACKYARD_BASE_URL
    worker  environment DJANGO_ALLOWED_HOSTS, BACKYARD_BASE_URL

The environment values are covered by a different mechanism: `ci.yml`'s deploy-check step
runs `manage.py check --deploy --fail-level WARNING` with `DJANGO_DEBUG=0`, an https
`BACKYARD_BASE_URL` and a real `DJANGO_ALLOWED_HOSTS` — the same values this overlay sets —
so the posture they produce is verified even though the overlay itself never boots.

That leaves ports, the Caddyfile and the ACME variables genuinely proven only by the live
instance. Acceptable, and stated rather than implied.

This guard keeps it true. If the overlay grows a new service, a `command:`, a different
image, or an environment variable outside the verified set, that addition would ship having
been booted nowhere — and nothing would have said so. Adding it here is the decision point:
either extend CI to cover it, or record why it cannot be.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


class _ComposeLoader(yaml.SafeLoader):
    """Compose's `!override` / `!reset` tags are not standard YAML.

    `safe_load` refuses an unknown tag outright, which would make this guard fail for a
    reason that has nothing to do with what it checks. The tags only tell Compose how to
    MERGE a value; the value itself is what matters here, so they are unwrapped.
    """


def _keep_the_value(loader: yaml.Loader, node: yaml.Node) -> object:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


for _tag in ("!override", "!reset"):
    _ComposeLoader.add_constructor(_tag, _keep_the_value)


ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "docker-compose.yml"
OVERLAY = ROOT / "docker-compose.prod.yml"

# Service-level keys the overlay may set. Each is either exercised by another CI step or is
# the part a runner genuinely cannot do.
ALLOWED_KEYS = {"environment", "ports", "volumes"}

# Environment variables the overlay may set, and why each is covered.
ALLOWED_ENV = {
    "DJANGO_DEBUG": "ci.yml deploy-check runs with DJANGO_DEBUG=0",
    "DJANGO_ALLOWED_HOSTS": "ci.yml deploy-check runs with a real ALLOWED_HOSTS",
    "BACKYARD_BASE_URL": "ci.yml deploy-check runs with an https base URL",
    "BACKYARD_DOMAIN": "Caddy's TLS host; no runner can provision a cert for it",
    "ACME_EMAIL": "the ACME account address; only meaningful against a real issuer",
}


def check() -> list[str]:
    errors: list[str] = []
    if not OVERLAY.is_file() or not BASE.is_file():
        return [f"missing compose file: {BASE.name} or {OVERLAY.name}"]

    # S506 is about `yaml.load` with a loader that can instantiate arbitrary objects.
    # `_ComposeLoader` subclasses SafeLoader and adds two constructors that return the
    # tagged value unchanged, so it constructs nothing SafeLoader would not — and the
    # input is two files in this repository, not user data.
    base = yaml.load(BASE.read_text(), Loader=_ComposeLoader) or {}  # noqa: S506
    overlay = yaml.load(OVERLAY.read_text(), Loader=_ComposeLoader) or {}  # noqa: S506
    base_services = set(base.get("services") or {})
    overlay_services = overlay.get("services") or {}

    if not base_services:
        return ["no services parsed from docker-compose.yml; this check is blind"]
    if not overlay_services:
        return ["no services parsed from docker-compose.prod.yml; this check is blind"]

    errors += problems_with(overlay_services, base_services)
    return errors


def problems_with(services: dict, base_services: set[str]) -> list[str]:
    """The actual rule. ONE implementation, called by `check()` and by `selftest()`.

    The first draft of this file had `selftest` re-implement the loop against a fixture,
    which is a second reader of one rule — they drift, and the copy in the self-test drifts
    toward passing. `check_stories.py` has the same note for the same reason.
    """
    errors: list[str] = []
    for name, service in services.items():
        if name not in base_services:
            errors.append(
                f"the prod overlay adds a service `{name}` that the base stack does not have. "
                "CI boots the base stack, so this service would ship having been started "
                "nowhere. Add it to the base file, or extend the CI live probe."
            )
            continue
        for key in service or {}:
            if key not in ALLOWED_KEYS:
                errors.append(
                    f"the prod overlay sets `{name}.{key}`, which is outside the set CI can "
                    f"account for ({sorted(ALLOWED_KEYS)}). CI boots the base stack, so this "
                    "override is exercised by nothing. Either cover it in CI or add it here "
                    "with the reason it cannot be covered."
                )
        for env_key in (service or {}).get("environment") or {}:
            if env_key not in ALLOWED_ENV:
                errors.append(
                    f"the prod overlay sets `{name}.environment.{env_key}`, which no CI step "
                    "exercises. The deploy-check step covers DJANGO_DEBUG, "
                    "DJANGO_ALLOWED_HOSTS and BACKYARD_BASE_URL; anything else changes "
                    "production behaviour with nothing watching."
                )
    return errors


def selftest() -> list[str]:
    """The guard must reject a known-bad overlay, or it is decoration.

    Run against `problems_with` — the same function `check()` uses — so a rule that stops
    firing stops firing here too.
    """
    errors: list[str] = []
    bad = {
        "web": {"command": "python -m http.server"},  # behaviour CI never boots
        "worker": {"environment": {"BACKYARD_FEATURE_X": "1"}},  # env nothing exercises
        "sidecar": {"image": "nginx"},  # a whole service
    }
    found = problems_with(bad, {"web", "worker", "caddy"})
    for needle, what in (
        ("`sidecar`", "a new service"),
        ("`web.command`", "a command override"),
        ("BACKYARD_FEATURE_X", "an unaccounted environment variable"),
    ):
        if not any(needle in err for err in found):
            errors.append(f"selftest: {what} passed the overlay guard (vacuous gate)")
    if problems_with({"web": {"environment": {"DJANGO_DEBUG": "0"}}}, {"web"}):
        errors.append("selftest: the guard rejected an overlay that is entirely accounted for")
    return errors


def main() -> int:
    errors = selftest() + check()
    for err in errors:
        print(f"GATE FAIL: {err}")
    print(f"compose overlay: {'FAIL' if errors else 'PASS'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
