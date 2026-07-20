"""Create the Postgres-backed cache table for allauth rate limits (TS-DJ-13).

Runs inside the migrate step, which the entrypoint executes as backyard_migrator,
so the table is owned by the migrator and the app role inherits DML through the
ALTER DEFAULT PRIVILEGES grant (ADR-004 role split). A shared cache is what makes
the rate limit real across the three gunicorn workers and across restarts.
"""

from __future__ import annotations

from django.core.management import call_command
from django.db import migrations

CACHE_TABLE = "backyard_cache"


def create_cache_table(apps: object, schema_editor: object) -> None:
    call_command("createcachetable", CACHE_TABLE)


def drop_cache_table(apps: object, schema_editor: object) -> None:
    schema_editor.execute(f'DROP TABLE IF EXISTS "{CACHE_TABLE}"')  # type: ignore[attr-defined]


class Migration(migrations.Migration):
    # createcachetable manages its own DDL/transaction; keep this migration
    # non-atomic so it does not nest a transaction around that.
    atomic = False

    dependencies = [("core", "0003_invites")]

    operations = [migrations.RunPython(create_cache_table, drop_cache_table)]
