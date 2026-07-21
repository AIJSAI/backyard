# Wave 4 receipt: every buildable increment landed; the wave stays OPEN

Date: 2026-07-21. Main at `7c9a3a5`. This is a progress receipt, not a close:
wave 4 cannot close until its ADR-002 measurement gate runs against a real
provider (rule 6, measured never claimed). Everything that could be built and
proven without that decision has been.

## What landed: eight increments, PRs #33 through #40

All eight merged through the armed protection on green CI, with an isolated
security review folded before each merge and a scripted live repro on the
running compose stack through Caddy. Each PR's closing comment quotes its
review verdict, the folded findings, and the live-repro results, so every
per-increment claim below is checkable on the PR itself.

1. **#33 dates substrate (S-903).** Per-field birthday and anniversary
   visibility on the S-902 model; fixed a live gap where the birthday rendered
   to every directory viewer unconditionally; one date resolver feeds the quiet
   feed banner and, later, the digest. Review SOUND, 2 LOW folded.
2. **#34 email substrate.** One send path: fixed sender, standing anti-phish
   footer enforced on both parts, control-strip into headers, BASE_URL-only
   links, refuse-to-boot on cleartext or unknown transports. Review SOUND,
   1 MEDIUM + 3 LOW folded.
3. **#35 digest lifecycle (S-501).** Confirm-before-first-content: the
   confirmation email is composed from module constants plus the minted link
   and nothing else, and the suite asserts no member, pod, or yard name can
   appear in it. Two-step unsubscribe that never touches membership,
   transport-truth delivery panel, and the digest joins the revocation
   registry. Review: 2 MEDIUM + 3 LOW folded.
4. **#36 per-digest read links.** The /d/ surface where the token only
   authenticates and every render re-resolves through the one audience query;
   revoked-before-expired failure ordering; request-log token redaction ships
   in the same change as the first token-bearing route. Review APPROVE, 3 LOW
   folded.
5. **#37 the builder (TM-2 core).** A pure function; every content byte
   resolves through the guard at build time. The 100 percent family gate is
   enforced, not aspired to: every block type the digest can render is
   family-authored content on the instance's own origin, and an unknown block
   or off-origin link fails the build. A self-testing CI drift-guard confines
   digest.py to the guard. Review: 2 MEDIUM + 3 LOW folded.
6. **#38 send orchestration.** One send path, identifiers only, per-recipient
   atomicity with an in-transaction liveness re-check (revoked-mid-queue means
   zero emails), savepoint rollback so a refused send never kills the
   previously emailed unsubscribe link. Review: 1 HIGH + 2 MEDIUM folded, and
   the live repro caught a real bug the unit suite missed (per-email rotation
   killed the first of a bridge member's two emailed links).
7. **#39 reply-by-email (S-502).** Capability addresses with three independent
   kill clocks; bounded inbound parsing; the deterministic separator strip
   exercised against a four-fixture authored corpus of client quoting shapes
   (Gmail, Apple Mail, Outlook, bare client). The corpus is hand-written, not
   captured mail, and the live round-trip stays open below for exactly that
   reason. Byte-identical bounces; From is a consistency check that
   quarantines and never attributes. Review: no CRITICAL or HIGH on the most
   attack-facing surface of the wave; 3 MEDIUM + 4 LOW folded.
8. **#40 connection health (S-705).** Counts-only rollup, the yes/no weekly
   presence as the only per-person data point, an app-wide anti-surveillance
   sweep pinning the metric field sets. Digest opens are counted from the
   emailed link's first use, never a tracking pixel, and a grace window
   discounts mail-scanner prefetch hits. Review: 1 HIGH + 3 MEDIUM + 3 LOW
   folded, including order-independent presence for bridge members.

Test suite: 246 to 364 since the wave-3 checkpoint, full gate (ruff, mypy
strict, full pytest, docker build) green on every merge. The isolation suite
grew a request class at nearly every increment: digest rendering, /d/ links,
reply addresses, delivery rows, aggregates.

## Story flips

S-501, S-502, S-705, S-903 move `spec` to `built`. None flips to `tested`:
S-501's delivery-status promise and the wave itself wait on the measured
provider matrix; S-502's live round-trip waits on the mailbox. The wave-3
photo stories (S-401, S-403) remain `built` for the same reason on their own
gate.

## What blocks the close (founder or external, no code)

- **W4-B1:** choose the email transport (Postmark, Mailgun, SES, self-hosted
  Postal, or bare SMTP submission), create the account, set SPF, DKIM, and
  aligned DMARC on the sending domain, then MEASURE the ADR-002
  delivery-and-bounce matrix and commit the receipt. Anymail is one settings
  change behind the seam; the boot guard forces its arrival to be loud.
- **W4-B2:** the dedicated inbound mailbox and its credentials; the IMAP
  adapter is one thin class behind the MailSource seam, with its trust
  contract (envelope Delivered-To, local-part case) already written down.
- **W4-B3:** the Procrastinate worker container, which is wave 3's deliverable
  or arrives here if the founder ratifies the swap; until then the management
  commands drive the same functions and can run from cron.
- Wave 3's own gate (ffmpeg latency and RAM on target hardware) is unchanged.

The wave plan allows building 4 ahead of 3, and that is what happened: wave 4
landed ahead of wave 3's hardware-gated close, with digest photos degrading to
deep links and no digest-local media signer minted.
