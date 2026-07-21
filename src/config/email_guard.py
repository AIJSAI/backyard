"""Boot-time validation of the outbound email transport (TS-PP-9).

The digest will carry capability deep links and children's photo renditions, so a
transport that would move them in cleartext is a misconfiguration we refuse to
boot with, the same hard-fail shape as the SECRET_KEY check. This lives outside
the settings module so the rule is a plain function the test suite exercises
directly; settings.py calls it once at import.
"""

from __future__ import annotations


def validate_email_transport(
    *,
    backend: str,
    host: str,
    use_tls: bool,
    use_ssl: bool,
    default_from: str,
) -> None:
    """Refuse a real SMTP transport that is unencrypted or under-configured.

    Non-network backends (console, locmem, file) are exempt: they never move a
    capability byte off the host, and console is the compose default until the
    founder picks a provider (ADR-002 keeps Anymail one settings change away).
    """
    if backend != "django.core.mail.backends.smtp.EmailBackend":
        return
    problems: list[str] = []
    if not host:
        problems.append("EMAIL_HOST is empty")
    if not default_from:
        problems.append(
            "DEFAULT_FROM_EMAIL is empty; digests need one fixed sender identity "
            "stated at onboarding (T-EMAIL-G3)"
        )
    if use_tls and use_ssl:
        problems.append("EMAIL_USE_TLS and EMAIL_USE_SSL are both on; pick exactly one")
    if not use_tls and not use_ssl:
        problems.append(
            "neither EMAIL_USE_TLS nor EMAIL_USE_SSL is on; capability-bearing "
            "mail must never travel in cleartext (TS-PP-9)"
        )
    if problems:
        raise RuntimeError(
            "Outbound email transport misconfigured: "
            + "; ".join(problems)
            + ". See docs/security/threat-model.md TS-PP-9."
        )
