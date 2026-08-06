"""Every setting the app reads from the environment must actually be passed in.

The class of bug this exists to stop: `settings.py` reads an environment variable,
nothing in `docker-compose.yml` passes it, and the operator's `.env` does nothing —
compose's `.env` is SUBSTITUTION-only, so a variable that is never named in a service's
`environment:` block cannot reach the container at all. That is exactly how
"bring your own SMTP" became impossible while the README promised it: all six EMAIL_*
settings were read by Django and none were passed, so setting an SMTP backend crash-looped
the web container on the boot guard's "EMAIL_HOST is empty" with nothing explaining why.

The check is text-level on purpose. It cannot import compose or run docker, and a YAML
parse would still not prove the variable is *substituted from the environment*, which is
the actual failure. Matching `NAME: ${NAME` pins both halves: named in the service, and
sourced from the operator's .env rather than hardcoded.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE = _ROOT / "docker-compose.yml"
_ENV_EXAMPLE = _ROOT / ".env.example"
_ALL_COMPOSE = sorted(_ROOT.glob("docker-compose*.yml"))

# `${NAME:?message}` — compose refuses to start unless NAME is set. Enumerated from the
# compose files rather than listed here on purpose: a hardcoded list is a guard that only
# covers what someone remembered to add to it, and this one is added to by writing YAML.
_REQUIRED_BY_COMPOSE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*):\?")

# Read by settings.py and required by any operator who brings their own SMTP server.
_SMTP_VARS = (
    "EMAIL_HOST",
    "EMAIL_PORT",
    "EMAIL_HOST_USER",
    "EMAIL_HOST_PASSWORD",
    "EMAIL_USE_TLS",
    "EMAIL_USE_SSL",
)
# Both services send mail: web sends transactional mail, the worker runs the digest.
_MAIL_SERVICES = ("web", "worker")


def _service_block(text: str, service: str) -> str:
    """The lines of one compose service, from its key to the next top-level service."""
    start = text.index(f"\n  {service}:")
    rest = text[start + 1 :]
    following = re.search(r"\n  [a-z][a-z0-9_-]*:\n", rest)
    return rest[: following.start()] if following else rest


def test_every_smtp_setting_is_passed_into_both_mail_services() -> None:
    compose = _COMPOSE.read_text()
    missing: list[str] = []
    for service in _MAIL_SERVICES:
        block = _service_block(compose, service)
        for var in _SMTP_VARS:
            # `NAME: ${NAME` — named in the service AND substituted from the environment.
            if not re.search(rf"^\s*{var}: \$\{{{var}[:-]", block, re.M):
                missing.append(f"{service}.{var}")
    assert not missing, (
        "these settings are read by src/config/settings.py but never reach the "
        "container, so an operator's .env cannot configure them: " + ", ".join(missing)
    )


def test_the_settings_module_still_reads_exactly_these_smtp_names() -> None:
    """Non-vacuity, from the other side: if a rename made the list above stale, the
    guard would pass while enforcing nothing. This fails when the names drift apart."""
    settings_src = (_ROOT / "src" / "config" / "settings.py").read_text()
    for var in _SMTP_VARS:
        assert f'os.environ.get("{var}"' in settings_src, f"{var} no longer read by settings"


def _variables_compose_refuses_to_start_without() -> set[str]:
    return {
        name for path in _ALL_COMPOSE for name in _REQUIRED_BY_COMPOSE.findall(path.read_text())
    }


def test_every_variable_compose_demands_is_settable_in_env_example() -> None:
    """The README's own install is three commands. It failed on the third.

    `cp .env.example .env` then `docker compose -f … -f docker-compose.prod.yml up` exited
    on `BACKYARD_DOMAIN: set BACKYARD_DOMAIN in .env`, because `.env.example` named three
    variables and the production overlay `:?`-requires five. A stranger following the
    README verbatim could not stand this up, and nothing noticed — the SMTP checks in this
    file guard a list somebody maintains by hand, and nobody added these two to it.

    So this asserts the relationship instead of the list: whatever compose refuses to start
    without must be a line an operator can fill in. It must be an ASSIGNMENT, not a mention
    — a variable explained in a comment and never given a `NAME=` line still leaves the
    person who copied the file with nowhere to type the value.
    """
    example = _ENV_EXAMPLE.read_text()
    missing = sorted(
        name
        for name in _variables_compose_refuses_to_start_without()
        if not re.search(rf"^{name}=", example, re.M)
    )
    assert not missing, (
        f"docker compose refuses to start without {missing}, and .env.example has no "
        "settable line for them — so `cp .env.example .env` produces a file that cannot "
        "boot the stack. Add each as `NAME=` with a comment saying what it is for."
    )


def test_the_required_variable_scan_finds_the_ones_we_know_about() -> None:
    """Denominator. If the regex or the glob breaks, the check above passes on an empty
    set and proves nothing — which is the failure mode this repo keeps finding in its own
    gates. Naming the known-required five makes a broken extractor say so."""
    found = _variables_compose_refuses_to_start_without()
    expected = {
        "POSTGRES_PASSWORD",
        "POSTGRES_MIGRATOR_PASSWORD",
        "POSTGRES_APP_PASSWORD",
        "BACKYARD_DOMAIN",
        "ACME_EMAIL",
    }
    assert expected <= found, (
        f"the `${{NAME:?}}` scan across {[p.name for p in _ALL_COMPOSE]} missed "
        f"{sorted(expected - found)} — the extractor is broken, so the check above is vacuous"
    )


def test_bring_your_own_smtp_is_documented_for_the_operator() -> None:
    """The README promises it; .env.example is where an operator looks for how."""
    example = _ENV_EXAMPLE.read_text()
    assert "EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend" in example
    for var in _SMTP_VARS:
        assert var in example, f"{var} undocumented in .env.example"
    # The honest limitation the README commits to being honest about.
    assert "inbound" in example.lower()
