#!/bin/sh
# Container entrypoint. Generates and persists the app secret on first boot (TM-8),
# applies migrations, collects static files, prints the first-run setup secret if
# needed, then hands off to gunicorn.
set -eu

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

python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py ensure_setup

# No --access-logfile: gunicorn's access log records the full request line, which would write
# elder token URLs verbatim into the container logs the moment the token surface lands (threat
# model TS-EDGE-LOG / TM-5). Caddy is the edge and does access logging under its redaction rule;
# gunicorn keeps only the error log.
exec gunicorn config.wsgi:application \
  --chdir /app \
  --bind 0.0.0.0:8000 \
  --workers 3 \
  --error-logfile -
