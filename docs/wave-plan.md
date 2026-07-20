# Phase 2 wave plan

Status: committed 2026-07-20. This is the build order for the 34-story v1 cut in [stories/stories.yaml](../stories/stories.yaml). Five waves, each a vertical slice proven live on the running compose stack before the next begins. The slice order comes from the Phase 2 goal: pods and auth, then feed and links, then media, then the digest in and out, then the PWA and the elder token path.

The tracker stays the single source of truth. This document maps stories to waves and fixes the rules every wave closes under; it never restates acceptance criteria. If a story and this plan disagree, the story wins and this file gets fixed.

## Rules for every wave

These apply to all five waves. Each wave's own section adds only what is specific to it.

1. **Full gate, never subsets.** A wave closes only on ruff + mypy + the full pytest suite + docker build, all green in CI. A passing subset proves nothing and does not count.
2. **Live repro, receipted.** Every wave ends with a documented live walk of that wave's stories on the running compose stack, committed as a receipt in [docs/receipts/](receipts/). What was not exercised live is not done.
3. **The isolation suite only grows.** S-202's test matrix is a merge gate from wave 1 onward. Every wave that adds a readable object type, request class, or surface adds it to the matrix in the same wave. The suite never shrinks.
4. **Security review before merge.** Every wave here touches auth, tokens, media, or email, so every wave gets a security-reviewer pass on its diff before its merge. CRITICAL findings block; HIGH findings are fixed before merge.
5. **Statuses flip honestly.** Stories move from `spec` to `built` to `tested` as waves land. `tested` means the story's acceptance criteria run as tests against a live stack, not that code exists. `passing` with evidence links is Phase 3's loop; no wave claims it.
6. **Measured, never claimed.** ADR-002's carried-forward validation gates are measured in the wave named below. A gate with no measurement stays open and blocks that wave's close.
7. **Founder decisions batch at wave boundaries.** Open product questions accumulate during a wave and land as one batched review at its close, the same way the [Phase 1 ratification](research/2026-07-20-founder-knowledge-capture.md) worked.
8. **Stack threats bind at kickoff.** Wave kickoff includes reading the [threat model's](security/threat-model.md) stack-specific section 7 rows (landed in the same commit as this plan) whose `binds` name that wave's stories, and carrying their answers into the wave's acceptance tests.
9. **The RLS deferral is checked at every retro.** Each wave retro checks [ADR-004](adr/ADR-004-rls.md)'s four reopening triggers (T1 an isolation escape, T2 a DB path outside the guard, T3 the audience model materializing, T4 the contributor surface outgrowing the founding instance). This is the one item that turns "defer with triggers" into "defer forever" if it is skipped, so it is a standing rule, not a hope.

One naming note, recorded to keep the checklist honest: the [PATH-TO-100](PATH-TO-100.md) slice list said "PWA+push". ADR-002 moved web push post-v1 (S-305 is the negative guarantee: zero push by default and no firehose option, which needs no push infrastructure). Wave 5 is therefore PWA plus the elder path, and no wave ships push.

## Wave 1: Pods and auth

**Stories (9):** S-101, S-201, S-202, S-701, S-702, S-703, S-801, S-803, S-805
**Security blocks:** eight of the nine carry threat refs (S-803's archive-compatibility gate is an integrity story with no block); the anchors are TM-1 (credential registry and revocation), TM-8 (first-run safety), TM-10 (supervised minors), plus the auth boundary rows (T-CRED-1, T-SESS-1, T-ADMIN-1, T-AUTH-G1 through G3, T-REMOVE-1/2, T-BOOT-1).

The riskiest wave, on purpose: everything after it stands on this foundation, and ADR-003's consequences clause requires the credential machinery to exist before any product code depends on it. Born here:

- The data model: member, pod, yard, membership, with a pod able to belong to multiple yards from the first migration (the load-bearing requirement from the [Phase 0 founder-capture doc](research/2026-07-20-founder-knowledge-capture.md); retrofitting this is the migration we refuse to need).
- The central authorization guard, deny-by-default to a byte-identical 404. Every read handler routes through it; a handler that does not fails the build (the mandatory-guard CI rule).
- The credential registry and generation-ID revocation core from ADR-003, plus server-side revocable sessions. Master elder tokens are minted in wave 5, but the registry, the generation check, and the revocation handler with its completeness test exist now.
- Auth: django-allauth with passkey-primary login, password fallback with the S-101 hardening (rate limits, uniform errors, common-password rejection), and the custom invite view that creates a member from an invite token before WebAuthn enrollment (the allauth caveat ADR-002 named).
- Roles and the permission matrix (S-701), atomic removal with the revocation inventory (S-702), supervised accounts (S-703), break-glass console recovery (S-805).
- S-801 completes the first-run wizard: the Phase 1 first-admin flow grows into admin plus first yard plus first pod, with admin passkey-or-TOTP enforced.
- S-803's archive-compatibility test enters CI with the first real schema: a seeded database from this wave's migration state upgrades cleanly in every future CI run.
- The [ADR-004](adr/ADR-004-rls.md) database foundation, built here because it gets expensive to retrofit: the `backyard_migrator`/`backyard_app` Postgres role split so the app never runs as superuser (threat row TS-PG-1, with the CI assertion that the app role cannot `CREATE TABLE`); an indexed denormalized `yard_id` on single-yard tables with a database-level same-yard constraint on cross-row references (multi-yard audience tables stay enforced by the module and matrix, per ADR-004); the single audience-resolution module consumed by the guard, feed, search, and (later) the digest, with the unscoped manager renamed and CI-allowlisted and a no-raw-SQL grep; and the S-202 matrix generated from the model registry with relation-traversal fixtures. These keep RLS one migration away without adopting it, per ADR-004.

Also landing at the start of this wave, the cheap present-config hardening from threat-model section 7 that needs no new surface: pin `SESSION_ENGINE` (TS-DJ-1), set `ATOMIC_REQUESTS` (TS-DJ-2), drop the gunicorn access log (TS-EDGE-LOG), add `manage.py check --deploy` to CI (TS-DJ-10), and Docker log rotation (TS-CO-1).

The S-202 isolation suite starts here, covering members, pods, yards, invites, and the admin endpoints. Rule 3 grows it from there.

**Exit, beyond the standing rules:** the revocation-completeness test passes for every credential class that exists so far (session, invite); the wizard's TM-8 gates re-verified live on a clean machine, extending the Phase 1 receipt.

## Wave 2: Feed, posts, and links

**Stories (11):** S-000, S-203, S-204, S-205, S-301, S-302, S-303, S-304, S-305, S-901, S-902
**Security blocks:** S-203 (TM-3 audience picker), S-302 (deletion propagation), S-902 via the directory rows (T-YARD-6); the guard from wave 1 carries the rest.

The product becomes usable by the seed household: the chronological feed that ends, text and link posts with preview cards, comments (born here alongside posts, ahead of their email-reply ingress in wave 4), the audience picker with TM-3's narrowest-default and confirm-on-widen, ad-hoc pods, quiet mute and leave, profiles and the directory with per-field per-yard visibility (server-side, an extension of the wave 1 guard). The link-preview fetcher lands here and gets its own security review inside the wave's pass (S-301 was flagged in ADR-002 as hand-rolled security-sensitive code: SSRF, private-IP blocking, timeouts, size caps).

S-305 lands as the negative guarantee it is: zero push default, no firehose option anywhere, verified by tests that assert absence.

The htmx interaction surface gets its first real workout (composer, picker, feed). This is the revisit trigger ADR-002 recorded: if htmx fights the composer or the picker, that observation goes in the wave-boundary batch rather than being quietly absorbed.

**Exit:** isolation matrix extended to posts, comments, reactions, previews, profiles, directory fields, search and autocomplete; audience-picker confirm-on-widen exercised in the live repro including a bridging multi-yard post.

## Wave 3: Media

**Stories (5):** S-401, S-402, S-403, S-704, S-802
**Security blocks:** S-401/S-402 (TM-9 ingest strip, re-encode), S-403 (access-checked serving, signed URLs), S-802 (TM-7 encrypted backups).

The media pipeline from ADR-002: Pillow ingest with server-side metadata strip before any derivative, client-side Canvas resize, ffmpeg transcode on a concurrency-1 Procrastinate queue, and every byte served through the access-checked path with tiered signed URLs carrying the generation ID. Export (S-704) lands here because member export includes media by acceptance; building it earlier would have meant claiming a story a wave before it could be true. S-802's backup and restore drill lands here for the same reason: a backup story closed before media existed would have been a false receipt.

**ADR-002 gates due, measured in this wave:**
- ffmpeg transcode latency for a 60-second 1080p clip on Celeron/N100-class hardware, against S-402's minutes-at-most acceptance.
- The pillow-heif decision: does mandatory client re-encode hold, or does HEIC ingest need it?

**Exit:** isolation matrix extended to every derivative type (original, thumbnail, rendition, transcode, poster frame); restore drill executed on the encrypted path with the security replay; deletion-beats-expiry verified live.

## Wave 4: Digest email, in and out

**Stories (4):** S-501, S-502, S-705, S-903
**Security blocks:** S-501 (TM-2 same-authz-engine, per-digest tokens), S-502 (TM-4 capability reply addresses), S-903 (per-field date visibility).

The digest is built per recipient through the same audience-resolution path as the feed, at send time, with per-digest short-scope tokens; reply-by-email posts through capability addresses with From: never trusted. IMAP-poll ingest is the default adapter, Anymail the transport out. S-705's weekly aggregates ride the same scheduler because they are the same shape of work: a periodic job that must never become a second authorization path. S-903's upcoming-dates section and quiet banner land with the digest that carries them.

**ADR-002 gate due, measured in this wave:** the Anymail delivery-and-bounce tracking matrix for the chosen provider, before S-501's per-member delivery-status view is promised.

**Exit:** isolation matrix extended to digest rendering (including upcoming-dates and every signed media URL) and reply-address handling; the T-EMAIL-G2 quoted-digest strip exercised with real mail-client fixtures; the injection fixture set from T-EMAIL-8 in the suite.

## Wave 5: PWA and the elder token path

**Stories (5):** S-102, S-103, S-104, S-601, S-602
**Security blocks:** S-102 (TM-5 token hygiene, capability ceiling), S-104 (provisioning and regeneration).

The elder surface ships last because it renders everything waves 1 through 4 build. The cost of that order, named honestly: the elder path is the product's core bet, and this sequencing validates its UX last. The credential machinery being live since wave 1 covers the mechanism risk, not the UX risk; a stubbed earlier surface would validate neither, since what elders react to is their family's real feed. This wave mints the master token and builds the surface: URL-to-cookie exchange, the capability ceiling, the large-text WCAG AA view, one-tap named reactions, and the provisioning flow that ends with the re-hand-over artifacts ready to send. The PWA manifest and minimal service worker land alongside, with the elder surface never depending on the service worker (the Safari eviction rule from ADR-002).

**ADR-002 gate due, measured in this wave:** RAM footprint across the four containers under the full stack, against the 0.7 to 1.2 GB estimate.

**Exit:** the full revocation-completeness drill live: after regenerate and after removal, master token, session, digest link, signed media URL, and reply address each 404 or bounce on next request. The isolation matrix covers the token surface as a request class. WCAG 2.1 AA checks pass on the elder view. This exit is also Phase 2's exit: every v1 story at `tested`, every receipt committed.

## What could reorder this

Recorded so a change is a decision, not drift: if the seed household needs the digest before media (lurker pull beats photo push), waves 3 and 4 can swap; their only coupling is inline digest images, which degrade to links. Nothing else in the order is negotiable: the guard, registry, and revocation core precede everything that mints credentials, and the elder surface follows what it renders.
