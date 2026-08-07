# Changelog

Notable changes, newest first. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [semantic versioning](https://semver.org/), and `0.x` means no stability
promise yet — the schema and the URLs may still move.

**Install a tag, not `main`.** `main` is where the work happens and it changes daily; a tag is
a point somebody deliberately stopped at, with a full green gate behind it.

## [0.1.2] — 2026-08-06

`v0.1.1` shipped before a week of edge and documentation fixes and could not be installed
from its own README. Install this one.

### Fixed

- **The documented install failed on its third command.** `.env.example` named three
  variables; the production overlay refuses to start without five. A stranger who ran the
  README verbatim got `set BACKYARD_DOMAIN in .env` and no instance. `BACKYARD_DOMAIN` and
  `ACME_EMAIL` are now in the file, with what each is for.
- **The printed emergency recovery card could not be pasted.** Its restore command opened
  `sh -c '` and never closed it — on the one page someone reads when the instance is
  already gone.
- **Seven documented container commands died before they started.** `docker compose exec`
  gets the container's configured environment, which has never held `DJANGO_SECRET_KEY`, so
  every documented `manage.py` invocation that did not read it from `/data/secret_key`
  exited on the boot guard.

### Security

- Seven things the live edge handed an unauthenticated stranger: a fallback response that
  skipped every security header while advertising the server, the static build manifest,
  `Via: 1.1 Caddy` re-announcing what `-Server` had just removed, and no compression on any
  response — worst on the elder page, the surface most likely to be read over a slow phone.
- `WHITENOISE_ALLOW_ALL_ORIGINS` off; slowloris timeouts and a hard request-body ceiling at
  the edge; an RFC 9116 `security.txt` served from Caddy so it stays reachable when the app
  is down.
- SPF, DMARC and CAA records, whose absence is only visible once abused.
- `cryptography` moved off a version with a published CVE that this repo's own upper pin
  had been blocking.

### Changed

- Three gates that could not fail were rewritten to fail: the runbook command check (a
  substring standing in for "this command runs"), the documented-version check (which was
  exempting every reference it was meant to compare), and the `.env.example` check (which
  guarded a hand-maintained list nobody had added the two new variables to).

## [0.1.1] — 2026-08-05

Everything here is a correction, not a feature. `v0.1.0` is **withdrawn**: install this one.

### Security

- **A bridging post leaked the other side of the family, photographs included.** The audience
  query filtered comments and reactions by *post* visibility alone, so on a post addressed to
  both sides a single-yard member received the other side's replies and the images attached to
  them. Fixed inside the one audience query. This is the defect that makes `v0.1.0` withdrawn
  rather than merely superseded.
- **A yard admin could mint a credential wider than their own reach** — an elder link for a
  member of a pod they were not in.
- **`DEBUG` could boot on a public host**, and setting it disabled the guard meant to prevent
  exactly that.
- **Pre-flight database dumps are encrypted** when a backup passphrase is set. They were
  written in plaintext on every container start, three deep.
- **`cryptography` is a declared dependency and pinned past `PYSEC-2026-3552`.** The backup
  guarantee previously rested on a transitive dependency of an MFA extra.
- Log redaction now covers the password-reset key; Pillow's format allowlist runs *before* the
  decode; ffmpeg no longer inherits the environment; a malformed multipart message is rejected
  instead of becoming a 500 and a provider retry loop.

### Fixed

- **The digest could not be switched on by anybody.** `/settings/digest/` was routed and
  linked from nowhere, so the only notification channel the product has was unreachable — and
  the weekly health email, which needs a confirmed subscription, was reaching nobody.
- **An invite-joined member had no way back in.** The join form collected no address, so
  password reset had nothing to send to and said "check your inbox" regardless.
- **The decommission runbook destroyed data.** It documented a flag the command does not
  accept, one step before `docker compose down -v`.
- The restore drill could not run — it untarred an archive that is encrypted by default.

### Changed

- Backup and restore are exercised end to end in CI against a real Postgres, not stubs.
- The demo family is fully invented; no real relative's name appears.
- Fonts ship with their licence text (SIL OFL 1.1).

[0.1.2]: https://github.com/AIJSAI/backyard/tree/v0.1.2
[0.1.1]: https://github.com/AIJSAI/backyard/tree/v0.1.1

## 0.1.0 — 2026-07-29 (withdrawn)

The first fixed point. **Pre-release: it runs, and it has not been handed to a family yet.**
The author's own QA walk ([`docs/runbooks/founder-qa.md`](docs/runbooks/founder-qa.md)) is the
gate, and it has not happened. Treat this as "reproducible enough to read and try", not
"trusted with your family's photographs".

### What works

- **Pods and yards.** Every household is a pod; each side of the family is a yard with its own
  shared feed. A household can belong to both sides without fusing them, and cross-yard access
  answers a byte-identical 404 — no existence signal.
- **A feed that ends.** Chronological, no algorithm, no engagement mechanics. Links, photos,
  video, short updates, comments, one reaction.
- **The elder path.** One link, no account, no app store. Large single-column type with a
  bigger-text toggle. Photos and video are reachable through it.
- **Photos and video.** Client-side resize, server-side re-encode, metadata stripped at ingest,
  every byte served through one access-checked path. Photos and clips work on replies too, so a
  wedding is one thread rather than a scatter of posts.
- **Email digest, out and in.** A weekly per-yard digest built through the same audience query
  as the web feed. Replying to a digest opens the app at the thread.
- **Installable PWA** on iOS and Android, no store.
- **The family directory.** Profiles with per-field visibility (nobody / my pods / my yards),
  birthdays as month-and-day with no year and no age ever, and vCard download so the numbers in
  your phone stop being stale.
- **Admin that a non-technical person can hold.** Five documented roles with the permissions
  written beside the control, household invites, member removal that asks what happens to their
  posts, single-item takedown, break-glass recovery.
- **Export.** Every member can download everything they authored, always, ungated.
- **Encrypted backups** with a restore that ends in a forced security replay, so a restore
  never resurrects a removed member's credentials.
- **A weekly health email** reporting last-backup age, disk headroom and domain days-remaining
  — and reporting `NOT MEASURED` for the two it genuinely cannot see, rather than omitting them.
- **Handover and shutdown runbooks**, with a `decommission_instance` command that exports for at
  least two named people *before* it revokes anything.
- **Accessibility.** WCAG 2.1 AA and 2.2 AA across 34 surfaces, verified with axe in a real
  browser at desktop and mobile, light and dark, including a deliberate hover pass. Forced-colors
  and `prefers-contrast` supported.

### What does not work yet

- **Reply-by-email needs one manual step.** Until the inbound webhook is registered with the
  mail provider, a reply is accepted with a `250` and silently goes nowhere. See
  [`self-host.md`](docs/runbooks/self-host.md).
- **The ambient photo-frame display (S-603) is not built.** It is the one unbuilt story.
- **Push notifications are out of scope** for 0.x, by decision — the digest is the notification.
- **No published container images.** You build from source with `docker compose`.
- **One instance has ever been deployed**, by the author. Hardware beyond a 2-vCPU Ubicloud VM
  is untested, and no NAS platform has been tried.
- **No independent security review.** The threat model is thorough and entirely self-authored.

### Security

- Credential literals removed from the seed and capture tooling. `scripts/demo_seed.py` carried
  a fixed password that **worked on the live instance**, in a public repository; it is now
  generated per run and printed once. Two more copies of the same mistake, hidden in
  `os.environ.get(KEY, "literal")` fallbacks, went with it. gitleaks had reported the history
  clean and was right by its own rules — it matches provider-shaped keys, not the password a
  person picks — so the enforcing check is now an `ast` guard,
  `src/core/tests/test_no_hardcoded_demo_credentials.py`.
- Baseline Content-Security-Policy with a nonce for the few inline scripts; `script-src` is not
  `unsafe-inline`.
- Every bearer credential is at least 128-bit CSPRNG, stored only as a hash, and anchored to a
  per-member generation so one revocation kills every derived credential on its next use.
- Dependency CVE scanning, SAST and secret scanning run on every push.

<!-- Points at the tag's tree rather than a Releases page: a bare annotated tag always renders
     here, whereas /releases/tag/ depends on a Release object existing, and publishing GHCR
     images and formal releases is still Phase 5 work. -->
<!-- 0.1.0 deliberately has NO link. The tag was deleted when the release was withdrawn, so
     /tree/v0.1.0 404s -- and repointing it at the commit the tag named would hand a reader a
     working path to the tree the withdrawal exists to take away, burned credential and
     cross-yard disclosure included. The notes below stay as history; the way in does not. -->
