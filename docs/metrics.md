# North Star and input metrics

Status: Phase 0 artifact, 2026-07-20.

## North Star

**Weekly Connected Members (WCM): family members active this week without being prompted.**

"Active" means any deliberate touch: opening the feed, posting, reacting, replying by email, or a token-link visit. "Unprompted" means not immediately preceded by someone texting them a link to look at (the exact behavior Backyard exists to replace). The alpha KPI is WCM >= 4 of 6 in the founding household, 3 of 4 consecutive weeks.

This is a connection metric, not an engagement metric: it counts people who showed up at all this week, never time spent, sessions per day, or items consumed. A family where everyone checks in once a week is a fully healthy Backyard.

## Input tree

WCM is driven by four inputs, each per yard:

| Input | Definition | Why it leads WCM |
|---|---|---|
| Posting breadth | Distinct pods that posted this week | A feed with one poster is a broadcast, not a backyard; breadth predicts return visits |
| Reciprocity rate | Share of posts receiving any response (reaction, comment, or elder email reply) within 7 days | The field-research failure mode was one-way flow; responses close the loop that keeps posters posting (R2) |
| Elder touch rate | Share of elder members with any touch this week (token link, digest open proxy, email reply, frame display heartbeat) | The hardest segment; if elders connect, the design is working (R3) |
| Catch-up regularity | Members with at least one feed visit in the week | The lurker habit is legitimate participation and the base of the pyramid |

## Anti-metrics (explicitly never optimized, never displayed)

Time on site · sessions per day · posts per person targets · streaks · like counts · follower anything. If a change increases WCM by increasing interruptions or obligation, it violates principle 1 and gets reverted. The metric serves the calm, never the reverse.

## Instrumentation (privacy-first, per principles)

- Server-side counters only; no third-party analytics, no client fingerprinting, no tracking pixels.
- Weekly aggregate rollups; raw event rows kept short-lived and local to the instance.
- Visible to the instance admin only, as aggregates per pod/yard, not per-person surveillance dashboards. The one exception: the alpha KPI requires per-member weekly presence (a yes/no), documented openly to the family being measured.
- Every instance owns its numbers; nothing phones home to the project. The project learns from the founder's instance and from what self-hosters volunteer.
