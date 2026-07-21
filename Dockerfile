# Backyard web image. Single Python image; the same image runs web and (later) the worker.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app/src \
    DJANGO_SETTINGS_MODULE=config.settings \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app

# Two persistent runtime binaries:
#   - postgresql-client-18: version-matched pg_dump for the pre-flight migration backup
#     (TS-CO-2, TS-PG-6); Debian's default client refuses servers newer than its own
#     major, so install client 18 from PGDG, key-verified.
#   - ffmpeg: the video transcode surface on the worker (ADR-002, S-402). It runs only
#     on hostile bytes behind the core/transcoding hardening (TS-PP-1/2); on the target
#     Intel box QSV hardware encode is enabled via BACKYARD_FFMPEG_VCODEC + /dev/dri.
# Kept in one layer; only curl/gnupg are purged, ffmpeg and the pg client persist.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
       | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] http://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-18 ffmpeg \
    && apt-get purge -y curl gnupg \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

# Dependencies first, for layer caching. package = false, so this installs deps only.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY manage.py entrypoint.sh ./
COPY src/ ./src/

RUN chmod +x entrypoint.sh \
    && adduser --system --no-create-home app \
    && mkdir -p /data /app/staticfiles \
    && chown app /data /app/staticfiles
# Code stays root-owned and read-only to the runtime user, so a future RCE cannot
# rewrite the app to persist. Only the data and static dirs are process-writable.

USER app
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
# The entrypoint is role-aware (TS-CO-3): the gunicorn CMD marks the web role,
# which owns secret generation, the pre-flight backup, migrate, collectstatic,
# and ensure_setup. The worker overrides CMD with `procrastinate worker` and
# skips all of that, so it never races the web container's migrations.
CMD ["gunicorn", "config.wsgi:application", \
     "--chdir", "/app", "--bind", "0.0.0.0:8000", "--workers", "3", \
     "--error-logfile", "-"]
