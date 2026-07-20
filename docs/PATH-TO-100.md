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
- [ ] Proxy voice-of-customer sweep (incumbent app-store reviews, r/selfhosted threads, zusam/HumHub issue trackers)
- [ ] PR-FAQ (working backwards)
- [ ] Product principles finalized (draft: docs/principles.md)
- [ ] North Star metric + input tree, privacy-first instrumentation plan
- [ ] Assumption map with kill criteria
- [ ] Story map; stories.yaml populated with the v1 cut + acceptance criteria
- [ ] Content judge panel workflow encoded (slop / substance / audience / voice lenses)
- [x] Domain registered: backyard.family (single-domain decision, ADR-001 amended) evidence: https://rdap.org/domain/backyard.family

## Phase 1: Architecture and scaffold

- [ ] Threat model (token links, pod isolation, media privacy, minors)
- [ ] ADR-002: stack decision, grounded in current library docs, not defaults
- [ ] CI: lint + typecheck + tests + build, from the first code commit
- [ ] Branch protection and review gates armed
- [ ] `docker compose up` brings up a hello-world instance on a clean machine
- [ ] Secrets hygiene verified: zero secrets in history (public repo from day 1)

## Phase 2: Build waves

- [ ] Wave plan with slices (pods+auth, feed+links, media, digest, PWA+push, elder path)
- [ ] Every wave closes on the full verification gate plus a live repro, never subset tests

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
