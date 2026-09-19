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
| Households and groups that posted | Distinct pods that posted this week. Stored as `YardWeekMetrics.posting_breadth`, which is what the model, the migration and `rollup_metrics` still call it. The screen says "Households and groups that posted" because the number counts pods, not people — three people in one household posting counts one — and because "posting breadth" was jargon on a page a relative reads. An ad-hoc group counts as one too, which the label now names | A feed with one poster is a broadcast, not a backyard; breadth predicts return visits |
| Reciprocity rate | Share of posts receiving any response (reaction, comment, or elder email reply) within 7 days | The field-research failure mode was one-way flow; responses close the loop that keeps posters posting (R2) |
| Elder touch rate | Share of elder members with any touch this week (token link, digest open proxy, email reply) | The hardest segment; if elders connect, the design is working (R3) |
| Catch-up regularity | Members with at least one feed visit in the week | The lurker habit is legitimate participation and the base of the pyramid |

**A frame display heartbeat is NOT an elder touch.** The elder-touch row used to list one,
which contradicted the definition of "active" four paragraphs above it, inside this one
file. A heartbeat is a powered-on tablet, not a deliberate act: wire it in and the one
signal that would tell a family an elder has gone quiet reads "active" for as long as her
frame has electricity. The ruling on record is to keep the heartbeat when S-603 is built,
record it under its own name (*"the frame in the kitchen has been dark for nine days"* is a
real signal, arguably a better one) and keep it out of `touched` — see
[the S-603 display threat draft](security/s603-display-threat-draft.md), row T-DISPLAY-5.
Nothing emits a heartbeat today; S-603 is still `spec`
(`grep -n 'id: S-603' -A 6 stories/stories.yaml`).

Every input the code actually counts is a human doing something: a feed visit, a post, a
reaction, a comment, a digest open, an email reply. Read them off `core/metrics.rollup_week`
rather than from this page.

## Anti-metrics (explicitly never optimized, never displayed)

Time on site · sessions per day · posts per person targets · streaks · like counts · follower anything. If a change increases WCM by increasing interruptions or obligation, it violates principle 1 and gets reverted. The metric serves the calm, never the reverse.

## Instrumentation (privacy-first, per principles)

- Server-side counters only; no third-party analytics, no client fingerprinting, no tracking pixels.
- Weekly aggregate rollups; raw event rows kept short-lived and local to the instance.
- Visible to the instance admin only, as aggregates per pod/yard, not per-person surveillance dashboards. The one exception: the alpha KPI requires per-member weekly presence (a yes/no), documented openly to the family being measured.
- Every instance owns its numbers; nothing phones home to the project. The project learns from the founder's instance and from what self-hosters volunteer.
