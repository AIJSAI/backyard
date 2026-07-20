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


def test_login_has_per_account_lockout_not_just_per_ip() -> None:
    """HIGH-1 regression: login_failed must carry a per-account (/key) component, not
    only /ip. A scopeless or ip-only rate lets an attacker who knows a username
    brute-force from rotating IPs with no account lockout (T-CRED-1)."""
    login_failed = settings.ACCOUNT_RATE_LIMITS["login_failed"]
    components = [c.strip() for c in login_failed.split(",")]
    assert any(c.endswith("/key") for c in components), (
        f"login_failed has no /key (per-account) scope: {login_failed}"
    )
    assert any(c.endswith("/ip") for c in components), "login_failed must also cap per IP"
    # reset_password likewise caps per target email, not just per IP (MEDIUM-2).
    reset = settings.ACCOUNT_RATE_LIMITS["reset_password"]
    assert any(c.strip().endswith("/key") for c in reset.split(","))
    assert settings.ALLAUTH_TRUSTED_PROXY_COUNT == 1  # exactly one proxy: the bundled Caddy


def test_rate_limits_parse_and_key_scope_is_effective() -> None:
    """Guard against a rate string that looks right but allauth parses to ip-only:
    parse the config through allauth itself and assert a key-scoped rule survives."""
    from allauth.core.internal.ratelimit import parse_rates

    rates = parse_rates(settings.ACCOUNT_RATE_LIMITS["login_failed"])
    assert any(getattr(r, "per", None) == "key" for r in rates), (
        "allauth parsed login_failed to no per=key rule (the HIGH-1 fail-open)"
    )


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
