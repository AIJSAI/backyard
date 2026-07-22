# Persistent Ubicloud instance stood up (S-728) — close receipt

Date: 2026-07-22. Phase 3, **step 5 (part 1)**: ONE persistent, internet-facing instance is
live at **https://backyard.family**, serving over TLS. This ends the "proven-live only on
throwaway `compose up … down -v` stacks" era the retro flagged — the box now persists, which is
the precondition for the `tested → passing` loop and founder QA.

## What is live

- **VM:** Ubicloud `backyard` in **us-east-a2** (closest US region for the Omaha founding family) —
  `ubuntu-noble` (24.04.2 LTS), `standard-2` (2 vCPU / 7.8 GiB), 40 GiB. Public IPv4 `108.62.118.152`.
  Provisioned via the Ubicloud REST API (`POST /project/{id}/location/us-east-a2/vm/backyard`).
- **DNS:** `backyard.family` A → the VM (Cloudflare, DNS-only so Caddy owns TLS).
- **TLS:** Caddy fetched a **Let's Encrypt** cert automatically (valid to Oct 20 2026, auto-renewing).
- **Stack:** the four ADR-002 containers (postgres 18 / web+gunicorn / worker / caddy) up via the new
  production overlay; migrations applied first-boot; app-role split (ADR-004) intact.
- **Firewall (hardened):** the Ubicloud default firewall opened **all** ports; scoped to exactly
  **TCP 22 / 80 / 443** on v4+v6. Postgres (5432) and everything else are now denied from the
  internet (defense-in-depth; the box was already catching `/secrets.json` scans within a minute).
- **First-admin setup secret** captured to `op://Backyard/Backyard first-admin setup secret`
  (the instance is at `/setup/`, awaiting the first admin — deliberately not consumed yet).

## What shipped (the reproducible production deploy — PATH-TO-100 criterion 6 groundwork)

The repo shipped a **local-only** Caddy (loopback:8000, plain HTTP). Added the production overlay so
a real deployment is one command, not tribal knowledge:

- **`docker-compose.prod.yml`** — publishes Caddy on `0.0.0.0:80/443` (replacing the loopback:8000
  binding via a compose `!override`) and mounts the production Caddyfile; web/worker read
  `DJANGO_DEBUG=0` / `DJANGO_ALLOWED_HOSTS` / `BACKYARD_BASE_URL` from `.env`.
- **`caddy/Caddyfile.prod`** — `{$BACKYARD_DOMAIN}` with auto-TLS, carrying the same edge posture as
  local (nosniff, `-Server`, the 512 MB body ceiling, and the deliberate NO-`Referrer-Policy`/NO-`log`
  cautions that the browser-CSRF and TS-EDGE-LOG findings require).
- Deploy: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d` with a `.env`
  carrying the three postgres passwords + `BACKYARD_DOMAIN` + `ACME_EMAIL` + the prod Django vars.
- Documented end-to-end in `docs/runbooks/live-repro.md` §B (now the *verified* procedure, not an outline).

## Verification (live, on the box)

- `https://backyard.family/healthz` → **200** over HTTPS; `/setup/` → 200; `/` → 302 (first-run
  redirect); `/robots.txt` → 200. Valid Let's Encrypt cert (issuer verified).
- The S-720 design renders correctly on the live instance (screenshotted `/setup/` over TLS — warm
  paper, brand mark, serif heading, styled form + primary button, footer).
- Firewall re-verified after scoping: SSH (22) up, HTTPS (443) up, all four containers stable.

## Gotchas hit + recorded (so the next deploy is turnkey)

- Ubicloud boot images use **codenames** — `ubuntu-noble` (24.04), not `ubuntu-24.04` (the API returns
  the valid set on a 400).
- **zsh does not word-split** unquoted `$var`, so a `for spec in "cidr port"` firewall loop sent a
  malformed cidr — five adds 400'd while four broad deletes 204'd, briefly leaving only :22 open and
  HTTPS blocked. Fixed with explicit per-rule calls. Lesson: **add the scoped rules and confirm them
  BEFORE deleting the broad ones**, and don't rely on shell word-splitting under zsh.
- Ubicloud firewall create-rule is `POST …/firewall-rule` with `{cidr, port_range:"N..N"}`; protocol
  defaults to `tcp`.

## Remaining in step 5 (next)

1. The **tested → passing** loop: verify each v1 story against the live app (browser-through-Caddy for
   any form, per the CSRF finding), receipt each, flip `tested → passing` in `stories/stories.yaml`.
2. **Email on the box:** wire Resend (`op://Backyard/Backyard Resend API`), confirm the health email
   sends, and re-measure the delivery/bounce matrix on a real elder subscription (⚠️ the Resend/WAF
   `Python-urllib` 1010 gotcha — confirm Anymail's UA passes at the live send).

Then the Claude Design visual pass gets applied + re-verified on this box, and it goes to founder QA
(step 6) — the last gate before the pod-of-6 share.
