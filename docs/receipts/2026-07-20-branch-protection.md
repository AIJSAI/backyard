# Receipt: branch protection armed on main

Date: 2026-07-20. Operator: orchestrator session (Phase 1 goal). Applied via `gh api -X PUT repos/AIJSAI/backyard/branches/main/protection`.

## Active configuration (from the API response)

| Setting | Value |
|---|---|
| Required status checks | `gates`, `secrets`, `code`, `e2e` (strict: branch must be up to date) — see the 2026-07-22 update below |
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

## Update 2026-07-22 — required checks refreshed (S-722)

The required-status-checks set grew as the CI grew, and this receipt had gone stale (the
Phase-2 retro flagged it). The live set is now **`gates`, `secrets`, `code`, `e2e`**
(strict), reconciled here:

- `code` (the ruff + mypy + full pytest + docker-build + compose-probe job) was added when
  the application code landed and is now recorded as required.
- **`e2e` armed as required (S-722):** the cross-browser mobile job (WebKit = iOS Safari,
  Chromium = Android Chrome) is the *sole* automated proof of S-101's "verified on iOS
  Safari and Android Chrome" and of the S-212/S-213 mint→hand-over→react browser paths. It
  ran on every PR but was advisory; it is now a required check, so a red e2e blocks merge.
  It runs on every `pull_request` with no path filter, so it never deadlocks a docs-only PR.

Applied via `gh api -X PATCH repos/AIJSAI/backyard/branches/main/protection/required_status_checks`
(contexts only; strict, enforce-admins, conversation-resolution, linear-history, and the
force-push/deletion blocks all unchanged and re-verified). This receipt's own PR merged
through the refreshed protection — including the newly-required `e2e` — which is the live
proof that the e2e gate now binds.
