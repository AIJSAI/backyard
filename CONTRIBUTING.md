# Contributing

Backyard is pre-alpha and moving fast; expect churn until v0.1.

## Ground rules

- **DCO, no CLA.** Every commit must be signed off (`git commit -s`), certifying the [Developer Certificate of Origin](https://developercertificate.org/). That sign-off is the entire paperwork; there will never be a CLA.
- **Conventional commits**: `feat` / `fix` / `docs` / `refactor` / `chore` / `test` / `perf` / `ci`.
- Small, focused PRs. One concern per PR.
- **Stories are the spec.** Work traces to an entry in [stories/stories.yaml](stories/stories.yaml). If your change has no story, propose the story first.
- The CI gate must be green (`scripts/check_stories.py` runs the tracker and checklist guards).

## What helps most right now

Product feedback grounded in real family use, deployment testing on real homelab hardware, and accessibility review of the elder path. Code contributions become practical once the architecture ADR lands.

## Privacy line

Never post real family data (names, faces, screenshots with real content) in issues, PRs, or discussions. Demo fixtures only. This rule has no exceptions; it is the product's whole point.
