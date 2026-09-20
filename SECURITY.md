# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| `v0.2.0` | ✅ current |
| `v0.1.8` | ⚠️ superseded — installable and safe; `v0.2.0` adds profile photos, the phone-width feed and Get The App (one additive migration) |
| `v0.1.7` | ⚠️ superseded — installable and safe; `v0.1.8` fixes the photo button on an empty composer |
| `v0.1.6` | ⚠️ superseded — installable and safe; `v0.1.7` lines the mail header up in Gmail |
| `v0.1.5` | ⚠️ superseded — installable; `v0.1.6` builds the mailed confirmation and reset links from the configured site address (CHANGELOG, Security) |
| `v0.1.4` | ⚠️ superseded — upgrade to `v0.2.0`: `v0.1.5` stopped an address being confirmed by anybody but its own signed-in account, which also gates password reset and Email Updates (CHANGELOG, Security) |
| `v0.1.3` | ⚠️ superseded — installable; upgrade to `v0.2.0`; the Security fixes in `v0.1.5` apply to every earlier tag |
| `v0.1.2` | ⚠️ superseded — installable; upgrade to `v0.2.0`; the Security fixes in `v0.1.5` apply to every earlier tag |
| `main` | ⚠️ moving target — fixes land here first, but it may be mid-refactor when you arrive |
| `v0.1.1` | ⚠️ superseded — installable, but its README's own install command fails; use `v0.2.0` |
| `v0.1.0` | ❌ withdrawn — superseded by `v0.2.0`; do not install |

`0.x` carries no stability promise. Security fixes go to `main` and into the next tag; there
is no backporting, because there is nothing to backport to.

## What you should know before trusting it

Stated plainly, because this software holds families' photographs:

- **No independent security review has happened.** The [threat model](docs/security/threat-model.md)
  is thorough and entirely self-authored. One person's blind spots are in it, by construction.
- **One instance has ever been deployed**, by the author.
- The [changelog](CHANGELOG.md) lists what does not work, including one manual step that
  reply-by-email needs or replies are accepted and silently dropped.

## Reporting a vulnerability

Use GitHub private vulnerability reporting (Security tab, "Report a vulnerability") on this
repository. Do not open public issues for security problems.

**This is one person, not a security team.** Expect an acknowledgment within about a week —
that is an honest figure rather than a reassuring one, and if a project this size promised you
72 hours you should not believe it. If something is actively exposing a family's data, say so
in the first line and it jumps the queue.

## Scope notes

This is family software. Anything touching the no-login elder token links, media privacy, pod isolation, or data export is security-relevant. Reports in those areas are welcome even if they feel like design nits.
