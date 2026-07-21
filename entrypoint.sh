#!/bin/sh
# Role-aware container entrypoint (TS-CO-3). The web role (gunicorn CMD) owns
# secret generation, the pre-flight backup, migrations, collectstatic, and the
# first-run setup secret; any other command (the worker's `procrastinate worker`,
# a one-off manage.py) execs directly and never races the web boot.
set -eu

case "${1:-}" in
  gunicorn) ROLE=web ;;
  *) ROLE=other ;;
esac

if [ "$ROLE" = web ]; then
  # Secrets written here are private to the process user only.
  umask 077

  SECRET_FILE=/data/secret_key
  # Regenerate if missing OR empty (a crash mid-write must not brick the instance).
  if [ ! -s "$SECRET_FILE" ]; then
    python -c "import secrets; print(secrets.token_urlsafe(64), end='')" > "$SECRET_FILE.tmp"
    mv "$SECRET_FILE.tmp" "$SECRET_FILE"
    echo "Generated a new DJANGO_SECRET_KEY, persisted at $SECRET_FILE."
  fi
  DJANGO_SECRET_KEY="$(cat "$SECRET_FILE")"
  export DJANGO_SECRET_KEY

  # Pre-flight backup before any migration (TS-CO-2, T-UPGRADE-1, S-803): dump as
  # the migrator (it owns every table) with the version-matched client, keep the
  # last three, and refuse to migrate if the dump fails. The explicit override
  # exists for the operator who accepts the risk, loudly.
  MIGRATOR_PW="${POSTGRES_MIGRATOR_PASSWORD:?POSTGRES_MIGRATOR_PASSWORD not set}"
  if [ "${BACKYARD_SKIP_PREFLIGHT_BACKUP:-0}" = "1" ]; then
    echo "WARNING: BACKYARD_SKIP_PREFLIGHT_BACKUP=1, migrating with NO pre-flight backup."
  else
    mkdir -p /data/backups
    STAMP="$(date +%Y%m%d%H%M%S)"
    PGPASSWORD="$MIGRATOR_PW" pg_dump \
      -h "${POSTGRES_HOST:-postgres}" -p "${POSTGRES_PORT:-5432}" \
      -U backyard_migrator -Fc \
      -f "/data/backups/preflight-$STAMP.dump" "${POSTGRES_DB:-backyard}" \
      || { echo "Pre-flight backup FAILED; refusing to migrate (set BACKYARD_SKIP_PREFLIGHT_BACKUP=1 to override)."; exit 1; }
    # Keep the last three pre-flight dumps; older ones rotate out.
    ls -1t /data/backups/preflight-*.dump 2>/dev/null | tail -n +4 | while read -r old; do
      rm -f "$old"
    done
    echo "Pre-flight backup written: preflight-$STAMP.dump"
  fi

  # Migrations run as backyard_migrator, the only role with DDL (ADR-004, TS-PG-1).
  # The env prefix scopes the migrator credentials to this one command; the unset
  # after it removes them from the process environment entirely, so the gunicorn
  # process that exec's below (and anything that compromises it) holds only the
  # backyard_app role.
  POSTGRES_USER=backyard_migrator POSTGRES_PASSWORD="$MIGRATOR_PW" \
    python manage.py migrate --noinput
  unset POSTGRES_MIGRATOR_PASSWORD MIGRATOR_PW

  # Everything from here runs as the unprivileged app role from the container env.
  python manage.py collectstatic --noinput
  python manage.py ensure_setup
else
  # Non-web roles still need the persisted secret to boot Django, but never the
  # migrator credentials; drop them if compose passed them along.
  if [ -s /data/secret_key ]; then
    DJANGO_SECRET_KEY="$(cat /data/secret_key)"
    export DJANGO_SECRET_KEY
  fi
  unset POSTGRES_MIGRATOR_PASSWORD || true
fi

# No --access-logfile on the web role: gunicorn's access log records the full
# request line, which would write elder token URLs verbatim into the container
# logs the moment the token surface lands (threat model TS-EDGE-LOG / TM-5).
# Caddy access logging is OFF too (no log directive in the Caddyfile), and must
# stay off unless token paths are redacted first; django.request 404s are
# redacted in-app (config/log_redaction.py).
exec "$@"
