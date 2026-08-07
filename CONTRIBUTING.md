# Contributing

Backyard is at [`v0.1.2`](CHANGELOG.md) and still moving fast; `0.x` means the schema and the
URLs may change under you. Work from a tag if you want stable ground, from `main` if you want
to contribute.

## Ground rules

- **DCO, no CLA.** Every commit must be signed off (`git commit -s`), certifying the [Developer Certificate of Origin](https://developercertificate.org/). That sign-off is the entire paperwork; there will never be a CLA. CI enforces it on the commits a pull request adds.

  **Existing history is not all signed** — 85 of the first 154 commits carry no trailer, from before this was enforced. They cannot be fixed: adding it means rewriting every SHA, which breaks every link and every receipt that cites one. So the rule binds from the merge base forward, and this paragraph says so rather than leaving a reader to discover it in `git log` and wonder what else here is aspirational.
- **Conventional commits**: `feat` / `fix` / `docs` / `refactor` / `chore` / `test` / `perf` / `ci`.
- Small, focused PRs. One concern per PR.
- **Stories are the spec.** Work traces to an entry in [stories/stories.yaml](stories/stories.yaml). If your change has no story, propose the story first.
- The CI gate must be green (`scripts/check_stories.py` runs the tracker and checklist guards).

## What helps most right now

Product feedback grounded in real family use, deployment testing on real homelab hardware, and accessibility review of the elder path — **especially the elder path**, which has been verified entirely by one person driving a browser and never by an actual elder.

**Code contributions are practical now.** The stack is settled ([ADR-002](docs/adr/ADR-002-stack.md)) and the architecture is documented: start at [docs/README.md](docs/README.md), which has diagrams of the data model, the elder path, and the one audience query everything routes through. Run the gate before you open a PR:

```bash
uv run ruff check src && uv run ruff format --check src && uv run mypy src && uv run pytest
```

Tests need their own Postgres — the compose one does not publish 5432. The recipe is in
[docs/RESUME-HERE.md](docs/RESUME-HERE.md) under "the environment recipe".

**The highest-value contribution is an adversarial one:** read the [threat model](docs/security/threat-model.md) and try to break a claim in it. It has never had an outside reader.

## Privacy line

Never post real family data (names, faces, screenshots with real content) in issues, PRs, or discussions. Demo fixtures only. This rule has no exceptions; it is the product's whole point.
