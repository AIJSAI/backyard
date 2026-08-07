# Outstanding — the security-pass backlog, plus what a readiness audit added

> **Read this first.** This file was written 2026-07-30 and titled "the single list". It was
> not one. It is an accurate **security-pass** backlog, and reading it as a *complete* one is
> what left backups, monitoring, audit logging and the product's only notification channel
> invisible. A six-axis readiness audit on 2026-08-01 found roughly thirty items it did not
> contain, seven of them critical — see [§6](#6-what-the-2026-08-01-readiness-audit-added).
>
> Three of those criticals are fixed (PR #118), and **both live production exposures are
> closed** (§0). The rest are open.

Everything not done, ranked, with who owns it.

**Read this, then verify with a primary check** (`git log`, `gh pr list`, run the probe named
in the item) rather than trusting the state below. Items are marked with the audit finding
they came from so you can go back to the source.

State on 2026-08-01: `main` = `162c620` (#118 merged) · **811 passing / 2 skipped** ·
46 stories passing, 2 superseded, **1 spec** · PATH-TO-100 30 checked / 15 open.

---

## 0. Operator actions — 1–3 DONE 2026-08-01 (CDT) / 2026-08-02 (UTC), one left

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
| 4 | **Register the Resend inbound webhook** | **STILL OPEN**, and see the ordering note below: it buys nothing until **C6** is fixed, because a reply-by-email is a reply *to a digest* and no member can enable the digest yet. |

**No plaintext copy of the family database now exists anywhere** — on the volume, in `/tmp`,
or off-box. That was the single worst standing exposure.

Note for the future: an agent session *can* do these after all, over SSH with the key at
`~/.ssh/backyard_vm`. The classifier refusal applies to a local `docker compose exec`, not to
`ssh … 'docker compose exec …'`. What actually gated this was founder authorisation, which is
the right gate.

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
- **S28** — **DONE 2026-08-01.** The demo relative carrying the author's real surname is now `Priya Whitfield`, matching the fictional family the design tooling already used. It had also reached a shipping `posting.py` comment and two receipts, and the README carried a blanket "no real family content" claim that was false a few files away — both corrected. Guarded by `src/core/tests/test_privacy_line_holds.py`.
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
  and were never inspected, so the check could not fire. A real relative's post, photograph
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
- **An elder cannot reply by email**, though `README.md:66` and `docs/README.md:70` say she
  can: she has `user=None` by design and digest enrolment is `@login_required` and self-only.
  **Still open.**

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

### 7.8 Still open

**Gates with an escape still open** — `test_self_host_docs.py` skip-inversion (2 of 3 skip
today) · `test_staged_upload_limits.py` `.split()` widening to the whole module on a rename ·
`test_metrics.py` two divergent `banned` tuples, the app-wide one weaker ·
`check_digest_confinement.py` guards one file of 60+ · `test_isolation_registry.py` passes
on classification, not coverage · `test_health_email.py` 5 hardcoded view modules of 13 ·
`test_no_hardcoded_demo_credentials.py` drift check is one-directional ·
`test_agpl_source_offer.py` substring over two named templates · **nothing reads `ci.yml`**,
so deleting a step leaves the job context green.

**From adversarial review, verified but not yet fixed** — the reachability crawl counts an
`href` and never a status code, so a link that 403s reads as reachable (live instance:
`Elder link` renders on `can_manage_member` but the view gates on the narrower
`can_provision_token`) · that crawl runs as an instance admin while the runbook it validates
addresses a **yard** admin, so "Members → Edit profile" is certified for a reader it is
false for · `preview()` undercounts fast-deletes, so the dry run and the receipt disagree ·
`preview`/`wipe` collect twice, outside the transaction · `SET_NULL` effects are invisible,
and a nulled ad-hoc `Pod.owner` is **unrecoverable** — no reassignment path exists ·
`create_supervised` never checks the parent belongs to the chosen pod · the roster's new
links render for cross-yard rows that then 404 · a parent still cannot create their own
child's account (the form is gated on `manageable`, which is `False` for self) ·
`self-host.md` pins a version and is not in `_READER_FACING` · `_release_in_flight` cannot
tell "not tagged yet" from "tag withdrawn", which is the exact `v0.1.0` case the file exists
for · the seed creates a `james` superuser with the demo password on any instance that does
not already have one.

**Product and docs** — three files cited the 2026-08-01 readiness audit as though it were a
document; it has no file, and §6 is its only record (now said there, and the citations
repointed) ·
`docs/README.md:47` lists a "search" surface the product does not have · `RESUME-HERE.md`
contradicts itself on whether the exposures are closed · `backup-restore.md` never uses the
word "replay", though a restore bumps every `token_generation` instance-wide · `revocation.py`
still calls three shipped credential classes "known future classes" · **85 of 136 commits are
unsigned** while `CONTRIBUTING.md` says every commit must be signed off · S-721 (the
non-technical delegate rehearsal) is still not in `stories/stories.yaml`.
