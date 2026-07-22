# S-727 TM-7 restore forced-security-replay — close receipt

Date: 2026-07-22. Phase 3, step 3 (pre-share safety debt). Closes the gap the Phase-2 retro
flagged: **the TM-7 / T-OP-G5 restore forced-security-replay was never implemented** — the
"security replay" the S-802 receipt named was actually the tar-path-escape guard
(crafted-archive rejection), a different control. So a restore could resurrect a revoked
token or an expelled ex-partner's live elder link. This matters before real families and
children.

## What shipped

- **`backups._forced_security_replay()`**, called at the end of `restore_backup`, returns a
  summary. It:
  - **Bumps `Member.token_generation` for every member.** Every generation-anchored bearer
    credential the backup carried is instantly invalid: elder token links, digest deep-links,
    and reply-by-email addresses each verify `minted_generation == member.token_generation`
    on resolve, so one bump kills them all at once (ADR-003).
  - **Flushes all sessions** — the elder and web sessions that carry no generation-checked
    row — forcing re-authentication.
  - **Voids every outstanding invite** — a restored `/join` link is a replayable bearer
    credential too.
  - All in one transaction, so a partial restore never leaves some credentials live.
  Everything is re-issuable: the admin re-provisions only members who should still have
  access and re-issues invites as needed.
- **`restore_instance` prints the security-replay checklist** — the rotation counts, plus
  the human half no code can automate (T-OP-G5): *any member removed after this backup, and
  any content deleted after it, has been restored — remove them again now; the restore
  cannot know what postdates it.*
- **Reconciled the record:** the S-802 story status note (which mislabeled the tar-escape
  guard as the "security replay") and the threat-model T-OP-G5 row now record that the real
  replay is implemented, distinct from the tar-escape guard.

## Verification

- ruff + mypy(strict, 135 files) clean; **534 unit** (+2 `test_backups.py`) + 8 e2e + stories
  gate green.
- Unit tests: `_forced_security_replay` bumps the generation, kills a live elder token
  (`resolve` raises), flushes the session, voids the invite, and returns the exact summary;
  and — the **load-bearing property** — a full `restore_backup` run leaves an ex-partner's
  elder link that the backup carried **dead, not live**
  (`test_restore_runs_the_security_replay_so_an_expelled_link_cannot_be_resurrected`).
- **Live drill (running compose stack, through Caddy):** seeded a live elder link, confirmed
  `GET /t/<token>/` → **302** (live); ran the forced-replay
  (`{members_rotated: 1, sessions_flushed: 1}`); the SAME link then returned **404** (dead).
  The expelled-ex-partner resurrection path is closed on the real instance.

## Files

`src/core/backups.py` (`_forced_security_replay` + `restore_backup` call/return),
`src/core/management/commands/restore_instance.py` (checklist),
`src/core/tests/test_backups.py` (2 tests), `stories/stories.yaml` (S-802 note),
`docs/security/threat-model.md` (T-OP-G5).
