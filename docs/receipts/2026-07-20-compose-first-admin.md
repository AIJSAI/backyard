# Receipt: docker compose up reaches the first-admin flow

Date: 2026-07-20. Operator: orchestrator session (Phase 1 goal). Host: macOS, Docker 29.4.3, from a clean checkout with all named volumes removed first (`docker compose down -v`).

This is the S-801 walking skeleton: a fresh machine goes from nothing to a working instance with an admin, through the reverse proxy, with the first-run wizard gated by a console secret (threat model TM-8). It is not the product; there is no feed yet.

## The run

```
$ printf 'POSTGRES_PASSWORD=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" > .env
$ docker compose up --build -d
 Container backyard-postgres-1  Healthy
 Container backyard-web-1       Started
 Container backyard-caddy-1     Started
```

`make up` does the same thing in one command (it generates `.env` if missing).

## What was verified, in order

| # | Check | Result |
|---|---|---|
| 1 | `GET /healthz` (process up, database answers) | `{"status": "ok"}` |
| 2 | `GET /` with no admin yet | `302 -> /setup/` |
| 3 | Setup secret printed only to the web console (TM-8) | 43-char token, read from `docker compose logs web` |
| 4 | `GET /setup/` issues a CSRF cookie and token | ok |
| 5 | `POST /setup/` with the secret, username `james`, a strong password | `302 -> /` (admin created) |
| 6 | `GET /` after setup | `<h1>Backyard is running</h1>`, admin `james` |
| 7 | `GET /setup/` after an admin exists (wizard hard-disabled) | `404` |
| 8 | Published host ports | only `caddy`, bound to `127.0.0.1:8000` (loopback); web and postgres have no host binding |
| 9 | First-boot secret generation | `Generated a new DJANGO_SECRET_KEY, persisted at /data/secret_key.` |
| 10 | `docker compose config` with no `POSTGRES_PASSWORD` | exits 1: "required variable POSTGRES_PASSWORD is missing a value" (no default credential) |
| 11 | App boot with `DJANGO_SECRET_KEY=changeme` | `RuntimeError: ... empty or a placeholder ... TM-8` |

Checks 8, 10, and 11 are the TM-8 commitments made real: one published port (the proxy), no default credentials, and no boot on a placeholder secret.

## Static checks (same as the CI `code` job)

```
$ uv run ruff check src && uv run ruff format --check src   # All checks passed
$ uv run mypy src                                           # Success: no issues in 15 source files
$ uv run pytest                                             # 7 passed
```

The seven tests cover the wizard: home redirects to setup when no admin exists, the correct secret creates the admin and consumes the token, a wrong secret and a weak password are both rejected, the wizard 404s once an admin exists, and `/healthz` answers. They are the seed of S-801's acceptance tests.

## Teardown

```
$ docker compose down -v
```

Image size: 558 MB (python:3.13-slim base). Reproduce anytime with `make up` then `make setup-secret`.

## Security review

The scaffold went through a security-reviewer pass before merge (auth/secrets/input surface). No CRITICAL. One HIGH, a TOCTOU race where two concurrent setup POSTs could each create an admin, is fixed: the secret verify and admin creation now run in one transaction with the token row locked and the "zero admins" gate re-checked under the lock, so the TM-8 close is atomic. The MEDIUM and LOW findings (secret-length floor, loopback bind, username validation, password-vs-username, secret-file permissions, root-owned code, image digest pins, gitleaks checksum) were folded in while the surface is small. Tests were added for the gate-closed-under-lock path, CSRF enforcement, and input validation.

