"""App config for the core app."""

from __future__ import annotations

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self) -> None:
        # Import for side effects: registering signal receivers (login cleanup,
        # and the Anymail inbound webhook -> reply-by-email pipeline).
        from . import inbound_webhook, signals  # noqa: F401
