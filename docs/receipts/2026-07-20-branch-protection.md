# Receipt: branch protection armed on main

Date: 2026-07-20. Operator: orchestrator session (Phase 1 goal). Applied via `gh api -X PUT repos/AIJSAI/backyard/branches/main/protection`.

## Active configuration (from the API response)

| Setting | Value |
|---|---|
| Required status checks | `gates`, `secrets` (strict: branch must be up to date) |
| Enforce for admins | **enabled** (no bypass, including the owner) |
| Required conversation resolution | enabled |
| Required linear history | enabled |
| Force pushes | blocked |
| Branch deletion | blocked |
| Required PR approvals | none required |

## Why zero required approvals

GitHub does not let a PR author approve their own PR. With a single human maintainer, requiring approvals would deadlock every merge behind an outside reviewer who does not exist yet. The review gate is carried instead by: required CI checks (both provably non-vacuous), required conversation resolution (review comments block merge until resolved), enforce-admins (nobody pushes to `main` directly, owner included), and the project's own review workflow (reviewer passes before merge on substantive changes). If a second maintainer ever lands, required approvals go to 1 and this receipt gets superseded.

## Live test

This receipt itself merged through the protection it documents: committed on a branch, PR opened, both required checks green, then merged. The PR is the evidence that direct pushes are off and the gates bind.

Verify current state anytime:

```
gh api repos/AIJSAI/backyard/branches/main/protection
```
