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

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
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

LOGIN_URL = "/setup/"

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
