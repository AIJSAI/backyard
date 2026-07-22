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
  - **Clears the digest confirm/unsubscribe tokens** — the one bearer class that is NOT
    generation-anchored (`digesting._by_token` matches the digest only), cleared like the
    revocation registry but without disabling the subscription (a preference, not a
    credential). Folded from the security review (see below).
  - All in one transaction, so a partial restore never leaves some credentials live; and a
    replay failure raises a loud `BackupError` ("DATABASE RESTORED but replay did NOT
    complete — rotate by hand") rather than leaving live credentials silently.
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

## Review panel (security-reviewer, no CRITICAL/HIGH)

One MEDIUM, folded: the hand-rolled replay missed two of the eight bearer-credential
classes the revocation drill enforces — the **digest confirm + unsubscribe tokens**
(`DigestSubscription.confirm_token_digest` / `unsubscribe_token_digest`), which are cleared
by the registry, not generation-anchored, so the bump alone left them live (a real re-arm
path: an expelled member re-confirms their restored subscription). Fixed by clearing the
two columns in the replay, and — the reviewer's stronger recommendation — added an
**equality drift-guard** (`test_restore_forced_security_replay_kills_every_registered_class`)
that seeds all eight classes via the existing revocation drill and asserts the replay kills
every one, so a future credential class can never be silently omitted here. LOWs folded:
the completeness claims (docstring / receipt / threat-model / command checklist) now name
the digest tokens, and a replay failure surfaces loud, actionable guidance. Sound otherwise
(fail-closed execution, rotation correct across the restore, no admin lock-out — break-glass
is the independent recovery path).

## Files

`src/core/backups.py` (`_forced_security_replay` + `restore_backup` call/return),
`src/core/management/commands/restore_instance.py` (checklist),
`src/core/tests/test_backups.py` (2 tests), `stories/stories.yaml` (S-802 note),
`docs/security/threat-model.md` (T-OP-G5).
