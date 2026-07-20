"""Core models for the Backyard hello-world scaffold."""

from __future__ import annotations

from django.db import models


class SetupToken(models.Model):
    """One-time secret gating the first-run wizard (threat model TM-8).

    Stored only as a password-style hash. Created at first boot when no admin
    exists, printed to the server console, and deleted the moment the first
    admin is created. The wizard's real gate is "zero admins exist", so this
    row is a convenience, not the security boundary.
    """

    token_hash = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "setup token"

    def __str__(self) -> str:
        return f"SetupToken(created_at={self.created_at:%Y-%m-%d %H:%M})"
