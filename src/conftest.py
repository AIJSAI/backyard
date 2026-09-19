"""Test configuration shared across the suite."""

from __future__ import annotations

from pathlib import Path

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


@pytest.fixture(autouse=True)
def _media_root_tmp(settings: pytest.FixtureRequest, tmp_path: Path) -> None:
    """Point MEDIA_ROOT at a per-test temp directory so uploaded-media tests never
    write into the repo or the /data volume, and each test starts clean."""
    settings.MEDIA_ROOT = str(tmp_path / "media")  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _setup_handover_tmp(settings: pytest.FixtureRequest, tmp_path: Path) -> None:
    """Same reason again, for the first-run hand-over file: a test run must never write
    (or delete) anything under /data, and this one holds a live credential."""
    settings.SETUP_HANDOVER_FILE = str(tmp_path / "first-run-secret")  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _backup_root_tmp(settings: pytest.FixtureRequest, tmp_path: Path) -> None:
    """Same reason, for the scheduled backup's archives: a test run must never write a
    copy of anything into /data, and retention DELETES files in this directory."""
    settings.BACKUP_ROOT = str(tmp_path / "backups")  # type: ignore[attr-defined]
