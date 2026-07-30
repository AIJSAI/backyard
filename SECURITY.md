# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| `v0.1.0` | ✅ current |
| `main` | ⚠️ moving target — fixes land here first, but it may be mid-refactor when you arrive |
| anything earlier | there is nothing earlier; `v0.1.0` is the first tag |

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
