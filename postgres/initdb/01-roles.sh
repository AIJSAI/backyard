#!/bin/sh
# Creates the two-role split from ADR-004 (threat model TS-PG-1) at first boot:
#
#   backyard_migrator  owns the database and schema; the only role that runs DDL
#                      (the container entrypoint migrates as it, then drops its
#                      credentials from the runtime environment).
#   backyard_app       what web and worker connect as: LOGIN only, no SUPERUSER,
#                      no BYPASSRLS, no CREATEDB, no CREATEROLE, DML granted via
#                      default privileges on migrator-created objects.
#
# The bootstrap superuser (POSTGRES_USER) remains for initdb, healthchecks, and
# version-matched pg_dump backups (TS-PG-6); the application never connects as it.
# Runs only on a fresh volume, like all docker-entrypoint-initdb.d scripts; an
# existing volume adopts the split via the documented dump-and-restore runbook.
set -eu

: "${POSTGRES_MIGRATOR_PASSWORD:?set POSTGRES_MIGRATOR_PASSWORD in .env, see .env.example}"
: "${POSTGRES_APP_PASSWORD:?set POSTGRES_APP_PASSWORD in .env, see .env.example}"

psql -v ON_ERROR_STOP=1 \
  -v migrator_pw="$POSTGRES_MIGRATOR_PASSWORD" \
  -v app_pw="$POSTGRES_APP_PASSWORD" \
  -v db="$POSTGRES_DB" \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE backyard_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
  PASSWORD :'migrator_pw';
CREATE ROLE backyard_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
  PASSWORD :'app_pw';

-- The migrator owns what migrations create; ownership is what grants it DDL.
ALTER DATABASE :"db" OWNER TO backyard_migrator;
ALTER SCHEMA public OWNER TO backyard_migrator;
GRANT USAGE ON SCHEMA public TO backyard_app;

-- DML for the app role on every table the migrator will create. Scoped
-- FOR ROLE backyard_migrator: without that clause the grant would attach to the
-- bootstrap superuser's objects and be vacuous for migration-created tables.
ALTER DEFAULT PRIVILEGES FOR ROLE backyard_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO backyard_app;
ALTER DEFAULT PRIVILEGES FOR ROLE backyard_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO backyard_app;
-- Procrastinate's schema is PL/pgSQL functions the worker (backyard_app) must
-- EXECUTE (ADR-002 job queue). Scoped FOR ROLE backyard_migrator like the table
-- grant above, so only the functions migrations create are reachable, and the
-- app role gains EXECUTE on nothing the bootstrap superuser owns.
ALTER DEFAULT PRIVILEGES FOR ROLE backyard_migrator IN SCHEMA public
  GRANT EXECUTE ON ROUTINES TO backyard_app;
SQL

echo "backyard role split created: backyard_migrator (DDL) / backyard_app (DML only)."
