# Founder knowledge capture

Date: 2026-07-20. Method: structured Q&A with the founder, who is a member of the user population and holds the family graph first-hand. This is founder domain knowledge, honestly labeled: **no user interviews were conducted** (a deliberate choice). Every assumption below gets behavioral validation in the seed-pod alpha, not by asking.

## The load-bearing fact: the two sides stay separate

The founder does **not** want to bring both extended families together. The two sides (maternal and paternal) are distinct communities that only intersect at his own household.

Structure per side: 2 grandparents; 5 adult siblings, each married, 2 to 4 kids per household. Roughly 25 to 30 people per side, 55 to 60 total. The founder's household of 6 is the only unit that belongs to both.

### Domain model implication: yards

The research-phase assumption of "pods plus ONE shared clan layer" is dead. The model becomes:

- **Pod** = a household (or later, an ad-hoc group like cousins or siblings).
- **Yard** = one side's community, with its own shared backyard feed.
- A pod can belong to **more than one yard** (the founder's household belongs to both).
- Per-post audience: my pod, a yard I belong to, or several at once. The already-required per-post audience override is the bridging mechanism; there is no forced all-family surface.

Getting this into the schema from day one avoids the single-community hardcoding that would otherwise demand a painful migration. One instance hosts multiple yards; one deploy, one KPI, total feed isolation between sides.

## Channels today

Group texts, and essentially nothing else. This confirms the core thesis: the family's only shared channel is interrupt-driven, with no archive, no media organization, and no ambient catch-up.

## Elders

Four grandparents (two per side). Onboarding will be assisted by family ("we will get them set up"), which matches the tech-grandchild pattern from the literature. Consequence: token links matter most for **daily use** (no passwords to remember, nothing to install), not just first setup.

## Open assumptions (feed the assumption map)

| ID | Assumption | Stance |
|---|---|---|
| A-TEENS | High-schoolers will at least lurk; some will post if scoped safely. Founder flags this as an open design question. Levers: per-post audiences (cousins pod, not the whole yard), zero public metrics, no cross-yard resharing, nothing a parent can publicly amplify. | Validate in alpha |
| A-BOUNDARIES | No known visibility landmines today (no divorces or estrangements surfaced). Per-post audience and flexible pod membership are retained as structural insurance anyway. | Monitor |
| A-ADOPTION | Founder expects "everyone will try it and participate." Recorded as founder optimism, not evidence. KPI gate and kill criteria unchanged. | KPI-gated |
| A-SEED-ALLY | Second reliable poster in the seed household not yet identified; the KPI needs 4 of 6. | Identify in alpha |

## Addendum (2026-07-20, later the same day): profiles and the directory

Founder ask, verbatim intent: individual profiles should carry birthdays, school, work, age, phone numbers, email; "contact information is helpful in a family," plus birthday reminders. Product translation became epic E9 (People and the family directory) with principle-preserving constraints: per-field per-yard visibility, age never displayed, dates surfaced via digest and a quiet feed banner rather than push. Anniversaries included; remembrance dates and genealogy deliberately deferred.

## Ratification (2026-07-20, batched Phase 1 sign-off)

The founder ratified the PR-FAQ, the 8 product principles, the v1 story cut (34 stories after S-805 joined), ADR-002 (Django stack), ADR-003 (token links), and the threat model in one batched review. Before ratifying he asked three clarifying questions about the deliberate exclusions, recorded here with the answers because they are the kind of questions users will ask too:

- **What is E2EE?** End-to-end encryption: content encrypted on the sender's device and readable only on recipients' devices, never by the server. Excluded from v1 because the elder surfaces depend on the server reading content (rendering the token-link feed, building the email digest, mapping email replies to comments). Backyard's threat model is platform-elimination, not secrecy from the family member hosting the box; the admin's power is disclosed instead of encrypted away.
- **Is chat excluded because it would be hard to use?** No, it is a scope decision, not a difficulty one. Group texts already do family messaging well and are entrenched; Backyard replaces their broadcast misuse (async catch-up), not messaging itself. Shipping chat would compete with iMessage, drag in presence and read-receipt pressure, and risk cannibalizing the feed the product exists for.
- **Is the calendar exclusion about birthdays?** No. Birthdays and anniversaries are in (people-dates in the directory, surfaced through the digest and a quiet banner, S-903). The exclusion is a calendar *product* (events, RSVPs, scheduling), which the family-organizer app wave already covers and which is a different job.

All three exclusions stand as ratified; each is reversible later as a spec story if real family usage argues for it.

## Rollout amendment

Rollout is **per yard**, not toward one clan layer: seed household first, then one high-energy pod on whichever side shows pull, opening each yard when its pods post weekly. The PATH-TO-100 Phase 6 items are interpreted per-yard.
