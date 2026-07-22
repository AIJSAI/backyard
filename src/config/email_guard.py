"""Boot-time validation of the outbound email transport (TS-PP-9).

The digest will carry capability deep links and children's photo renditions, so a
transport that would move them in cleartext is a misconfiguration we refuse to
boot with, the same hard-fail shape as the SECRET_KEY check. This lives outside
the settings module so the rule is a plain function the test suite exercises
directly; settings.py calls it once at import.
"""

from __future__ import annotations

_SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
# The Anymail Resend backend (wave 4 provider): it sends over HTTPS to the Resend
# API, so a capability byte never crosses the wire in cleartext by construction and
# the SMTP branch's encryption concern does not arise. Its own validation below
# checks the API key and the fixed sender identity are present.
_ANYMAIL_RESEND_BACKEND = "anymail.backends.resend.EmailBackend"
# The transports this guard knows how to judge. An unknown backend string refuses
# to boot rather than sailing through unvalidated (security review of #34 LOW:
# exemption-by-default would let a future backend arrive silently outside the
# guard). ADR-002's "loud arrival" for the provider is exactly this: the Anymail
# backend is listed HERE, deliberately, with its own validation.
_KNOWN_BACKENDS = frozenset(
    {
        _SMTP_BACKEND,
        _ANYMAIL_RESEND_BACKEND,
        "django.core.mail.backends.console.EmailBackend",
        "django.core.mail.backends.locmem.EmailBackend",
        "django.core.mail.backends.filebased.EmailBackend",
        "django.core.mail.backends.dummy.EmailBackend",
    }
)


def env_flag(value: str) -> bool:
    """A tolerant boolean env parse: '1', 'true', 'yes', 'on' (any case) are on.
    Strict '== \"1\"' parsing read the common EMAIL_USE_TLS=true as OFF (security
    review of #34 LOW); the guard kept that fail-closed, but the operator deserves
    the setting to mean what it says."""
    return value.strip().lower() in {"1", "true", "yes", "on"}


def validate_email_transport(
    *,
    backend: str,
    host: str,
    use_tls: bool,
    use_ssl: bool,
    default_from: str,
    resend_api_key: str = "",
) -> None:
    """Refuse an unknown transport, a real SMTP one that is unencrypted or
    under-configured, and the Anymail Resend backend without its API key.

    Non-network backends (console, locmem, file, dummy) pass: they never move a
    capability byte off the host, and console is the compose default until the
    founder picks a provider (ADR-002 keeps Anymail one settings change away).
    """
    if backend not in _KNOWN_BACKENDS:
        raise RuntimeError(
            f"Unknown EMAIL_BACKEND {backend!r}. Add it to config/email_guard.py "
            "deliberately, with its own transport validation, before booting with "
            "it. See docs/security/threat-model.md TS-PP-9."
        )
    if backend == _ANYMAIL_RESEND_BACKEND:
        missing: list[str] = []
        if not resend_api_key:
            missing.append(
                "RESEND_API_KEY is empty; the Anymail Resend backend cannot send without it"
            )
        if not default_from:
            missing.append(
                "DEFAULT_FROM_EMAIL is empty; digests need one fixed sender identity "
                "stated at onboarding (T-EMAIL-G3)"
            )
        if missing:
            raise RuntimeError(
                "Anymail Resend transport misconfigured: "
                + "; ".join(missing)
                + ". See docs/security/threat-model.md TS-PP-9."
            )
        return
    if backend != _SMTP_BACKEND:
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
