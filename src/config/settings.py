"""Backyard settings, hello-world scaffold.

Security posture here follows the Phase 1 threat model (docs/security/threat-model.md,
TM-8): no default secrets, hard-fail on a placeholder SECRET_KEY, and HTTPS assumed in
production. This is the walking skeleton for S-801's first-run wizard, not the full app.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# SECRET_KEY: no default, and the app refuses to boot on an empty or placeholder value.
# A real value is generated at first boot by the container entrypoint (TM-8).
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
_PLACEHOLDERS = {"", "changeme", "change-me", "placeholder", "secret", "django-insecure"}
_normalized = SECRET_KEY.strip().lower()
if (
    _normalized in _PLACEHOLDERS
    or _normalized.startswith("django-insecure")
    or len(SECRET_KEY) < 32
):
    raise RuntimeError(
        "DJANGO_SECRET_KEY is empty, a placeholder, or too short (need >= 32 chars). "
        "Generate a real secret before boot; the container entrypoint does this "
        "automatically. See docs/security/threat-model.md TM-8."
    )

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

# ALLOWED_HOSTS is required in production; localhost is the only default, for the repro.
_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
ALLOWED_HOSTS = [h for h in _hosts.split(",") if h]

# The base URL the instance is served from. Token links refuse to mint against non-HTTPS in
# production (threat model TM-8 / T-EDGE-1); enforced once the token service lands.
BASE_URL = os.environ.get("BACKYARD_BASE_URL", "http://localhost:8000").rstrip("/")

# DEBUG serves tracebacks with settings to anyone; it must never be on for a real deployment.
# Extend the refuse-to-boot posture to it (threat model TS-DJ-10): a public HTTPS base URL with
# DEBUG on is a misconfiguration we hard-fail rather than serve.
if DEBUG and BASE_URL.lower().startswith("https://"):
    raise RuntimeError(
        "DJANGO_DEBUG is on while BASE_URL is https. DEBUG must be off in production; it leaks "
        "settings and tracebacks. See docs/security/threat-model.md TS-DJ-10."
    )

# The symmetric guard (security review MEDIUM-3): the whole HTTPS posture (secure cookies,
# HSTS, SSL redirect, the WebAuthn secure-origin check) keys off BASE_URL's scheme. An operator
# who fronts a real domain with TLS but forgets BACKYARD_BASE_URL (it defaults to http localhost)
# would silently get all of that OFF. So a non-local http base URL in production is a hard-fail.
# The local plain-HTTP repro (http://localhost) is exempt: it is the documented clean-machine path.
_is_local = any(host in BASE_URL.lower() for host in ("localhost", "127.0.0.1"))
if not DEBUG and not BASE_URL.lower().startswith("https://") and not _is_local:
    raise RuntimeError(
        "BACKYARD_BASE_URL is a non-local http URL. In production it must be https, or secure "
        "cookies, HSTS, and the SSL redirect stay off. Set BACKYARD_BASE_URL to your https URL. "
        "See docs/security/threat-model.md TS-DJ-10 / TS-EDGE-1."
    )

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",  # required by allauth's default MFA templates
    "allauth",
    "allauth.account",
    "allauth.mfa",  # TOTP + WebAuthn passkeys (ADR-002 S-101)
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",  # required by allauth
]

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.contrib.messages.context_processors.messages",
                "django.contrib.auth.context_processors.auth",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Postgres only (ADR-002). Values come from the environment; the compose file wires them.
# ATOMIC_REQUESTS wraps each request in a transaction so a multi-step write that crashes
# partway leaves no half-applied state; the TM-1 revocation handler depends on removal being
# one atomic act (threat model TS-DJ-2). Jobs and management commands still wrap explicitly.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "backyard"),
        "USER": os.environ.get("POSTGRES_USER", "backyard"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "ATOMIC_REQUESTS": True,
    }
}

# Server-side, individually revocable sessions are a hard requirement: removal and token
# regeneration must be able to kill a live session on its next request (threat model TS-DJ-1,
# T-SESS-1, S-702). The database backend is Django's default, but it is pinned here so a later
# switch to signed-cookie sessions (which cannot be revoked) is a deliberate, visible change.
SESSION_ENGINE = "django.contrib.sessions.backends.db"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Authentication (django-allauth, S-101) ---------------------------------
# Rate limits and lockouts ride the Django cache framework. The default is
# per-process LocMemCache, which on three gunicorn workers means a limit that is
# 3x looser and resets on every restart, and TS-EDGE-IP's per-account backoff
# would be inconsistent across workers (threat model TS-DJ-13). Use a Postgres
# DatabaseCache: shared across workers, survives restarts, and adds no container.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "backyard_cache",
    }
}

# allauth cannot reliably determine the client IP behind a proxy, and since its
# 65.14.2 security release it distrusts X-Forwarded-For by default (threat model
# TS-EDGE-IP). Exactly one proxy sits in front: the bundled Caddy, which
# overwrites client-sent forwarded headers and is the only peer that can reach
# web (the TS-CO-4 network split). A CDN or second proxy must revisit this.
ACCOUNT_ADAPTER = "core.adapters.AccountAdapter"  # signup is invite-only (S-101)
ACCOUNT_LOGIN_METHODS = {"username", "email"}
ACCOUNT_EMAIL_VERIFICATION = "optional"  # invite-token members may have no email
ACCOUNT_PREVENT_ENUMERATION = True  # login/reset never reveal whether an account exists
ACCOUNT_RATE_LIMITS = {
    # Per-IP AND per-account backoff on the credential endpoints (T-CRED-1, T-EDGE-2).
    # The `/key` scope is the per-account half and is load-bearing: allauth defaults a
    # scopeless rate to per-IP, so an attacker who knows a username could brute-force
    # from rotating IPs with no account lockout (security review HIGH-1). Every
    # credential limit here carries an explicit `/ip` and, where an account or target
    # exists, a `/key` component.
    "login_failed": "5/5m/ip,10/1h/ip,5/15m/key",
    "login": "30/5m/ip",
    "signup": "20/1h/ip",
    "reset_password": "20/1h/ip,5/1h/key",
}
ALLAUTH_TRUSTED_PROXY_COUNT = 1

# Passkey-primary login with password fallback (ADR-002). WebAuthn passkeys are
# the preferred method; a password remains a fallback. Passkey SIGNUP stays off:
# it forces email verification, which invite-token signup (email optional) cannot
# meet, so the invite flow is a custom view (S-101) that enrolls WebAuthn after.
MFA_SUPPORTED_TYPES = ["webauthn", "totp", "recovery_codes"]
MFA_PASSKEY_LOGIN_ENABLED = True
MFA_PASSKEY_SIGNUP_ENABLED = False
# Local HTTP repro only: fido2 <= 1.1.3 rejects localhost as a secure origin.
# Never true in production (keyed off the same HTTPS signal as the cookie flags).
MFA_WEBAUTHN_ALLOW_INSECURE_ORIGIN = not BASE_URL.lower().startswith("https://")

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR.parent / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Where login_required sends an anonymous visitor: the allauth login page (the
# member-management surface is the first login-gated view).
LOGIN_URL = "account_login"

# Security headers. Secure cookies and HSTS switch on when the instance is served over
# HTTPS, keyed off BASE_URL rather than DEBUG, so the local HTTP clean-machine repro still
# accepts the setup form while a real HTTPS deployment gets the full treatment (TM-8).
_HTTPS = BASE_URL.lower().startswith("https://")
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
CSRF_TRUSTED_ORIGINS = [BASE_URL]
if _HTTPS:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # The threat model treats the instance domain as a multi-year family asset (T-OP-G4), so
    # committing to HTTPS-only in browsers is consistent and strengthens elder-token protection.
    # The operator still submits the domain to the preload list; this only emits the directive.
    SECURE_HSTS_PRELOAD = True
    # Safe only because the bundled Caddy sets X-Forwarded-Proto on every hop and the
    # web container publishes no host port, so a client cannot reach Django directly to
    # spoof it. A future compose that exposes web's port must revisit this (TM-8).
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
