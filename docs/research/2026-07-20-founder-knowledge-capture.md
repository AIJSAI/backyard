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

## Rollout amendment

Rollout is **per yard**, not toward one clan layer: seed household first, then one high-energy pod on whichever side shows pull, opening each yard when its pods post weekly. The PATH-TO-100 Phase 6 items are interpreted per-yard.
