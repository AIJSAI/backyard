# Assumption map and kill criteria

Status: Phase 0 artifact, 2026-07-20. Assumptions ranked by risk. Each has a test and, where warranted, a kill or pivot criterion. Honesty rule: founder optimism is recorded as optimism, never as evidence.

## Ranked assumptions

| ID | Assumption | Risk | Test | Trigger if false |
|---|---|---|---|---|
| A-HABIT | The founding household will form a weekly check-in habit around a calm feed with no notifications pushing them | **Highest** | Alpha KPI: WCM >= 4/6, 3 of 4 consecutive weeks ([metrics](metrics.md)) | KILL PATH below |
| A-ADOPTION | Extended family members beyond the seed household will join and stay via pod-by-pod rollout ("everyone will try it" is founder optimism, recorded as such) | High | Per-yard WCM after each pod invite wave | Pause rollout, adoption discovery on the stalled pod before inviting more |
| A-ELDER-RECIPROCITY | Grandparents will not just view but respond, given one-tap and email-reply paths | High | Elder touch rate and elder share of reciprocity within 8 weeks of elder onboarding | Redesign elder reply surface before adding ANY other elder feature |
| A-TEENS | High-schoolers will at least lurk; some will post when audiences are scoped and nothing is publicly amplifiable. Proxy VoC (2026-07-20) found thin, uniformly negative teen signal (teens default to peer networks), so the plan assumes asymmetric participation: parents and elders are the active core, teens are occasional contributors, and adoption math never depends on them | Medium | Teen WCM and teen posting in alpha + rollout | Ship teen-scoped pods (cousins) earlier; treat any teen posting as upside, never as a gate |
| A-CALM-SUFFICIENT | Zero notifications by default will not starve the feed of attention (the digest email and habit are enough pull) | Medium | Catch-up regularity vs posting activity divergence | Add strictly opt-in, per-member weekly digest nudge; never per-post push by default |
| A-BOUNDARIES | No hidden visibility landmines exist in the family graph (none surfaced in founder capture) | Medium | First 8 weeks of real posting behavior; any "please hide this from X" request | Per-post audience override already ships in v1 as structural insurance; add member-level mute-from-pod if requested twice |
| A-SEED-ALLY | A second reliable poster exists in the founding household | Medium | Identify within 2 weeks of alpha | Founder recruits one ally explicitly before inviting pod two |
| A-SELFHOST-DEMAND | Other families (via their tech-family-member) will deploy Backyard once launched | Low stakes pre-launch | Stars, deploys, NAS-store installs after Phase 5 | No kill: the project remains excellent personal software; OSS ambitions archive honestly |

## Kill path (A-HABIT)

The one that ends the project rather than tuning it:

1. Alpha misses KPI for a full cycle: diagnose with the family informally, ship one design iteration.
2. Misses a second cycle after iteration two: **feature work stops.** Only adoption discovery is allowed (what would make you check it weekly?).
3. Still failing after that: the project archives honestly with a public post-mortem in the devlog. No zombie repo. The graveyard this project was researched out of does not get a new resident quietly.

## Standing insurance (structural, ships regardless)

Per-post audience override (A-BOUNDARIES) · token-link plus email elder paths (A-ELDER-RECIPROCITY) · no public metrics anywhere (A-TEENS) · full export (leaving is always safe).
