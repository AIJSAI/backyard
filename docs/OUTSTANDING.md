# Outstanding — the security-pass backlog, plus what a readiness audit added

> **Read this first.** This file was written 2026-07-30 and titled "the single list". It was
> not one. It is an accurate **security-pass** backlog, and reading it as a *complete* one is
> what left backups, monitoring, audit logging and the product's only notification channel
> invisible. A six-axis readiness audit on 2026-08-01 found roughly thirty items it did not
> contain, seven of them critical — see [§6](#6-what-the-2026-08-01-readiness-audit-added).
>
> Two of those criticals are now fixed (PR #118). The rest are open.

Everything not done, ranked, with who owns it.

**Read this, then verify with a primary check** (`git log`, `gh pr list`, run the probe named
in the item) rather than trusting the state below. Items are marked with the audit finding
they came from so you can go back to the source.

State on 2026-08-01: `main` = `bb54411` · **811 passing / 2 skipped** on PR #118 ·
46 stories passing, 2 superseded, **1 spec** · PATH-TO-100 30 checked / 15 open.

---

## 0. Do these first — a person has to, on the box

An agent session cannot do these: the command classifier refuses
`docker compose exec … manage.py shell`. The commands are in
[`RESUME-HERE.md`](RESUME-HERE.md) under "Operator actions waiting".

| # | Action | Why it is first |
|---|---|---|
| 1 | **Rotate the demo accounts** | The leaked password **still authenticated on production** at the end of the security pass. Re-tested repeatedly; it is live. |
| 2 | **Set `BACKYARD_BACKUP_PASSPHRASE`** | Production is writing **plaintext dumps of the entire family database on every boot** — three on the volume. The instance warns about it on every start. **Do this only on a tree that includes PR #118**: before it, CI asserted the *plaintext* pre-flight filename, so setting the passphrase would have turned the gate red. |
| 3 | **Take a backup** | Production has never had one, so restore has never been exercised against real data either. |
| 4 | **Register the Resend inbound webhook** | Until then a reply-by-email is accepted with a `250` and **silently goes nowhere**. |

---

## 1. Decisions only the founder can make

Nothing below moves until these are answered.

**Enforce admin 2FA (T-ADMIN-1).** The threat model claims *"passkey or TOTP, enforced in the
wizard so a password-only admin never exists."* Nothing enforces it — a password-only
superuser reaches every admin surface. Left open deliberately: enabling it can lock the only
admin out, and `breakglass.py` already assumes the control exists. The safe order is
**enrol, then enforce**. That is a rollout call, not a patch.

**S-603 — build the ambient photo frame, or cut it?** The last `spec` story. If built it
needs a threat-model entry *before* code (new always-on bearer credential on a device in a
room); a five-row `T-DISPLAY-*` draft is at
[`security/s603-display-threat-draft.md`](security/s603-display-threat-draft.md).

**S-603 carries its own contradiction.** `metrics.md:9` defines active as *"any **deliberate**
touch"*; `metrics.md:21` counts a **frame heartbeat** toward the elder touch rate. A heartbeat
is a powered-on tablet. Wire it in and the one signal that would show an elder has gone quiet
reads "active" as long as her frame has electricity. **Recommendation: keep the heartbeat,
name it separately, keep it out of `touched`** — that is the reversible direction.

**Founder QA walk** ([`runbooks/founder-qa.md`](runbooks/founder-qa.md)) — ~90 minutes, and
always the gate before anything is shared. Wipe the demo family first (`BACKYARD_DEMO_WIPE=1`).

---

## 2. Security findings not yet fixed

From the 2026-07-30 five-angle fan-out. Everything CRITICAL and HIGH was fixed in #108–#113;
these are what remains. Each was **re-confirmed still present on 2026-07-30** before being
written here.

### Worth doing next

| # | Finding | Where |
|---|---|---|
| S1 | **Anymail's inbound fetch has no `timeout=` and no size cap.** Three `requests.get` calls with neither, inside the webhook's own request cycle — so a slow provider pins a gunicorn worker indefinitely, and the size cap in our code applies only *after* the whole message is downloaded and parsed. Fix by enqueueing the fetch on the worker with a bounded, timed read. | `anymail/webhooks/resend.py:277,287,331` (upstream — needs a subclass) |
| S2 | **No rate limiting on any unauthenticated bearer surface.** `/t/`, `/d/`, `/media/`, `/join/`, `/break-glass/` — all hit the DB, none throttled, and each 404 now renders the ~26KB branded page. Token entropy is 256-bit so this is availability, not guessing. `middleware.py` names the gap itself. | `elder_views.py`, `digest_views.py`, `media_views.py` — confirmed 0 rate-limit calls |
| S3 | **Control characters are not stripped from post bodies or display names.** The inbound path strips; the web composer and profile editor do not, and `digest.txt` renders with `autoescape off`. A bidi override or ANSI escape in a name reaches the plaintext digest verbatim; a `\x00` is a 500. | `posting.py`, `commenting.py` — confirmed 0 `strip_control` calls |
| S4 | **The webhook route is mounted unconditionally**, and the secret is only required when the Resend *send* backend is active. On the documented SMTP config, every unauthenticated POST is an unhandled 500. Fail-closed today only by an upstream library rejecting an empty secret. | `config/urls.py`, `config/email_guard.py` |
| S5 | **`_trusted_recipient` falls back to a sender-controlled `To:` header** when the transport supplies no envelope recipient, and takes `[0]` of a multi-recipient list. Converts TM-4's "the address IS the credential" into "a header is the credential". Should fail closed. | `inbound_webhook.py:40-54` |
| S6 | **Supply chain**: CI actions pinned to mutable tags (`actions/checkout@v4`, `setup-python@v5`, `setup-uv@v5`) not SHAs; Dockerfile base images float on tags while compose digest-pins; `uvx bandit`/`pip-audit` unpinned beside a checksum-verified gitleaks; no container/OS image scan; dependabot disabled. | `.github/workflows/`, `Dockerfile` — confirmed |
| S7 | **`cryptography` is undeclared.** The primitive the entire backup guarantee rests on arrives only via `django-allauth[mfa]` → `fido2`. The day that extra changes, encrypted backup breaks at import. | `pyproject.toml` — confirmed absent |

### Smaller, still real

- **S8** — `profiles._can_see_field` returns `True` for YARD unconditionally; every current caller pre-scopes, so no live route, but one future caller reintroduces T-YARD-6.
- **S9** — Voluntary leave does not fire the revocation handler, and pod-leaves-yard has no implementation at all, though TM-1 names both.
- **S10** — Break-glass keys on `is_superuser`, so a *promoted* instance admin (the S-707 succession path) has no recovery path.
- **S11** — `notify_reply` rotates the unsubscribe token on every nudge, invalidating the link in the digest already in her mailbox.
- **S12** — `create_supervised` places the child in the **actor's** pod, not the named parent's.
- **S13** — The bigint-cursor guard exists in one id parser and is missing from the others (`handover.int_or_404`, `pod_views._int`, `breakglass._resolve_admin`) → 500 on a 21-digit id.
- **S14** — `can_assign_role` would permit `SUPERVISED`; unreachable today only because the view allowlists first.
- **S15** — Session lifetime is a fixed 2-week window with no absolute cap or rotation on privilege change (TS-DJ-1 residual, disclosed).
- **S16** — `viewers.py` omits the `hasattr(member, "elder_token")` check that `elder_views.py` applies to the same session.
- **S17** — `transcoding.py` logs ffmpeg stderr containing the media token, on a logger not attached to the redaction filter.
- **S18** — `domain_expiry` follows a third-party redirect with an https check but **no private-range rejection**, unlike `link_preview`. Two outbound fetchers should share one validator.
- **S19** — Staging disk budget is per-session with no instance-wide cap, on the volume holding `/data/secret_key`.
- **S20** — Restore trusts an unauthenticated plaintext archive when no passphrase is configured; no extraction size cap.
- **S21** — `export.py` reads a whole video into memory; `/settings/export/` has no rate limit.
- **S22** — Icons re-render with Pillow on every request, unauthenticated.
- **S23** — `link_preview` raises an unhandled `ValueError` on a scope-qualified IPv6 from `getaddrinfo`.
- **S24** — `read_only` rootfs still unset (needs `collectstatic` moved to build time); `write` timeout deliberately unset.

### Hygiene / disclosure

- **S25** — **26KB, 40% of every page, is developer CSS commentary** served to unauthenticated visitors, disclosing internal story IDs, founder feedback, and `django-allauth`. Strip comments at render time; do not delete them.
- **S26** — Ubicloud project id and Cloudflare zone id in `runbooks/live-repro.md`; the prod IP was parameterised there but these were not.
- **S27** — Maintainer's real email in `receipts/2026-07-22-wave-4-close.md`. Already public via git author metadata, but the receipt is a distinct disclosure naming it as the live inbox.
- **S28** — **`Priya Shehan` in the demo seed carries the maintainer's real surname.** Every other demo name is invented. If she is a real family member this violates CONTRIBUTING's privacy line. **Only the founder can answer.**
- **S29** — No `/.well-known/security.txt` despite a SECURITY.md and an invitation to self-host. No `Permissions-Policy`, `CORP`, `COEP`.

---

## 3. Gates that still overstate

From the gate audit. These do not break anything today; they mean a future regression goes
unnoticed.

- **G1** — `test_self_host_docs.py` **suppresses itself**: `pytest.skip` when a command is not
  named in the guide, so 2 of 3 cases are vacuous right now (they are the "2 skipped" in every
  gate line this repo quotes). The enumeration is inverted — it should walk commands *named in
  the guide* and assert each resolves. 4 of 9 management commands are outside it entirely.
- **G2** — **Required contexts are job-level.** Deleting a *step* — bandit, a selftest, the
  compose live probe — leaves its context green. No test reads `ci.yml`.
- **G3** — The isolation registry is satisfiable by **classification, not coverage**: adding a
  model to `_ISOLATION_EXEMPT` with any non-empty reason passes. ADR-004 claims "a new model
  **without an isolation fixture** fails the build"; what ships fails on a missing *name*.
- **G4** — ADR-004's promised **repo-wide raw-SQL ban never shipped** — `check_digest_confinement`
  guards exactly one file out of 60+. Two live `connection.cursor()` sites are unpoliced.
- **G5** — `check_stories.py`'s evidence rule is a **substring test**: `evidence: trust me`
  passes. All 91 references do resolve today; nothing enforces it. ~10 lines to add.
- **G6** — `scripts/axe_sweep.py` appears **nowhere in CI**. The accessibility backstop that
  `test_design_system_wcag.py` defers to is a manual sweep.
- **G7** — Caddy's security invariants (`admin off`, no `log`, no global `Referrer-Policy`) are
  enforced by **comments**, not a guard.
- **G8** — `backups.py`'s module docstring says *"the archive is a plain tar … nothing here
  holds a key"*. Encryption is real and default; the docstring is stale, and it is the exact
  sentence a prior audit caught shipping plaintext under.
- **G9** — The backup runbook puts the migrator password on the host command line, in the same
  document that (correctly) says never to do that with the passphrase.
- **G10** — The one-time setup secret is printed to stdout → the Docker json log.

---

## 4. What nobody has verified

Not findings — gaps in evidence. Each needs a person or a real device.

- **No real phone has imported a vCard.** Validated against `vobject`, not iOS Contacts. Same
  for the yearless birthday.
- **No real device has installed the PWA**, and **no elder has held the elder path**. Everything
  about that experience is verified by me driving a browser.
- **The health email has never been seen landing in a real inbox** — only its sender output.
- **Restore has never run against production data** (there is no backup to restore).
- **No independent security review.** The threat model is thorough and entirely self-authored;
  the 2026-07-30 pass was still me, with agents.

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

### Still open — criticals

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

### Still open — newly measured

- **No scheduled backup exists** (`tasks.py` has six periodics; none backs up).
- **The monitor lives inside the monitored thing**: only `postgres` has a healthcheck;
  `web`/`worker`/`caddy` have none, and the health email is a *worker* periodic.
- **65KB uncompressed on every anonymous page** — 26,041 bytes (40.1%) is developer CSS
  commentary, and Caddy has no `encode` directive at all. The elder path is standalone and
  unaffected.
- **No audit log exists** (27 models, none records actions), and
  `remove_member(content="delete")` hard-purges photos behind one session POST with no
  reauth, no confirmation and no undo.
- **The privacy note never reaches the family**: `family-privacy-note.md` is referenced by
  zero files under `src/`, while S-705 sits at `passing`.
- **AGPL §13 source-offer unsatisfied** — no repo URL or licence reference in `src/` or on
  the live page.

### Ordering error in §0 above

§0 ranks **operator action #4 (register the Resend webhook)** as a launch prerequisite. A
reply-by-email is a reply *to a digest*, and nobody can subscribe to a digest — so #4 buys
nothing until **C6** is fixed and belongs after it.

---

## Suggested order

1. **Operator actions 1–4.** Two are live exposures; nothing else matters more.
2. **S1–S7**, the security findings with real reach.
3. **G1–G2**, the two gates that would hide a regression in the checks themselves.
4. **S25**, the 26KB of commentary on every page — one change, every visitor, and it also cuts
   page weight for elders on slow connections.
5. Founder decisions, then S-603 or not.
6. The long tail: S8–S24, G3–G10.

Phase 5 and 6 stay where they are: gated on the founder's QA walk and the decision to go public.
