# Outstanding — the security-pass record, plus what a readiness audit added

> **This is a RECORD, not a queue.** It was written 2026-07-30 and titled "the single list",
> and it was not one: reading it as a *complete* backlog is what left backups, monitoring,
> audit logging and the product's only notification channel invisible until a six-axis
> readiness audit on 2026-08-01 found roughly thirty items it did not contain, seven of them
> critical ([§6](#6-what-the-2026-08-01-readiness-audit-added)).
>
> **Open work lives in GitHub issues** — `gh issue list --state open` — and nothing here is a
> second copy of that list. What this file is for is the reasoning: findings kept with their
> verdicts and their evidence, so a closed item can be re-opened by somebody who can see why
> it was closed. Anything below that is still open carries its issue number, or says plainly
> that it has none.

Items are marked with the audit finding they came from so you can go back to the source.
Verify with a primary check (`git log`, `gh issue list`, run the probe the item names) rather
than trusting the state below; that instruction has earned its keep in this file repeatedly.

There is deliberately **no state line here any more.** It used to read "State on 2026-08-01:
`main` = `162c620` · 811 passing / 2 skipped · 46 stories passing…" — four numbers that were
each false within the week, at the top of the document people read first. The commands that
derive them are in [`RESUME-HERE.md`](RESUME-HERE.md).

---

## 0. Operator actions — ALL FOUR DONE (1–3 on 2026-08-01 CDT / 2026-08-02 UTC; 4 confirmed 2026-09-19)

Done over SSH with founder authorisation, each verified rather than assumed. Secrets live in
the **1Password `Backyard` vault**; no secret value is in this repo, on a command line, or in
a shell history.

> **On the two dates.** The work happened on the evening of **2026-08-01 US Central**, which
> was already **2026-08-02 UTC**. The box runs UTC, so artefacts it named itself carry the
> later date — `backup-2026-08-02.bak`, `preflight-20260802023148.dump.enc`. Both are correct;
> they are the same moment. Worth stating because it recurs every evening, and an operator
> log whose dates disagree with its own filenames is one an operator stops trusting. **When
> you correlate a runbook entry with a file on the box, compare in UTC.**

| # | Action | State |
|---|---|---|
| 1 | **Rotate the demo accounts** | **DONE.** Checked empirically first: the burned password authenticated `priya`, `sam`, `dave` and **not** `james` — the instance admin predates the seed, so it was never the leaked value and was left untouched. The three were rotated to a generated password (1P: *Backyard demo family logins*). Verified over HTTPS against the live site: the burned credential now returns **200 (rejected)**, where it previously returned 302 (success). |
| 2 | **Set `BACKYARD_BACKUP_PASSPHRASE`** | **DONE.** Generated in 1Password *first* (there is no key escrow), then piped to the box over stdin — never through a command line. Boot log now reads `Pre-flight backup written ENCRYPTED: preflight-….dump.enc`, and that file was proven to decrypt to a real `PGDMP` archive. The 1P value was hash-compared against the container's env to prove they match. |
| 3 | **Take a backup** | **DONE** — the first in the project's history. `backup-2026-08-02.bak`, 512,071 bytes, encrypted; copied off the box to `~/backyard-backups/`, SHA-256 matched, and **decrypted locally** to `backup-manifest.json` + `database.dump` (PGDMP) + `media.tar.gz`. Only after that were the remaining plaintext pre-flight dumps deleted — they were, until then, the only copies of the database in existence. |
| 4 | **Register the Resend inbound webhook** | **DONE.** Read from the provider on 2026-09-19: the endpoint `/anymail/resend/inbound/` is registered for `email.received` and enabled, and the sending domain is verified. Real mail was measured in a real inbox the same day — SPF, DKIM and DMARC all pass, and both the Family-email confirmation and the account verification arrived in the inbox with working links. Nothing in this repository can assert any of that, so it is recorded as a measurement on a date. The ordering objection below is also spent: C6 is closed. |

**No plaintext copy of the family database now exists anywhere** — on the volume, in `/tmp`,
or off-box. That was the single worst standing exposure.

Note for the future: an agent session *can* do these after all, over SSH with the key at
`~/.ssh/backyard_vm`. The classifier refusal applies to a local `docker compose exec`, not to
`ssh … 'docker compose exec …'`. What actually gated this was founder authorisation, which is
the right gate.

---

## 1. Decisions only the founder can make

Nothing below moves until these are answered.

**Admin 2FA (T-ADMIN-1) — RULED 2026-09-19: offered, not enforced. No longer waiting on
anyone.** The threat model claimed *"passkey or TOTP, enforced in the wizard so a
password-only admin never exists"* and nothing ever enforced it; the record was corrected
rather than the code. Requiring one means lockouts for the two non-technical relatives
becoming admins here, and a locked-out admin on a family box is recovered only through a
server shell they have not got. What ships is the offer: a second factor available to every
account, the account-security page reachable from Settings, and one calm dismissible prompt
on the member roster for an admin with nothing enrolled. Enforcement for the INSTANCE ADMIN
alone — one account, the person who does have the shell — is a narrower question and is
filed as issue 182 for the owner.

**S-603 — build the ambient photo frame, or cut it?** The last `spec` story. If built it
needs a threat-model entry *before* code (new always-on bearer credential on a device in a
room); a five-row `T-DISPLAY-*` draft is at
[`security/s603-display-threat-draft.md`](security/s603-display-threat-draft.md).

~~**S-603 carries its own contradiction.** `metrics.md:9` defines active as *"any **deliberate**
touch"*; `metrics.md:21` counts a **frame heartbeat** toward the elder touch rate.~~ —
**RESOLVED 2026-09-19 in the docs-truth pass.** The recommendation was taken: `metrics.md` no
longer counts a heartbeat toward the elder touch rate, and says in the same file why — keep
the heartbeat when S-603 is built, record it under its own name, keep it out of `touched`.
That is the reversible direction, and un-corrupting a KPI's history later is not a one-line
change. The decision the founder still owns is whether S-603 gets built at all.

**Founder QA walk** ([`runbooks/founder-qa.md`](runbooks/founder-qa.md)) — ~90 minutes, and
always the gate before anything is shared. Wipe the demo family first
(`manage.py wipe_demo_data --dry-run`, then `--yes`).

---

## 2. Security findings not yet fixed

From the 2026-07-30 five-angle fan-out. Everything CRITICAL and HIGH was fixed in #108–#113;
these are what remains. Each was **re-confirmed still present on 2026-07-30** before being
written here.

### Worth doing next

| # | Finding | Where |
|---|---|---|
| ~~S1~~ | **DONE 2026-09-19 (security-hardening PR).** `core.inbound_webhook.BoundedResendInboundWebhookView` overrides the two fetch helpers with a connect/read timeout and a streamed, size-capped read; a refusal lands on the admin's quarantine panel rather than as a 500 the provider retries. ~~Anymail's inbound fetch has no `timeout=` and no size cap.~~ Three `requests.get` calls with neither, inside the webhook's own request cycle — so a slow provider pins a gunicorn worker indefinitely, and the size cap in our code applies only *after* the whole message is downloaded and parsed. Fix by enqueueing the fetch on the worker with a bounded, timed read. | `anymail/webhooks/resend.py:277,287,331` (upstream — needs a subclass) |
| ~~S2~~ | **DONE 2026-09-19 (security-hardening PR), with issue 173.** `core.throttling.FamilyLinkThrottleMiddleware` bounds `/t/`, `/d/`, `/join/`, `/get-back-in/`, `/break-glass/` and the two digest pages, GET included, and refuses with the product's own calm page. In MIDDLEWARE rather than in the views because ATOMIC_REQUESTS rolls a view's counter write back on the Http404 path — i.e. on exactly the requests worth counting. `/media/` is excused BY NAME with its reason. ~~No rate limiting on the unauthenticated bearer surfaces' GET.~~ `/t/`, `/d/`, `/media/`, `/join/`, `/break-glass/`, `/get-back-in/` — all hit the DB on a GET, none throttled, and each 404 now renders the ~26KB branded page. Token entropy is 256-bit so this is availability, not guessing. `middleware.py` names the gap itself. Two of the three surfaces that SET a credential throttle their POST (`/join/` and `/get-back-in/` both consume allauth's `login` limit). `/break-glass/` does NOT — it resets an instance admin's password on an unauthenticated POST with no limit of any kind (`core/breakglass.py::break_glass` makes no `ratelimit.consume` call), which is the one act in this row worth the most to an attacker. So the gap is the bare lookup on every surface, AND the act on `/break-glass/`. | `elder_views.py`, `digest_views.py`, `media_views.py` — confirmed 0 rate-limit calls |
| ~~S3~~ | **DONE 2026-09-19 (security-hardening PR).** `emailing.strip_control` / `strip_control_keep_breaks` are the one rule, applied by `posting`, `commenting` and a `pre_save` receiver on `Member`; tested on printability rather than category Cc, because the bidi overrides this was about are category Cf. ~~Control characters are not stripped from post bodies or display names.~~ The inbound path strips; the web composer and profile editor do not, and `digest.txt` renders with `autoescape off`. A bidi override or ANSI escape in a name reaches the plaintext digest verbatim; a `\x00` is a 500. | `posting.py`, `commenting.py` — confirmed 0 `strip_control` calls |
| ~~S4~~ | **DONE 2026-09-19 (security-hardening PR).** `config.urls._inbound_urlpatterns` mounts it only when `RESEND_INBOUND_SECRET` is configured, and the view's `dispatch` refuses it anyway. ~~The webhook route is mounted unconditionally~~, and the secret is only required when the Resend *send* backend is active. On the documented SMTP config, every unauthenticated POST is an unhandled 500. Fail-closed today only by an upstream library rejecting an empty secret. | `config/urls.py`, `config/email_guard.py` |
| ~~S5~~ | **DONE 2026-09-19 (security-hardening PR).** `received_for` only, a multi-recipient delivery is refused rather than resolved to its first element, and no trustworthy address means no post — with a quarantine row so the refusal is visible. ~~`_trusted_recipient` falls back to a sender-controlled `To:` header~~ when the transport supplies no envelope recipient, and takes `[0]` of a multi-recipient list. Converts TM-4's "the address IS the credential" into "a header is the credential". Should fail closed. | `inbound_webhook.py:40-54` |
| S6 | **Supply chain** — mostly CLOSED 2026-09-19. Every third-party action is pinned to a full commit SHA with its release tag in a trailing comment (`checkout` v7.0.1, `setup-python` v7.0.0, `setup-uv` v10.1.0, moved to their current majors), and `.github/dependabot.yml` now runs weekly grouped version updates for `uv`, `docker`, `docker-compose` and `github-actions`, which is what keeps a SHA pin from rotting. **"Dependabot disabled" was never true and is the part of this row to read twice**: security updates have been enabled the whole time — PR #164 and #129 are its output — and what was missing was the *version*-update config, so nothing was ever going to open a pull request for a stale action pin or a stale base-image digest. The Dockerfile base still floats, now on purpose and recorded (see the `FROM` comment and threat model TS-CO-8): it is the only cache key above the apt layer, so a digest pin would freeze the pg client and ffmpeg behind somebody remembering to bump it. **Still open**: `pip-audit` is invoked unpinned (`uv run --with pip-audit`) beside a checksum-verified gitleaks and a pinned `bandit==1.9.2`, and there is still no container/OS image scan. | `.github/workflows/`, `.github/dependabot.yml`, `Dockerfile` — re-measured |
| ~~S7~~ | **DONE (#118).** `pyproject.toml` declares `cryptography>=50,<51` with the reason on the line. ~~The primitive the entire backup guarantee rests on arrives only via `django-allauth[mfa]` → `fido2`.~~ The day that extra changed, encrypted backup and restore would have broken at import — on the one code path with no fallback and no key escrow. | `pyproject.toml` — re-measured 2026-09-19 |

### Smaller, still real

**S8–S24 are carried as ONE tracked item, issue 195**, together with the gate entries still
open after this pass (G3, G4, G5). They are recorded here with their evidence rather than
filed one-per-issue, because seventeen issues nobody has scheduled turns the tracker into a
second version of this file. Where a line names a different issue or a pull request, that is
the one that carries it.

- **S8** — `profiles._can_see_field` returns `True` for YARD unconditionally; every current caller pre-scopes, so no live route, but one future caller reintroduces T-YARD-6. Adjacent, and filed: `can_edit_profile_of` carries the same supervised-parent bypass the household surface now re-checks (issue 181, item 4).
- **S9** — **DONE 2026-09-19 (security-hardening PR), with issue 174's first half.** `pods.leave_pod` now locks the member row, refuses a leave that would strand somebody, and runs `revocation.revoke_for_membership_shrink` scoped to the sides actually being lost, before the membership row goes. Pod-leaves-yard and the deceased flow are still unbuilt and are named as unbuilt in TM-1 rather than described as shipped.
- **S10** — Break-glass keys on `is_superuser`, so a *promoted* instance admin (the S-707 succession path) has no recovery path.
- **S11** — `notify_reply` rotates the unsubscribe token on every nudge, invalidating the link in the digest already in her mailbox.
- **S12** — `create_supervised` places the child in the **actor's** pod, not the named parent's.
- **S13** — The bigint-cursor guard exists in one id parser and is missing from the others (`handover.int_or_404`, `pod_views._int`, `breakglass._resolve_admin`) → 500 on a 21-digit id.
- **S14** — `can_assign_role` would permit `SUPERVISED`; unreachable today only because the view allowlists first.
- **S15** — Session lifetime is a fixed 2-week window with no absolute cap or rotation on privilege change (TS-DJ-1 residual, disclosed).
- **S16** — **DONE 2026-09-19 (security-hardening PR).** `viewers._reader_from_elder_session` applies the same live-token check, so a deleted `ElderToken` row stops the photographs as well as the feed.
- **S17** — **DONE 2026-09-19 (security-hardening PR).** `settings.LOGGING` declares `core` on the redacting handler, so no module under it can be a fourth unfiltered sink.
- **S18** — **DONE 2026-09-19 (security-hardening PR).** The validator moved to `core/outbound_addresses.py` and both fetchers share it; `domain_expiry` resolves, range-checks and pins on every hop through `_ValidatedHTTPSHandler`, before the connect.
- **S19** — Staging disk budget is per-session with no instance-wide cap, on the volume holding `/data/secret_key`. Related and filed: media lives on the box's own disk and the small VM class tops out well short of a family's photo history (issue 176).
- **S20** — **Extraction cap DONE 2026-09-19 (security-hardening PR):** `backups._refuse_an_oversized_extraction` refuses against the destination volume's free space, a per-member ceiling and an absolute total, loudly and before a byte is written. STILL OPEN: restore trusts an unauthenticated plaintext archive when no passphrase is configured — the module docstring's trust boundary is the only control there. The three ceilings being module constants rather than settings is filed as issue 187, item 3.
- **S21** — `export.py` reads a whole video into memory; `/settings/export/` has no rate limit.
- **S22** — Icons re-render with Pillow on every request, unauthenticated.
- **S23** — `link_preview` raises an unhandled `ValueError` on a scope-qualified IPv6 from `getaddrinfo`.
- **S24** — `read_only` rootfs still unset (needs `collectstatic` moved to build time); `write` timeout deliberately unset.

### Hygiene / disclosure

- **S25 — STILL OPEN, and it is product code, not a document.** 26,041 bytes of developer CSS
  commentary — re-measured 2026-09-19 against `src/core/templates/core/base.html`, 36.4% of
  that file, plus 1,557 bytes more in `elder_feed.html` — is served to every unauthenticated
  visitor, disclosing internal story IDs and `django-allauth`. Nothing strips comments at
  render time (`core/middleware.py`, `config/settings.py`). Caddy's `encode zstd gzip` now
  masks the wire cost; the **disclosure** is unchanged, and compression is not the fix. The
  fix is to strip at render time and keep them in source — they are load-bearing for whoever
  reads the templates next. **Tracked as issue 191**; it is deliberately not fixed in a
  documentation pull request, because a render-time change to every page in the product is
  not a docs change however small the diff looks.
- ~~**S26**~~ — **DONE.** The Ubicloud project id and Cloudflare zone id are parameterised in
  `runbooks/live-repro.md` and the 2026-07-26 audit, and the return of that class is guarded
  by shape rather than by a denylist (`src/core/tests/test_no_infrastructure_identifiers.py`,
  which also names the three documents it must be scanning so it cannot go vacuous).
- **S27 — STILL OPEN.** The maintainer's real email is in
  `receipts/2026-07-22-wave-4-close.md`, named as the live inbox. Already public through git
  author metadata on every commit, which is why it is hygiene rather than a finding — but a
  receipt is a dated record and editing one to clean a grep is the thing this project has
  repeatedly decided not to do, so closing it is a judgement call rather than an edit.
  Tracked as issue 192.
- **S28** — **DONE 2026-08-01.** The demo relative carrying the author's real surname is now `Priya Whitfield`, matching the fictional family the design tooling already used. It had also reached a shipping `posting.py` comment and two receipts, and the README carried a blanket "no real family content" claim that was false a few files away — both corrected. Guarded by `src/core/tests/test_privacy_line_holds.py`.
- **S29** — ~~No `/.well-known/security.txt`~~ **half DONE:** `caddy/Caddyfile.prod` serves one, with a `Canonical:` line. Still absent: `Permissions-Policy`, `CORP`, `COEP` — tracked as issue 193.

---

## 3. Gates that still overstate

From the gate audit. These do not break anything today; they mean a future regression goes
unnoticed. Most are closed; the three still open after the 2026-09-19 pass — G3, G4 and G5 —
are carried with S8–S24 as issue 195.

- **G1** — ~~`test_self_host_docs.py` **suppresses itself**: `pytest.skip` when a command is not
  named in the guide, so 2 of 3 cases are vacuous~~ **CLOSED (#144).** The enumeration was
  inverted and is now the right way round: it walks the commands the guide *names* and asserts
  each resolves, with a denominator test so an extractor returning nothing cannot pass it
  trivially. The skips are gone; only the prose describing them remains. See §7.8.
- **G2** — ~~**Required contexts are job-level.** Deleting a *step* — bandit, a selftest, the
  compose live probe — leaves its context green. No test reads `ci.yml`.~~ **CLOSED (#144)** —
  `src/core/tests/test_ci_still_runs_what_it_claims.py` reads the workflow. Proven by probe:
  deleting the bandit scan left 11 mentions of "bandit" and the old rule green.
- **G3** — The isolation registry is satisfiable by **classification, not coverage**: adding a
  model to `_ISOLATION_EXEMPT` with any non-empty reason passes. ADR-004 claims "a new model
  **without an isolation fixture** fails the build"; what ships fails on a missing *name*.
- **G4** — ADR-004's promised **repo-wide raw-SQL ban never shipped** — `check_digest_confinement`
  guards exactly one file out of 60+. Two live `connection.cursor()` sites are unpoliced.
- **G5** — `check_stories.py`'s evidence rule is a **substring test**: `evidence: trust me`
  passes. All 91 references do resolve today; nothing enforces it. ~10 lines to add.
- **G6** — ~~`scripts/axe_sweep.py` appears **nowhere in CI**~~ **CLOSED 2026-09-19.** It runs
  as a step of the existing `e2e` job — the only job that already installs Chromium, which is
  why it costs minutes rather than a new lane: seed a throwaway instance, run a server, sweep.
  Measured before wiring: 33 surfaces, 132 renders, 0 violations, 0 serious/critical, with
  `DJANGO_DEBUG=0` so the branded 404 and the real static pipeline are what gets swept. The
  script now **exits non-zero** on a serious/critical finding (a step that always exits 0 is a
  decorative gate), and `axe.min.js` is fetched pinned and checksum-verified rather than
  vendored. Still manual, and named rather than implied: the hover pass covers the *first*
  primary button on a page, and `member-profile` is skipped when the viewer's directory is
  empty — the sweep says so in its own output.
- **G7** — ~~Caddy's security invariants are enforced by **comments**, not a guard~~
  **CLOSED 2026-09-19.** `src/core/tests/test_caddy_security_invariants.py` parses
  `caddy/Caddyfile.prod` with comments stripped (its own cautions quote the directives they
  forbid) and asserts `admin off`, no `log`, no global `Referrer-Policy`, `-Server`, `-Via`,
  `nosniff`, the aborted `:443` fallback and the internal-only `:8000` health block — plus
  that the production overlay publishes 80 and 443 and nothing else. Seven mutation tests
  break each invariant in the real file's text and require the matching check to go red.
- **G8** — ~~`backups.py`'s module docstring says *"the archive is a plain tar … nothing here
  holds a key"*.~~ **CLOSED (#118).** Re-read 2026-09-19: the docstring says "ENCRYPTED AT
  REST BY DEFAULT (S-802)" and points at `backup_crypto.py` for the construction.
- **G9** — ~~The backup runbook puts the migrator password on the host command line, in the same
  document that (correctly) says never to do that with the passphrase.~~ **CLOSED (#118).**
  The runbook now says compose already places `POSTGRES_MIGRATOR_PASSWORD` in the web
  service's environment and that passing it with `-e` is the same mistake; the one remaining
  use is `PGPASSWORD="$POSTGRES_MIGRATOR_PASSWORD"` *inside* the container's own `sh -c`
  during the drill, which never reaches a host shell's history.
- **G10** — **DONE 2026-09-19 (security-hardening PR).** The secret goes to a 0600 file on the data volume (`SETUP_HANDOVER_FILE`, default `/data/first-run-secret`); only the path is printed, the file is deleted when setup completes and again on the next boot, `make setup-secret` reads it, and the CI compose probe asserts live that it is 0600 and that its value appears nowhere in the container log.

---

## 4. What nobody has verified

Not findings — gaps in evidence. Each needs a person or a real device.

- **No real phone has imported a vCard.** Validated against `vobject`, not iOS Contacts. Same
  for the yearless birthday.
- **No real device has installed the PWA**, and **no elder has held the elder path**. Everything
  about that experience is verified by me driving a browser.
- ~~**The health email has never been seen landing in a real inbox** — only its sender output.~~
  **CLOSED 2026-09-19 for two of the three transactional paths**: the Family-email confirmation
  and the account verification were both measured arriving in a real inbox, with SPF, DKIM and
  DMARC passing and their links working. The weekly health email itself still has not been
  watched land; it rides the same sending path, which is evidence and not proof.
- ~~**Restore has never run against production data** (there is no backup to restore).~~
  **CLOSED 2026-09-19.** An archive of the real instance was restored onto a different
  machine, and the instance it produced was walked. That is also where the two restore traps
  now in [`runbooks/backup-restore.md`](runbooks/backup-restore.md) came from — the file has
  to be streamed in as the app user, and `migrate --check` stays at 1 until web and worker
  restart.
- **No independent security review.** The threat model is thorough and entirely self-authored;
  the 2026-07-30 pass was still me, with agents. Unchanged, and the largest gap in this list.

---

## 5. Product work remaining

**S-603** is the only `spec` story — see the decisions above.

**Phase 5, OSS launch machinery** (7 items, all gated on the founder deciding to go public):
docs site · public demo instance · GHCR images and tagged releases · NAS store listings ·
awesome-selfhosted PR · API + MCP endpoint · launch posts.

**Phase 6, rollout** (4): pod-by-pod invites · opening the shared backyard layer · full-clan
invite · the `v1.0` tag.

---

## 6. What the 2026-08-01 readiness audit added

Six independent read-only axes, each re-measured against the tree rather than re-reading this
file. Verdicts: ops **RED**, product **RED**, OSS-artifact **RED**, critic **RED**, security
**YELLOW**, gates **YELLOW**.

> **This audit has no standalone file, and this section is its only record.** `docs/audits/`
> contains exactly one document, `2026-07-26-honest-100-audit.md`. Three places cited "the
> 2026-08-01 readiness audit" as though a reader could open it; they now point here. The
> audit happened — the verdicts above are its output — but it was never written up, which is
> why its findings were re-derived from scratch on 2026-08-06.

### Fixed in PR #118

- **C1 — the decommission runbook destroyed data.** `shutdown.md` documented
  `backup_instance --output …`; `output` is positional, so it exited "unrecognized
  arguments" — one step before `docker compose down -v`. `self-host.md` had the correct
  form all along. Guard added: `test_runbook_commands_are_runnable.py` parses every
  documented invocation with the command's real parser, across every runbook.
- **C3 — restore had never executed against a real Postgres**, anywhere. CI now runs a
  full round trip (seed → back up → delete → restore → assert), verified in the log.
- **C4 — the encrypted pre-flight path had never run in any gate**, and the assertion
  depended on backups staying plaintext.
- Plus **S7** (`cryptography` undeclared), **G8**, **G9**, the plaintext-justifying doc
  drift, an unrunnable restore drill (`tar xf` on ciphertext), and a `scripts`-driven
  verifier that never existed.

### Closed since this section was written

**C2, C5, C6 and C7 all shipped and are listed as open below.** The entries stay as written —
this file is a record, not a status board — but read them with these verdicts:

| | |
|---|---|
| **C2** `v0.1.0` publishes the burned credential | **CLOSED** — re-tagged and withdrawn (#126) |
| **C5** private vulnerability reporting disabled | **CLOSED** — enabled 2026-08-01 |
| **C6** `/settings/digest/` linked from nowhere | **CLOSED** (#120). Its twin `notification_settings` had the identical defect one route over and survived another month — see §7.3 |
| **C7** invite-joined members locked out | **CLOSED** (#121) |

### The criticals, as first written — ALL FOUR NOW CLOSED

**Read the table directly above before this list.** C2, C5, C6 and C7 are closed; the
entries stay verbatim because this file is a record and a backlog that quietly loses its
entries stops being checkable. This heading used to read "Still open — criticals", which put
four closed criticals under a live heading in the document somebody reads first.

- **C2 — `v0.1.0` still publishes the burned credential** in 3 tracked files. The tag
  predates the removal by ten hours and `README.md` tells strangers to clone it, so the
  documented install path is the distribution vector. **Decision taken: re-tag `v0.1.1`
  from clean `main` and delete `v0.1.0`.**
- **C5 — GitHub private vulnerability reporting is disabled** (`{"enabled": false}`) while
  `SECURITY.md` names it the only channel and forbids public issues. One click, founder-only.
- **C6 — `/settings/digest/` is routed but linked from nowhere.** The only notification
  channel cannot be enabled by any member, and because `health_email.admin_recipients()`
  needs a *confirmed* subscription, **the weekly health email very likely sends to nobody** —
  the most plausible reason the plaintext-dump warnings never reached anyone.
- **C7 — invite-joined members can be locked out permanently.** `join.html` collects no
  email, so password reset reports success and sends nothing.

### Newly measured by that audit — where each one stands now

Written 2026-08-01 as a flat "still open" list. Re-measured against the tree on 2026-09-19,
one by one, because a list under that heading is read as current:

- ~~**No scheduled backup exists** (`tasks.py` has six periodics; none backs up).~~ **CLOSED.**
  `scheduled_backup_task` is `@app.periodic(cron="30 3 * * *")` and writes
  `/data/backups/scheduled-YYYY-MM-DD.bak`, encrypted or not at all. It fails loudly in three
  places at once: the weekly health email, `/healthz` answering `degraded`, and the worker log.
- ~~**The monitor lives inside the monitored thing**: only `postgres` has a healthcheck.~~
  **CLOSED.** All four services carry one (`grep -c 'healthcheck:' docker-compose.yml` → 4),
  and the monitor that matters is outside the box entirely:
  `.github/workflows/monitor.yml` asks `/healthz` and the certificate's days-remaining every
  30 minutes from GitHub's infrastructure, and opens one issue rather than e-mailing per run.
- **65KB uncompressed on every anonymous page** — the compression half is **CLOSED**
  (`caddy/Caddyfile.prod` now has `encode zstd gzip`); the 26,041 bytes of CSS commentary are
  **still served** and are S25 above, tracked as issue 191.
- **No audit log exists**, and `remove_member(content="delete")` hard-purges photos behind one
  session POST with no reauth, no confirmation and no undo. **Partly addressed:** the removal
  form now asks what happens to their posts and makes you type the name, and `HouseholdChange`
  is the first durable record of an admin act on a member — with the caveat that its `pod` and
  `member` foreign keys are `CASCADE`, so the record dies with its subject (issue 181, item 1).
  There is still no general audit log.
- ~~**The privacy note never reaches the family**: `family-privacy-note.md` is referenced by
  zero files under `src/`.~~ **CLOSED.** The promises are in the product: the "How this works"
  page carries them in words, reachable from Settings, from the sign-in page and from the
  welcome, and `src/core/tests/test_plain_pages.py` fails if the page and the note stop
  agreeing.
- ~~**AGPL §13 source-offer unsatisfied**~~ **CLOSED** — the "About this Backyard" page carries
  the licence and the source offer, guarded by `src/core/tests/test_agpl_source_offer.py`.

### Ordering error in §0 above — spent

§0 ranked **operator action #4 (register the Resend webhook)** as a launch prerequisite, and
this section correctly objected that a reply-by-email is a reply *to a digest* while nobody
could subscribe to one. **C6 is closed**, so the objection is spent — and #4 itself is done.
The deeper answer arrived later and from the other direction: since #101 the digest publishes
no reply address at all, so the inbound route is a live capability nothing currently hands
anybody the key to.

---

## Suggested order — as of 2026-09-19

The first three steps of the original order are done. What it now reads as:

1. ~~Operator actions 1–4~~ · ~~S1–S7~~ · ~~G1–G2~~ — all closed; see §0, §2 and §3.
2. **S25** (issue 191), the 26KB of developer commentary on every anonymous page. One
   change, every visitor, and the only item in this file that is both open and touches what
   a stranger receives.
3. **The founder's QA walk** ([`runbooks/founder-qa.md`](runbooks/founder-qa.md)), which is
   and has always been the gate, and the S-721 delegate rehearsal beside it (issue 194) — a
   second person walking [`runbooks/setting-up-your-side.md`](runbooks/setting-up-your-side.md)
   cold, because the founder must not role-play the delegate.
4. The filed follow-ups, in the tracker rather than here: 176, 180, 181, 182, 187, 188,
   and the hygiene pair 192 (S27) and 193 (the rest of S29).
5. Founder decisions, then S-603 or not.
6. The long tail — S8–S24 and the gate entries still open after this pass, G3, G4 and G5 —
   recorded above and carried as one unscheduled item, issue 195.

Phase 5 and 6 stay where they are: gated on the founder's QA walk and the decision to go public.

---

## 7. The 2026-08-06 session: what was found, fixed, and left

Written at the end of the session rather than after it, because §6's findings lived only in
a chat log for a week and four of them were still listed "Still open" here after they had
shipped. Everything below carries a verdict and the evidence for it.

**Corrections to §6, which was stale:** C2 (re-tag) closed by #126 · C5 (private
vulnerability reporting) enabled 2026-08-01 · C6 (`/settings/digest/` unreachable) closed by
#120 · C7 (invite-joined lockout) closed by #121.

### 7.1 Production — both live exposures closed and verified from outside

| | |
|---|---|
| **A relative carried the author's real surname on the public instance.** `b8b9813` renamed her in the repo and added a guard; **the data was never migrated.** | Fixed after an encrypted backup (`pre-privacy-fix-2026-08-07-0009.bak`). Swept posts, comments, pods, yards and kinship names — only the author's own row remains, which the guard allows. Verified by signing in over the public internet and reading `/directory/`. |
| **The `worker` container ran 7-day-old code.** Images were genuinely different: web `6cc6b523` (08-06) vs worker `0e61b7f3` (07-30), so digests, transcoding, link previews, `rollup_metrics` and `clearsessions` were all stale. The deploy step restarts `web` only. | Rebuilt. Both now carry the identical build stamp `2026-08-06T02:30:07.298Z`. |
| **6 orphaned media files** — `rows=4 referenced=8 on_disk=14`, including a video source+transcode pair with no row. Nothing in the product would ever remove them: every purge path needs the row. | Unlinked. Now `on_disk=8`, exact match, `REFERENCED BUT MISSING: 0`. All 8 `/media/` URLs still return 200 with real bytes. |

Deliberately left on the box, because founder QA needs them and they go with the demo family:
the 2 `ISOPROBE` posts, Rose Whitfield's elder token, 35 sessions (0 expired).

**Operational facts worth writing down.** The server key is stored as a **document**, not an
SSH Key item, so the 1Password SSH agent never serves it — fetch with `op document get`. The
user is `ubuntu`, not `root`. The box has **no `.git`**: it was deployed by file copy, so
`git pull` is not the upgrade path there.

### 7.2 The launch-day landmine

`BACKYARD_DEMO_WIPE=1` ran `Pod.objects.all().delete()` — unscoped — and was documented in
four places as the step to run immediately before the first real invite. Measured against a
database holding one real family beside the fixture one:

```
pods 2->0   members 4->0   posts 2->0   comments 2->0   memberships 4->0
real member survives: False        real ELDER survives: False
```

Members reached **zero**, not one: `exclude(user__username="james")` is keyed to a string
literal and the superuser was not called that. `exclude()` across a nullable relation also
keeps NULL rows, so every elder and supervised child was in the delete set by construction.
Line 54 deleted auth accounts by **first name**.

Replaced by `seeded_by` markers and `manage.py wipe_demo_data` (#134). Three further defects
found by adversarial review of that fix, each verified before being fixed:

- **The refusal checked the three marked models while the deletion travelled through four
  others.** `Post.pod`, `Comment.post`, `Reaction.post`, `MediaAsset.post` carry no marker
  and were never inspected, so the check could not fire. *(`Reaction` was deliberately
  taken back OFF the refusing set on 2026-09-19, walk item 30: a heart is not somebody's
  writing, it has no meaning once the fixture post is gone, and if that post was taken
  down there is no screen left on which its owner could remove it — so it blocked the
  whole wipe with no way out. It is counted in the dry run instead. Post and Comment are
  unchanged.)* A real relative's post, photograph
  and comment inside a fixture pod were deleted with no refusal: `wipe refused? False`.
- **One removed member blocked every future wipe, permanently.** `set() <= doomed_pods` is
  `True`, and `removal.remove_member` keeps the Member row by design.
- **Stranding was checked on pods but not yards.** A real household in a demo yard came out
  attached to nothing: `member_yard_ids() == set()`, and it could not see itself.

### 7.3 Built, shipped, unreachable

Removing one nav link makes **15 routes** unreachable — the entire delegation surface. Fixed
in #135, with the 1-hop hand-maintained check replaced by a link crawl.

Found by that crawl, and by nothing before it: `member_digests` and `member_metrics` had
**zero** `{% url %}` references anywhere; `member_quarantine` and `managed_profile_edit` had
one, their own; `create_supervised` is POST-only with no form anywhere, so **a supervised
child account could not be created from any screen, by anybody** — S-703 reads `passing`.
And the product had **no sign-out link at all**.

`notification_settings` was C6 verbatim, one route over, a month later — while
`profile_edit.html` carried a comment explaining that exact bug two lines above the fix.

### 7.4 Claims the product made that were not true

- **`pod_owner` grants nothing.** No predicate reads it. Both affirmative halves of its
  shipped description were false, and `permission-matrix.md`'s ladder used a strict `<`
  where `member = pod_owner` holds. The drift guard checked only the sentence's *negative*
  clause. (#136)
- **The bridging household could not be created in the product** — the diagram the README
  leads with, captioned "yours, probably". Every call site did `pod.yards.set([one])`; the
  only multi-yard assignment in the tree was a seed script; Django admin is not mounted. It
  took a shell. ~15 tests exercise bridging behaviour and every one built the bridge by
  direct ORM call. (#136)
- **The delegate runbook described a nav that did not exist** — no URL anywhere, no sign-in
  step, no statement that the reader must be promoted first (they get a bare 403). Its own
  promise, *"if a step is not here, you do not have to do it"*, was false for every step.
- **An elder cannot reply by email**, though `README.md:66` and `docs/README.md:70` said she
  can: she has `user=None` by design and digest enrolment is `@login_required` and self-only.
  ~~**Still open.**~~ **CLOSED 2026-09-19 in the docs-truth pass** — `README.md` was corrected
  at the time and `docs/README.md`'s elder diagram was the half that was missed for six weeks.
  It now says replying to the family email opens the app at the thread, with the reason under
  the diagram. Nobody replies by email today, elder or not: #101 removed the reply address
  from the digest body because it is a bearer credential.

### 7.5 The elder path (#137)

On **day 14** her page died and blamed her link. `SESSION_COOKIE_AGE` defaults to two weeks
and is not extended by a request that does not modify the session — which the elder feed
never did. Her token has `expires_at = None` and never expires; only the cookie ran out, and
the shared 404 says *"the link may have expired or been revoked"*.

Fixed at the cause, not the message: that 404 is byte-identical for unknown/revoked/expired
by design (S-202), so explaining itself would leak which. Also: sending love threw her to the
top of the page; reactions showed legal names where every other line prefers the kinship
name; the AGPL offer had **no CSS rule at all** and rendered at the same size as her
grandchildren's news.

### 7.6 Forms that discarded what a person had just done (#139)

The join form cleared all four fields on any error — the first thing a relative ever does,
on a phone. The composer kept the photos, dropped the words, and said the photos were safe.
The digest could be turned on and never off from the web, so an unconfirmed subscriber could
not turn it off at all.

### 7.7 The gates — the theme of the day

Nearly every defect above was found *behind a passing check*. Five shapes:

| shape | live example |
|---|---|
| substring standing in for a structural property | `assert "secret_key" in line` passed on a command with an unclosed quote |
| denominator measuring the wrong quantity | the version gate counted references *before* the exemption that emptied it |
| silent drop instead of fail | `_split()` returned `None` → `continue` → the command left the corpus |
| hardcoded enumeration presented as a rule | 3 reachable URL names guarded, of 62 routes |
| defined-and-unused / one-directional | `_CONTAINER_EXEC` compiled and never referenced |

Two gates were **vacuous at the moment they were measured**:
`test_documented_version_resolves.py` had `ACTUALLY_CHECKED = []` for all four guarded
documents, and `test_self_host_docs.py` skips 2 of its 3 commands.

**Four of the guards written this session were vacuous on first write** and were caught by
breaking them: the runbook-label check matched by substring; the wipe's marker accepted `""`
(which selects exactly and only real data); the version denominator counted the wrong set;
the reachability exclusion list named a route that does not exist.

**The `secrets` job scans every branch.** `actions/checkout` uses `fetch-depth: 0`, so
`gitleaks git .` walks the whole commit graph: one credential-shaped literal on a single
unmerged branch fails `secrets` on **every open PR at once**, including ones that did not
change. Measured: 171 commits, one finding, on an unmerged branch. `make secrets` now
reproduces this locally.

### 7.8 Closed since this section was written

Every gate escape listed here has been closed and **proven by breaking what it guards** —
the fix is not recorded until the guard has been seen to fail. Merged to `main`:

| was | closed by | what the probe showed |
|---|---|---|
| `test_self_host_docs.py` skip-inversion (2 of 3 skipped) | #144 | the skips are gone; only prose describing them remains |
| **nothing reads `ci.yml`** | #144 | deleting the bandit scan left 11 mentions of "bandit" and the old rule green |
| `test_staged_upload_limits.py` `.split()` widening | #145 | `rindex` did not raise — it validated the `clearsessions` task's cron, 8 lines up |
| `test_metrics.py` two divergent `banned` tuples | #145 | collapsed to one constant |
| `test_health_email.py` 5 hardcoded modules of 13 | #146 | a mistyped glob found 10 of 11 and still passed the `>= 8` floor, dropping `views.py` |
| `test_agpl_source_offer.py` coverage | #146 | standalone pages computed, each template read once |
| crawl counts an `href`, never a status | #147 | `Elder link` visible to a yard admin, 403 on click |
| crawl runs as instance admin, runbook addresses a yard admin | #147 | only `[yard_admin]` goes red; `[instance_admin]` stays green |
| roster links render for cross-yard rows that 404 | #147 | the roster gated on `manageable`, the view on `can_provision_token` |
| `preview()` undercounts fast-deletes | #148 | worse than reported — see below |
| `preview`/`wipe` collect outside the transaction | #148 | closure now computed under `select_for_update` inside the atomic block |
| the seed creates a `james` superuser with the demo password | #148 | selected by `is_superuser` now; a populated instance with no superuser is refused |

**One was corrected downward.** `check_digest_confinement.py` guarding a single file was
recorded here as too narrow. Measured: widening it false-positives on three modules that
legitimately import digest names. The one-file scope is right, and the entry was wrong.

**One turned out worse than recorded.** "`preview()` undercounts fast-deletes" was filed as
a reporting mismatch. `Collector` splits deletion into rows it instantiates and rows it
removes in bulk, and only the first appear in `.data` — so the refusal that had just been
written to stop a real person's content being destroyed was **blind to `Reaction`,
`PodMembership`, `PodMute`, `LinkPreview`, `ReplyAddress`, `PodWeekMetrics` and both m2m
through-tables**. `Reaction` was named in the tuple that check iterates and could never
match. Measured, with the relative safely in their own household so nothing else could fire:

```
real person's reactions before: 1
preview() returned, NO refusal: {Yard: 1, Pod: 1, Post: 1, Member: 1}
Reaction counted in preview: False
wipe() receipt: {core.Reaction: 1, ...}
real person's reactions AFTER: 0
```

The dry run did not mention it, the guard could not see it, and the receipt afterwards listed
the row it had just destroyed.

### 7.9 In flight

| item | PR |
|---|---|
| `test_isolation_registry.py` passes on classification, not coverage | #151 |
| `test_no_hardcoded_demo_credentials.py` drift check is one-directional | #151 |
| `create_supervised` never checks the parent belongs to the chosen pod | #149 |
| a parent cannot create their own child's account | #149 |
| `self-host.md` pins a version and is not in `_READER_FACING` | #150 |
| `_release_in_flight` cannot tell "not tagged yet" from "tag withdrawn" | #150 |

### 7.10 Closed since 7.9 was written

Everything §7.10 listed as open has landed or is in flight. Recorded here rather than deleted,
because a backlog that quietly loses its entries stops being checkable — which is the note §6
of this file already carries about itself.

| was | closed by | what the measurement was |
|---|---|---|
| a nulled ad-hoc `Pod.owner` is unrecoverable | #153 | worse than filed: a DEPARTED owner also kept control of a pod they left, and S-702 removal was a third route nobody had wired |
| `docs/README.md` lists a "search" surface | #154 | there is no post search anywhere in the product |
| `revocation.py` calls three shipped classes "known future classes" | #154 | all three are in `_REVOCATION_STEPS` and shipped months ago |
| `backup-restore.md` never says what a restore does to live credentials | #154 | it now carries the table, including the row that matters: members removed since the backup COME BACK |
| S-721 is not in `stories.yaml` | #154 | the cross-reference check found six more — S-722..S-727 — cited by `PATH-TO-100` and never filed |
| 85 of 154 commits unsigned while CONTRIBUTING says every commit must be | #158 | enforced on the commits a PR adds; history is stated rather than silently contradicted |
| `RESUME-HERE.md` contradicts itself on the exposures | earlier | the header now narrates the contradiction as a past lesson rather than repeating it |
| three files cite a readiness audit that has no file | earlier | citations repointed at §6, which is its only record |

**Nothing from the original §7 audit is open.** What remains is §7.11 below, found while
closing it — and the founder-gated items in §6 that no amount of code closes: CodeQL, the
retention window, PRIV-1, and the QA walk itself.

### 7.11 New, found while closing the above

These were not in any audit. Each came from breaking a guard rather than reading it.

* **`uv run pytest` is a strict PREFIX of `uv run pytest -m e2e -v`.** No substring
  distinguishes them, so the entire unit suite could have been deleted from `ci.yml` with the
  meta-gate green. Found by the new uniqueness rule, not by review.
* **A parent could not create their own child's account.** `can_create_supervised` returns
  `True` for `actor.pk == parent.pk` and always has; the only control lived on `/members/`,
  which is admin-only. The permission said yes, the page said 403, and a hand-written POST
  worked.
* **A child could be placed in a household their parent is not in.** The view checked that
  the pod was visible to whoever *submitted* the form — for an instance admin, every pod on
  the instance.
* **`member.pods` includes ad-hoc groups** under controls captioned "households" — the same
  mislabel fixed once on this roster, reintroduced by a new field weeks later.
* **`test_no_relative_carries_the_authors_real_surname` asserted a floor, not a ceiling.**
  `== ["James Shehan"]` made the author's real surname *required* in the seed; removing it
  failed the test for having leaked less.
* **The merge train read a queued CI check as a verdict.** `gh` reports an in-progress check
  as the empty string, and jq's `//` defaults only on `null`, so `"" // "RUNNING"` is `""`.
  It announced "all five green" with `code` still running. The same falsy-but-not-null slip
  the codebase keeps producing, in the tooling built to land the fixes for it.

