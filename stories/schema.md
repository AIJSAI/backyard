# stories.yaml schema

Top level: `meta` (version, updated, note) and `epics` (list).

Epic fields: `id` (E-number), `title`, `intent`, `stories` (list, may be empty).

Story fields (all required):

| Field | Meaning |
|---|---|
| `id` | Stable id, `S-` prefix. Never reused. |
| `epic` | Parent epic id. |
| `persona` | Who this serves (e.g. founder-poster, lurker, elder, pod-owner, self-hoster). |
| `story` | One sentence: As X, I can Y so that Z. |
| `acceptance` | Non-empty list of testable criteria. These become the e2e spec. |
| `status` | `spec` -> `built` -> `tested` -> `passing`. |
| `evidence` | Required when status is `passing`: URL or repo path to the test receipt. |
| `v1` | Optional boolean: marks the v1 walking-skeleton cut (see docs/story-map.md). Absent means not yet triaged. |

Discipline: stories are written before code (acceptance criteria are the spec). Status flips to `passing` only with evidence; CI (`scripts/check_stories.py`) enforces structure, status values, and the evidence rule, and self-tests its own guards against known-bad fixtures so the gate can never rot into a vacuous green.
