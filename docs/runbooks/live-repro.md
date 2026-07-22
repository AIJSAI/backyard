# Runbook: live-repro & the tested→passing loop

The Phase-2 retro flagged this harness as undocumented tribal knowledge ([LOW] debt). This
captures it so the **tested→passing loop** (Phase-3 step 5, against the persistent instance) and
any story's live-repro are turnkey and reproducible — not re-derived each time. Everything here is
**verified through use**, not aspirational. It is design-independent (behavior, not visuals), so it
holds regardless of the Claude Design pass.

Two distinct things live here: (A) the **local gate + live-repro** used to verify a change before
merge, and (B) the **deploy + passing loop** on the persistent Ubicloud instance.

---

## A. Local gate + live-repro (before merge)

### Standalone Postgres (the compose `postgres` does NOT publish 5432 to the host)

The compose stack keeps Postgres on an internal network, so `pytest` (which connects to
`localhost:5432`) needs its own DB:

```bash
docker run -d --name backyard-test-pg \
  -e POSTGRES_DB=backyard -e POSTGRES_USER=backyard -e POSTGRES_PASSWORD=ci-not-a-secret \
  -p 5432:5432 postgres:18-alpine
```

### The gate (mirrors CI's `code` job)

```bash
export DJANGO_SECRET_KEY=ci-not-a-secret-deadbeef-cafe-1234567890   # MUST be ≥32 chars (TM-8 fails closed otherwise)
export POSTGRES_HOST=localhost POSTGRES_PASSWORD=ci-not-a-secret
uv run ruff check src && uv run ruff format --check src
uv run mypy src
uv run pytest                     # video tests need a real ffmpeg on PATH (`brew install ffmpeg`)
DJANGO_DEBUG=0 BACKYARD_BASE_URL=https://ci.example.com DJANGO_ALLOWED_HOSTS=ci.example.com \
  DJANGO_SECRET_KEY=ci-deploy-check-not-a-secret-0123456789abcdef0123456789abcdef \
  uv run python manage.py check --deploy --fail-level WARNING
```

### Cross-browser e2e (the S-101 mobile onboarding proof)

`pytest -m e2e` is deselected by default; it drives real engines and needs Playwright browsers
installed (WebKit = iOS Safari, Chromium = Android Chrome):

```bash
uv run pytest -m e2e            # 8 tests; needs the browsers + a live_server
```

### The full stack for a real browser-through-Caddy repro

```bash
make up            # generates .env (3 db-role passwords), brings up web+worker+postgres+caddy
make setup-secret  # prints the one-time first-admin secret from the web logs
# open http://localhost:8000/setup/  → create the first admin
```

### Gotchas that have burned us (each cost real time)

- **browser-vs-curl CSRF asymmetry — the big one.** `Referrer-Policy: no-referrer` makes a browser
  send `Origin: null` on a same-origin form POST → Django's CSRF Origin check 403s → *every form is
  broken in a real browser* even though `curl` (no Origin) and the `live_server` fixture (no Caddy)
  pass. **A form change is only proven by driving it in a real browser through the Caddy edge**
  (`localhost:8000`), never by curl or `live_server` alone. (Fixed per-surface: `same-origin` floor,
  `no-referrer` only on the form-less token-in-URL `/t/`,`/d/`,`/media/` surfaces.)
- **zsh eval PATH:** `curl` may not resolve under a `zsh -c` eval; run repro scripts with
  `bash script.sh`.
- **SSRF repros need a real public URL** — `cloudflared` quick tunnels are unreliable; point the
  fetcher at a stable public page.
- **Inline `<style>`/comments leak into rendered HTML** — several tests assert on rendered `.content`
  (copy strings, `type="checkbox"` counts, `26px` in the elder view). Don't put a test-matched string
  in a CSS comment, and use unquoted attribute selectors (`[type=checkbox]`) so the stylesheet
  doesn't trip a structural count guard.
- **Deploy check** needs a ≥50-char, ≥5-unique-char secret or it warns (`security.W009`); use the
  long CI-style key above for `check --deploy`, not the short test key.
- **`op` (1Password):** macOS has no `timeout`; do NOT wrap `op read` in it (false-negative). Read
  secrets directly: `op read "op://Backyard/<Item>/<field>"`.
- **Cleanup:** `docker rm -f backyard-test-pg` when done; `make down` for the compose stack.

---

## B. Persistent instance deploy + the tested→passing loop (step 5)

> **VERIFIED 2026-07-22** — the instance is live at https://backyard.family (Ubicloud us-east-a2,
> `108.62.118.152`). Receipt: `docs/receipts/2026-07-22-s728-persistent-instance.md`. All secrets via
> `op read "op://Backyard/…"` (Ubicloud API, Cloudflare DNS Token, Resend, first-admin secret). Run
> multi-value shell loops under **bash**, not zsh (zsh does not word-split unquoted `$var`), and use
> `/usr/bin/curl` (curl is not on the zsh-eval PATH).

1. **Provision** (Ubicloud REST API, base `https://api.ubicloud.com`, `Authorization: Bearer <PAT>`):
   `POST /project/{project_id}/location/us-east-a2/vm/{name}` with an SSH `public_key`, `boot_image`
   **`ubuntu-noble`** (codenames, not `ubuntu-24.04` — a 400 returns the valid set), `size` `standard-2`,
   `storage_size` 40. Poll `GET …/vm/{name}` until `state=running` for the `ip4`. project_id
   `pjwfd7p9m80e3kybnr2xrs0ywq`.
2. **Firewall (do this right):** the default firewall opens ALL ports — scope it to TCP 22/80/443.
   `POST …/firewall/{fw}/firewall-rule` `{"cidr":"0.0.0.0/0","port_range":"22..22"}` (+ 80, 443, and
   `::/0`), **confirm the scoped rules exist, THEN** `DELETE …/firewall-rule/{id}` the four broad ones.
   (Delete-before-add briefly locked out HTTPS once.)
3. **DNS:** `backyard.family` A → the VM `ip4`, **DNS-only** (proxied:false) so Caddy owns TLS.
   Cloudflare API, zone `90a11296ca7850a5dd56df4239328644`.
4. **Deploy:** SSH in (`~/.ssh/backyard_vm`, user `ubuntu`); install Docker (`curl -fsSL get.docker.com | sudo sh`
   + `usermod -aG docker ubuntu`); copy the tree (`tar czf - … | ssh … tar xzf -`); write `.env` (three
   postgres passwords + `BACKYARD_DOMAIN` + `ACME_EMAIL` — the prod overlay derives
   `DJANGO_DEBUG=0` / `DJANGO_ALLOWED_HOSTS` / `BACKYARD_BASE_URL` from the domain, so the HTTPS
   posture can't hinge on a forgotten var); then
   `docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d`. Caddy auto-fetches the
   Let's Encrypt cert on first hit. First-admin secret: `docker compose logs --no-log-prefix web | awk '/paste this one-time secret/{getline;gsub(/^ +/,"");print}'`.
5. **Wire email on the box:** set the Resend env (`op read "op://Backyard/Backyard Resend API/credential"`),
   confirm the health email sends (T-MON-1) and re-measure the delivery/bounce matrix on a **real** elder
   subscription (⚠️ Resend sits behind Cloudflare WAF — a `Python-urllib` UA gets HTTP 403 `error code: 1010`;
   confirm Anymail's `requests` UA passes at the live send).
6. **The tested→passing loop:** for each v1 story in `stories/stories.yaml`, run its acceptance against the
   **live deployed app** (browser-through-Caddy for anything with a form, per the CSRF gotcha), capture a
   receipt, and flip `tested → passing`. Never tear the instance down — `passing` is only meaningful
   against a persistent box.
7. **A11y:** run the full axe-in-browser sweep across every surface against the live instance (the WCAG-AA
   depth beyond the token-contrast guard, proven end to end).
