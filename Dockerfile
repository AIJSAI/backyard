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
