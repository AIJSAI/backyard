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


def _commands_the_guide_names() -> set[str]:
    """Every `manage.py <command>` the guide actually tells an operator to run."""
    import re

    return set(re.findall(r"manage\.py\s+([a-z_][a-z0-9_]*)", _GUIDE.read_text()))


def test_every_command_the_guide_names_actually_exists() -> None:
    """A guide that tells an operator to run a command that was renamed is worse than no
    guide: they find out at the moment they need a restore.

    Read OUT OF the guide, not checked against a hardcoded list. The previous version walked
    `["backup_instance", "restore_instance", "ensure_setup"]` and did
    `pytest.skip(f"{command} is not named in the guide")` — an inverted enumeration, where
    DELETING a command from the guide made the check pass more easily. Measured before this
    change: 2 of the 3 skipped, so the guard was one-third live and reported green.

    (`restore_instance` is documented in backup-restore.md and `ensure_setup` runs from the
    container entrypoint, so their absence here was correct — the LIST was wrong, not the
    guide. Which is exactly why the list should not exist.)
    """
    named = _commands_the_guide_names()
    ours = {p.stem for p in (_ROOT / "src" / "core" / "management" / "commands").glob("*.py")}
    ours.discard("__init__")
    django_builtins = {"shell", "migrate", "check", "collectstatic", "createsuperuser"}

    missing = sorted(name for name in named - django_builtins if name not in ours)
    assert not missing, (
        f"docs/runbooks/self-host.md tells the operator to run {missing}, which do not exist "
        "in src/core/management/commands/. They find that out at the moment they need it."
    )


def test_the_guide_still_names_commands_at_all() -> None:
    """Denominator. The check above is a set difference, so an extractor that returns nothing
    passes it trivially — which is the failure mode the skip-based version had in a different
    costume."""
    named = _commands_the_guide_names()
    assert named, (
        "no `manage.py <command>` found in the guide; the extractor is broken, so the check "
        "above compares an empty set and proves nothing"
    )
    assert "backup_instance" in named, (
        "the self-host guide no longer tells an operator how to back up. That is the one "
        "command a self-hoster cannot discover on their own and cannot afford to miss."
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
