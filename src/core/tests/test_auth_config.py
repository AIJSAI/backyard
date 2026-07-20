"""Auth scaffold tests: prove the security-relevant allauth configuration is real.

These are not testing allauth's own behavior; they pin the settings the threat
model requires so a later change that weakens them fails the build (S-101,
TS-DJ-13, TS-EDGE-IP, T-CRED-1).
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test import Client

pytestmark = pytest.mark.django_db


def test_login_surface_is_mounted() -> None:
    response = Client().get("/accounts/login/")
    assert response.status_code == 200


def test_signup_is_closed_account_creation_is_invite_only() -> None:
    """Account creation is invite-only (S-101): allauth's open signup is closed by
    the adapter, so a signup POST creates no user. The custom invite view is the
    only path that mints a member."""
    from django.contrib.auth import get_user_model

    from core.adapters import AccountAdapter

    assert AccountAdapter().is_open_for_signup(None) is False

    user_model = get_user_model()
    before = user_model.objects.count()
    Client().post(
        "/accounts/signup/",
        {
            "username": "stranger",
            "email": "s@example.com",
            "password1": "xK9!mnpq2ffz",
            "password2": "xK9!mnpq2ffz",
        },
    )
    assert user_model.objects.count() == before


def test_rate_limit_substrate_is_shared_not_per_process() -> None:
    """TS-DJ-13: the cache backing allauth's rate limits is Postgres DatabaseCache,
    not per-process LocMemCache, so the limit holds across gunicorn workers and
    across restarts. A LocMem default would silently make the limit 3x looser."""
    assert settings.CACHES["default"]["BACKEND"] == ("django.core.cache.backends.db.DatabaseCache")
    cache.set("probe", "value", 30)
    assert cache.get("probe") == "value"
    # The row lives in a real table both workers query (the shared-substrate proof).
    with connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM backyard_cache")
        assert cur.fetchone()[0] >= 1


def test_credential_endpoints_are_rate_limited() -> None:
    limits = settings.ACCOUNT_RATE_LIMITS
    assert limits and limits.get("login_failed"), "per-account login backoff must be set"
    assert settings.ALLAUTH_TRUSTED_PROXY_COUNT == 1  # exactly one proxy: the bundled Caddy


def test_enumeration_is_prevented() -> None:
    """Login and reset must not reveal whether an account exists (family structure
    leak, T-CRED-1)."""
    assert settings.ACCOUNT_PREVENT_ENUMERATION is True


def test_passkey_login_on_signup_off() -> None:
    """Passkey login is primary; passkey signup stays off because it forces email
    verification that invite-token signup cannot meet, which is why the invite
    flow is a custom view (ADR-002, S-101)."""
    assert settings.MFA_PASSKEY_LOGIN_ENABLED is True
    assert settings.MFA_PASSKEY_SIGNUP_ENABLED is False
    assert "webauthn" in settings.MFA_SUPPORTED_TYPES
