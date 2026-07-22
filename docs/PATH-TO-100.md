# Path to 100%

The single canonical checklist for Backyard v1.0. Rules:

1. A box may only be checked with an evidence link on the same line (`evidence:` followed by a URL or repo path). CI enforces this.
2. Items get added, never silently deleted. Superseded items are struck through with a note.
3. 100% means the goal below is MEASURED, not vibes.

## The goal (open until every criterion has receipts)

**BACKYARD v1.0: LEGIT + ALIVE.** Closed only when ALL of:

1. 100% of v1 stories at status `passing` in [stories/stories.yaml](../stories/stories.yaml), each with test evidence
2. Seed pod live: at least 4 of 6 household members active in 3 of 4 consecutive weeks, unprompted (server receipts)
3. This checklist at 100% with evidence links
4. One-command deploy verified on a clean machine (fresh VM, documented run)
5. v1.0 tagged; public demo and docs site live

## Phase 0: Product foundation

- [x] Research brief with verified findings evidence: docs/research/2026-07-19-research-brief.md
- [x] License decided and recorded evidence: docs/adr/ADR-000-license.md
- [x] Name decided and recorded evidence: docs/adr/ADR-001-name.md
- [x] Founder knowledge capture (family graph, sharing habits, sensitivities) evidence: docs/research/2026-07-20-founder-knowledge-capture.md
- [x] Proxy voice-of-customer sweep (six channels, verbatim quotes, honest coverage gaps) evidence: docs/research/2026-07-20-voc-sweep.md
- [x] PR-FAQ (working backwards; two judge-panel passes, all blockers resolved) evidence: docs/PR-FAQ.md
- [x] Product principles v1 (two judge-panel passes, all blockers resolved; founder sign-off batched in ratification) evidence: docs/principles.md
- [x] North Star metric + input tree, privacy-first instrumentation plan evidence: docs/metrics.md
- [x] Assumption map with kill criteria evidence: docs/assumptions.md
- [x] Story map; stories.yaml populated with the v1 cut + acceptance criteria evidence: docs/story-map.md
- [x] Content judge panel workflow encoded (slop / substance / audience / voice lenses) evidence: .claude/workflows/judge-content.js
- [x] Domain registered: backyard.family (single-domain decision, ADR-001 amended) evidence: https://rdap.org/domain/backyard.family

## Phase 1: Architecture and scaffold

- [x] Threat model (token links, pod isolation, media privacy, minors); token-link forwarding trade-off recorded as ADR-003; judge-panel passed evidence: docs/security/threat-model.md
- [x] ADR-002: stack decision, grounded in current library docs, not defaults; full dossier committed; judge-panel passed evidence: docs/adr/ADR-002-stack.md
- [x] CI: lint + typecheck + tests + build, from the first code commit (ruff + mypy + pytest + docker build in the `code` job) evidence: .github/workflows/ci.yml
- [x] Branch protection and review gates armed (required checks gates+secrets, enforce-admins, conversation resolution; merged through its own protection) evidence: docs/receipts/2026-07-20-branch-protection.md
- [x] `docker compose up` brings up a hello-world instance on a clean machine (first-admin flow reached; TM-8 gates verified live) evidence: docs/receipts/2026-07-20-compose-first-admin.md
- [x] Secrets hygiene verified: zero secrets in history, gitleaks full-history scan + continuous CI job with non-vacuous selftest evidence: docs/receipts/2026-07-20-secrets-scan.md

## Phase 2: Build waves

- [x] Wave plan with slices (pods+auth, feed+links, media, digest, PWA + elder path; push moved post-v1 by ADR-002, slice label amended) evidence: docs/wave-plan.md
- [x] Stack-specific threat pass (Django, Postgres, Caddy, compose, parsers) appended to the threat model (section 7; 46 findings, adversarially verified, security-reviewer passed) evidence: docs/security/threat-model.md
- [x] ADR-004: Postgres RLS belt-and-suspenders decision on the record (defer-with-triggers; role split + same-yard schema built wave 1) evidence: docs/adr/ADR-004-rls.md
- [x] Wave 1 (pods+auth) closed: full gate + live repro receipt (S-101 feed-landing and S-201 household-onboarding carried into wave 2 per the wave plan) evidence: docs/receipts/2026-07-20-wave-1-close.md
- [x] Wave 2 (feed+links) closed: full gate + live repro receipt evidence: docs/receipts/2026-07-20-wave-2-close.md
- [x] Wave 3 (media) closed: full gate + live repro receipt; ffmpeg latency measured (2-vCPU Ubicloud, 60s 1080p 14.9s) and pillow-heif decided evidence: docs/receipts/2026-07-21-wave-3-close.md
- [x] Wave 4 (digest in/out) closed: full gate + live repro receipt; Anymail delivery-status matrix measured (delivered/bounced/complained + real inbox); S-501/502/903/705 all tested (live Resend send + inbound round-trip; S-705 family disclosure kept light + judge-passed) evidence: docs/receipts/2026-07-22-wave-4-close.md
- [x] Wave 5 (PWA + elder path) closed: full gate + live repro receipt; RAM footprint measured (four containers, ~294 MiB); full revocation drill (six credential classes, live) evidence: docs/receipts/2026-07-21-wave-5-close.md
- [x] Every wave closes on the full verification gate plus a live repro, never subset tests evidence: docs/receipts/

### What is left, and who unblocks it

Waves 1, 2, 3, 5 are closed and tested; **wave 4 (digest email in/out) closed
2026-07-22** ([receipt](receipts/2026-07-22-wave-4-close.md)) — Resend wired via
django-anymail v15, the ADR-002 delivery-and-bounce matrix measured
(delivered/bounced/complained + a real inbox), and both halves proven live on the
running compose stack: outbound through the app's Anymail→Resend path, and a full
inbound reply-by-email round-trip (Resend receiving → `email.received` webhook →
comment posted, quoted tail stripped, attributed from the capability). **S-501,
S-502, S-903 are `tested`.** The one remaining item is a founder input, not code:

1. **Email provider, sending domain, inbound mailbox** (closes wave 4).
   Recommended and researched: create a second **free Resend Team** under the
   existing login (the "one project" limit is really Free's 1-domain cap;
   multiple isolated Teams are free), put **both sending and receiving on one
   domain** (`mail.backyard.family`, since each subdomain counts against the
   1-domain cap), set SPF/DKIM/aligned-DMARC, and add Resend's inbound MX +
   `email.received` webhook. Verified: Resend does inbound and django-anymail
   wires it (v15.0), and inbound is included on Free. This is zero repo code but
   real ops — Anymail is one settings change behind a provider-agnostic seam.
   Then measure the ADR-002 delivery-and-bounce matrix, run the live mailbox
   round-trip, and wave 4's stories flip to `tested`.

   *Wave 3 closed 2026-07-21* ([receipt](receipts/2026-07-21-wave-3-close.md)):
   ffmpeg latency measured on a 2-vCPU Ubicloud runner (60s 1080p 14.9s, PASS),
   pillow-heif decided (client Canvas conversion, defer the dependency),
   client-side resize + video transcode + encrypted-backup restore all
   live-repro'd.

2. **The batched policy defaults** — RATIFIED in
   [ADR-005](adr/ADR-005-batched-defaults.md) (2026-07-21). The wave-boundary
   knobs are now decided on the record, each unchanged from its proposed value:
   the 3-and-4 build overlap; the digest-link TTL (21 days); the reply-address
   grace (30 days past supersession, with voiding and generation-kill immediate
   underneath); date-visibility (YARD for adults, POD for supervised, contact
   fields HIDDEN); a bridge household's pod-only posts in both sides' digests
   (yes — the pod spans, the yard never fuses); top-quoting clients (quarantine,
   never recover); digest enrollment (opt-in with double-confirm) and timing
   (rolling per-member weekly anchor, not a global send-time). The S-705 family
   disclosure *wording* is RESOLVED (2026-07-22): the founder chose a deliberately
   light family note ([family-privacy-note.md](family-privacy-note.md)),
   judge-passed, with the fuller technical privacy documentation deferred to the OSS
   deployer docs (Phase 5). S-705 is now `tested`. The privacy posture it describes
   is already ratified and enforced in code.

## Phase 3: Story loop

- [ ] Every v1 story tested against the live app with receipts; loop until 100% passing

## Phase 4: Seed pod alpha

- [ ] Deployed instance for the founding household of 6
- [ ] KPI instrumented: weekly active members, unprompted, aggregates only
- [ ] 3 of 4 consecutive weeks at 4/6 or better

## Phase 5: OSS launch machinery (gated on Phase 4 passing)

- [ ] Docs site: admin install, member guide, elder path page, PM case-study page
- [ ] Public demo instance seeded with the fictional demo family
- [ ] GHCR images, tagged releases, changelog
- [ ] NAS store listings: TrueNAS SCALE, Umbrel, Unraid
- [ ] awesome-selfhosted PR
- [ ] API + MCP endpoint
- [ ] Launch posts (judge-panel approved): r/selfhosted, Show HN

## Phase 6: Extended rollout

- [ ] Pod-by-pod invites: one high-energy pod per side of the family
- [ ] Shared backyard layer opened once 3+ pods post weekly
- [ ] Full-clan invite timed to a family gathering
- [ ] v1.0 tag
