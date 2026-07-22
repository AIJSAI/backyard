# S-707 + S-708 close: the seed-ally rollout enablers (appoint a delegate, create a family side)

Date: 2026-07-22. Stories **S-707** (appoint a delegate / grant a second instance admin)
and **S-708** (create the other family side), epic E7. Branch
`feat/s707-s708-rollout-enablers` off `main`. This is the first Phase-3 slice, ratified by
the founder, and it turns "the family social network is built" into "the family can be
onboarded onto both sides without the founder at a shell." Every claim below is run.

## What shipped

- **`permissions.administrable_members(actor)`**: the members an admin may administer. The
  instance admin owns the instance and sits ABOVE yard isolation, so they administer every
  member — including those on a family side they are not a member of, which the seed-ally
  rollout requires. A yard admin administers only the yard-scoped visible set, so resolving
  a member through it keeps the byte-identical 404 for a cross-yard target (S-202). The
  roster, `assign_role`, `remove`, and `provision_elder` all resolve members through it;
  `can_manage_member` still gates the action.
- **`admin_views.assign_role`** (S-707, POST-only): appoint a per-side delegate (yard admin)
  or a second instance admin (bus-factor). The role string is whitelisted
  (`_ASSIGNABLE_ROLES`, supervised excluded) BEFORE use and then authorized by
  `can_assign_role`, so a yard admin can only re-role an in-scope member to a non-admin
  role, no one re-roles themselves, and there is no privilege inversion.
- **`admin_views.family_sides`** (S-708): instance-admin-only create-a-yard, refresh-safe via
  the single-use intent nonce, name bounded and slugified to a unique slug. It does not
  reopen the TM-8 first-run wizard.
- **`invite_household` extended**: an instance admin's yard-picker is every yard and the POST
  resolves any yard, so they can stand up the first household in a brand-new empty side; a
  yard admin is unchanged (their own yards only, `can_issue_invite` still the gate).
- Roster role-control (`members.html`) + `family_sides.html`; S-707/S-708 added to the story
  tracker (`check_stories` green).

## Full verification gate (never a subset)

`ruff` + `ruff format --check` + `mypy` (129 files) + full `pytest` (**494 passed, 2 e2e
deselected** in the browser-free run) + `docker build` (web + worker). New tests: a full
`test_rollout_enablers.py` (12) covering create-side (instance-admin-only, refresh-safe,
name required), assign-role (appoint yard admin, grant 2nd instance admin, yard-admin
in-scope-only + no-admin-grant, cross-yard 404, whitelist + supervised rejection, POST-only,
no self-role-change), and the end-to-end seed-ally journey.

## Security review (roles/grants + an instance-wide-admin scope change — highest-risk class)

A `security-reviewer` pass traced the full diff, both changed views, the authorization
model, and the 12 adversarial tests. **Verdict: clean, no CRITICAL/HIGH.** All eight
properties confirmed: the role string is whitelisted before use and `can_assign_role`-gated
(a yard admin can never grant an admin role, no privilege inversion, no self-administration);
`administrable_members` returns exactly `visible_members` for a yard admin, so the S-202
byte-identical 404 for a cross-yard target is preserved and no other call site was changed;
the instance admin's instance-wide reach is correctly bounded (nothing new exposed to a
non-instance-admin); `family_sides` is instance-admin-only, refresh-safe, and injection-free
(escaped name + slugified slug); the `invite_household` extension keeps `can_issue_invite` as
the authoritative gate; CSRF + POST-only hold. Findings, all conscious-accepts (no fix):

- **MEDIUM (by-design):** two co-equal instance admins can demote or remove each other,
  including the founder — the natural meaning of co-equal admin. No lockout-to-zero is
  reachable (self-demote is blocked). The mitigation is the intended design and the founder's
  ratified framing: per-side delegates get `yard_admin` (which the rollout uses); reserve an
  `instance_admin` grant for genuinely trusted succession/bus-factor.
- **LOW:** `_unique_yard_slug` is check-then-create against a unique slug; two concurrent
  creates could race to an `IntegrityError`→500 (unreachable for a single admin behind a
  per-session nonce; the same helper the setup wizard uses). `assign_role` reads then updates
  without `select_for_update`; the only reachable racy outcome is a demote, never an
  escalation. Neither is worth serializing at family scale.
- **Informational (consistency, not a hole):** `create_supervised` still resolves its parent
  yard-scoped, so an instance admin cannot create a supervised child on a side they have not
  joined — *more* restrictive than the other member actions, no security impact, and the
  per-side delegate covers their own side. Tracked as a minor follow-up, not a blocker.

## Live repro on the running compose stack (through Caddy)

`docker compose up --build` on fresh volumes. The whole seed-ally handoff, curl-driven:

| # | Step | Result |
|---|---|---|
| 1 | `GET /healthz` | `200` |
| 2 | Bootstrap the instance admin | `302` |
| 3 | Create the other family side (S-708) | `302`; both Mom side and Dad side listed |
| 4 | Invite the first household **into the new side** | Dad side offered in the picker; `POST` invite `200`; 43-char token minted (instance-admin operates instance-wide) |
| 5 | Uncle Chris redeems | join `POST 302 → /feed/` — lands in the Fox household on Dad side |
| 6 | Instance admin promotes Chris (S-707) | role `Member` → `Yard admin` on the roster |
| 7 | The delegate is self-sufficient | Chris logs in `302`; `invite-household` `200` (his side); `family-sides` **`403`** (instance-admin only) |

This proves the founder can stand up the second family side, invite its first household,
and hand it to a per-side delegate who then onboards the rest — with zero shell.

## Cleanup

The compose stack + volumes and the throwaway test Postgres are torn down after this
receipt.

## Result

**S-707 and S-708 → tested.** The seed-ally rollout's starting position is now
executable in-product. Next Phase-3 slice: S-213 (onboard a net-new elder) + S-212
(hand-over UX + resend).
