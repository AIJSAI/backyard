"""Test configuration shared across the suite."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _non_manifest_static_storage(settings: pytest.FixtureRequest) -> None:
    """Use plain static storage in tests.

    Production serves static files through WhiteNoise's manifest storage, which
    strict-checks every {% static %} reference against a collectstatic manifest
    (correct: it catches a missing asset before it ships). Tests do not run
    collectstatic, so allauth templates that reference their bundled JS would
    raise "missing manifest entry". Swapping to the non-manifest backend keeps
    the tests about behavior, not about the static pipeline, which the compose
    live probe exercises for real.
    """
    settings.STORAGES = {  # type: ignore[attr-defined]
        **settings.STORAGES,  # type: ignore[attr-defined]
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
