"""The install guide must describe the software that actually exists.

The audit's finding was not "the docs are thin" — it was that the README stated the
OPPOSITE of reality ("There is nothing to install yet") for a product that had been
deployed and serving over TLS for days, while promising "bring your own SMTP" that was
impossible. Prose drifts silently, so the load-bearing claims are pinned here against the
code they describe.

These are deliberately about FACTS a reader would act on — env var names, command names,
the honest limitations — not about wording.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_GUIDE = _ROOT / "docs" / "runbooks" / "self-host.md"
_README = _ROOT / "README.md"


def test_the_install_guide_exists_and_the_readme_points_at_it() -> None:
    assert _GUIDE.is_file(), "the README promises an install guide"
    readme = _README.read_text()
    assert "docs/runbooks/self-host.md" in readme
    assert "nothing to install" not in readme.lower(), (
        "the README said there was nothing to install while the instance was live"
    )


@pytest.mark.parametrize(
    "command",
    ["backup_instance", "restore_instance", "ensure_setup"],
)
def test_every_command_the_guide_names_actually_exists(command: str) -> None:
    """A guide that tells an operator to run a command that was renamed is worse than no
    guide: they find out at the moment they need a restore."""
    guide = _GUIDE.read_text()
    if command not in guide:
        pytest.skip(f"{command} is not named in the guide")
    assert (_ROOT / "src" / "core" / "management" / "commands" / f"{command}.py").is_file(), (
        f"the guide tells the operator to run `{command}`, which does not exist"
    )


def test_every_env_var_the_guide_names_is_one_the_app_reads() -> None:
    """The exact defect class the audit found: `.env` documentation for variables nothing
    consumes, or that compose never passes into the container."""
    import re

    guide = _GUIDE.read_text()
    settings = (_ROOT / "src" / "config" / "settings.py").read_text()
    compose = (_ROOT / "docker-compose.yml").read_text()
    prod = (_ROOT / "docker-compose.prod.yml").read_text()
    caddyfile = (_ROOT / "caddy" / "Caddyfile.prod").read_text()
    known = settings + compose + prod + caddyfile

    # Only the ones presented as configuration the reader should set.
    documented = {
        name
        for name in re.findall(r"^([A-Z][A-Z0-9_]{4,})=", guide, re.M)
        if not name.startswith("PATH")
    }
    assert documented, "the guide should document the configuration"
    unknown = sorted(name for name in documented if name not in known)
    assert not unknown, f"the guide documents variables nothing reads: {unknown}"


def test_the_guide_states_the_limitations_a_self_hoster_would_otherwise_hit() -> None:
    """Each of these is a real, current limitation. If one is ever fixed, this test should
    be updated deliberately — which is the point: the docs change WITH the code."""
    guide = _GUIDE.read_text().lower()
    for claim, why in (
        ("resend-only", "inbound reply-by-email works with exactly one provider"),
        ("no web push", "the notification opt-in sends email, not a push"),
        ("no key escrow", "a lost backup passphrase is unrecoverable"),
        ("silently", "an unregistered inbound webhook fails with no bounce and no error"),
    ):
        assert claim in guide, f"the guide must say: {why}"


def test_the_guide_does_not_teach_putting_the_passphrase_in_shell_history() -> None:
    """The runbook used to demonstrate `VAR=secret docker compose ...`, which contradicts
    the command's own docstring and puts the backup key in the operator's history file."""
    guide = _GUIDE.read_text()
    assert "BACKYARD_BACKUP_PASSPHRASE=... docker" not in guide
    assert "--passphrase-file" in guide
