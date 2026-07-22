# S-201 close: delegated household onboarding (invite a household in one flow)

Date: 2026-07-21. Story **S-201** (epic E2). Branch
`feat/s-201-household-invite` off `main` (`2215cc0`). This closes the
rollout-critical carry-forward: a per-side moderator (yard admin) onboards a
household **without the founder** — names it, picks their side of the family, and
gets a one-time link + printable QR to hand over. Whoever opens the link picks a
name and password and lands straight in the family feed, with no
create-a-community screen. Every claim below is run or measured, never asserted.

## What shipped

- `core/permissions.can_issue_invite(actor, pod)` — the write-authority gate for
  minting an invite, mirroring `can_manage_member`: instance admin into any pod; a
  yard admin only into a pod whose yards are **all** within their own (T-AUTH-G2);
  pod owners and plain members never issue in v1. The prior `_target_within_actor_scope`
  empty-set hole (a yardless target vacuously passing the subset check) is closed in
  the same idiom (`bool(target_yards) and …`).
- `core/scoping.pod_yard_ids(pod)` — the pod-side companion to `member_yard_ids`.
- Three admin views in `core/admin_views.py`:
  - `invite_household` — creates the household pod in the picked yard and mints its
    invite in **one atomic flow**, shows the link + inline SVG QR once, carries the
    TM-5 `no-store`/`no-referrer`/`noindex` header set, and is guarded by a single-use
    intent nonce so a browser refresh does not duplicate the household.
  - `invite_list` — the outstanding-invite ledger, scoped **exactly** to what the
    actor may issue, showing per invite the uses-left, expiry, and who redeemed it
    and when (the S-201 join-visibility hardening).
  - `revoke_invite` — POST-only; revoking kills the link immediately with 404-parity.
- `core/handover.py` — the `qr_svg` / `fresh_intent` / `consume_intent` helpers, now
  shared by both the elder-token path (S-104) and this one; `provisioning_views.py`
  was refactored onto it with its per-target nonce key preserved.
- Templates `core/invite_household.html` and `core/members_invites.html`; three
  routes in `config/urls.py`; a ledger link from the members roster.

## Full verification gate (never a subset)

`ruff check` + `ruff format --check` + `mypy` (**126 files**) + full `pytest`
(**462 passed, 0 skipped** — ffmpeg was installed locally so the S-402 video/transcode
tests ran for real, not skipped) + `docker build` (both `backyard-web` and
`backyard-worker` images built clean). Run against a Postgres 18 matching the CI
`code` job.

New tests: `can_issue_invite` scope / empty-set / pod-owner-and-member cases in
`test_permissions.py`; a full round-trip suite in `test_invite_household.py` (one-flow
create + pod kind/yard, invitee-lands-inside-pod, refresh-no-duplicate, name-required,
yard-admin-confinement with cross-yard 404-parity, plain-member 403, ledger scoping,
bridge-pod exclusion, revoke-kills-link, revoke-POST-only, cross-scope-revoke-404,
TM-5 headers).

## Security review (mandatory — grants + bearer-token surface)

A `security-reviewer` pass traced the full diff, the redemption/join path, the shared
helpers, both templates, the models, and the tests. **Verdict: clean — no CRITICAL,
no HIGH.** All ten required properties confirmed holding: yard-scope confinement with
genuine defense-in-depth (primary `require_visible_yard` + in-transaction
`can_issue_invite` re-check), byte-identical 404 parity, non-vacuous empty-set in both
guards, admin-only issuance with no ownership-keyed branch, once-only non-logged token
with TM-5 headers, the intent-nonce replay guard, QR XSS-safety (only the CSPRNG token
in trusted `BASE_URL` reaches the SVG; `household_name`/`yard_name` are auto-escaped and
never touch it), transaction atomicity (no orphan pod on a mid-flow refusal), CSRF +
POST-only revoke, and no injection/IDOR/SSRF/auth-bypass.

- **LOW (fixed before close):** `invite_list` sliced `[:200]` over an over-broad DB
  prefilter *before* the authoritative `can_issue_invite` Python filter, so a yard
  admin flooded with out-of-scope bridge-pod invites could have in-scope ones pushed
  out of the window (a display-completeness edge, never a leak). **Fixed:** the
  candidate query is now scoped exactly (`filter(pod touches actor yards).exclude(pod
  touches a yard outside)`) before the slice, with `can_issue_invite` kept as
  defense-in-depth. Pinned by `test_invite_list_excludes_bridge_pod_invites_from_a_yard_admin`.
- **INFO (on the record):** the admin-only mint endpoint carries no rate limit (the
  public `/join` redemption does). Acceptable — minting is gated to the two admin
  roles and creates DB rows, not a guessable-token oracle. Deliberate asymmetry.

## Live repro on the running compose stack (through Caddy, fresh volumes)

`docker compose up --build` on a clean `down -v`; web + worker + caddy + postgres all
healthy, reached on the published loopback port. The full delegated-onboarding
round-trip, end to end:

| # | Step | Result |
|---|---|---|
| 1 | `GET /healthz` | `200` |
| 2 | First-run setup secret (TM-8 console only) | 43-char token read from the web console |
| 3 | `POST /setup/` (creates admin + first yard+pod, auto-login) | `302 → /` |
| 4 | `GET /members/invite-household/` | intent nonce + the admin's yard option rendered |
| 5 | `POST` create "The Davis family" in one flow | `200`, minted `/join/<token>/`, inline `<svg>` QR present |
| 6 | Fresh person `GET`+`POST /join/<token>/` | `200` then `302 → /`; `GET /feed/` `200` (already inside a pod, no setup screen) |
| 7 | `GET /members/invites/` as admin | ledger shows "Aunt Rose" joined + the household |
| 8 | Anonymous `GET /members/invite-household/` | `302 → login` (refused) |
| 9 | `POST` revoke, then re-fetch the link | revoke `302`; link after revoke `404`; unknown token `404` (byte-parity) |

This proves all three S-201 acceptance criteria live — one-flow pod creation, invitees
land already inside their pod, no invitee ever sees a create-a-community screen — plus
the hardening: revocable link, admin-visible join ledger with who-joined-and-when.

## Cleanup

The compose stack and its volumes are torn down after this receipt (`docker compose
down -v`); the throwaway test Postgres used for the local gate is removed. No ephemeral
infra persists. Secrets stay in 1Password (`op://Backyard/…`), never in the repo.

## Result

**S-201 → tested.** With this, the v1 cut stands at 32/34 tested; the two remaining
built stories are S-301 (og:image re-hosting through the media pipeline) and S-101
(feed-landing redirect + mobile e2e harness).
