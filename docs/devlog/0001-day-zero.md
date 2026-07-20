# Devlog 0001: Day zero, research first

Date: 2026-07-19

Backyard exists as of tonight. No code yet, on purpose.

What happened before the first commit:

- A deep research sweep (103 research agents, every claim adversarially verified against primary sources) established that the niche is genuinely empty: no active, polished, family-focused open-source social network exists anywhere. The whitespace is specifically an async family feed with nested privacy pods and a grandparent-grade onboarding path. Receipts in the [research brief](../research/2026-07-19-research-brief.md).
- Peer-reviewed in-home deployment studies (21-week field trials, not surveys) supplied the design requirements: async and ambient beats always-on, reciprocity is mandatory, and you cannot assume the oldest generation owns a smartphone.
- A 32-candidate naming sprint, one verification agent per name, killed 11 candidates on collisions with live products we would never have caught guessing. The survivors, the finalists, and the reasoning are in [ADR-001](../adr/ADR-001-name.md).
- License and governance settled up front: AGPL-3.0, DCO, no CLA ([ADR-000](../adr/ADR-000-license.md)).
- The definition of done is public from day zero: [Path to 100%](../PATH-TO-100.md). A checkbox only counts with an evidence link, and CI enforces that rule starting with this commit.

Next: the PR-FAQ, final product principles, the story map, and only then a stack decision.
