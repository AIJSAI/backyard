# Wave B: the silent-failure cluster

Date: 2026-07-27. Branch `feat/wave-b-silent-failures`. Closes four findings from
[the honest 100% audit](../audits/2026-07-26-honest-100-audit.md) — two BLOCKER, two HIGH.
They share one shape: **the product failed and told nobody.** A member or an operator was
shown success while something was quietly lost.

Every claim below is measured against a running instance, never asserted.

## 1. BLOCKER — photos + a yard audience silently discarded the media

The TM-3 confirm-on-widen page is an ordinary form with no `enctype` and no file inputs,
and the view returned it **before** `_attach_photos` ran. The re-POST therefore arrived
with an empty `request.FILES` and the post was created with zero media and no error.
"Camp dump, finally", aimed at a whole side of the family — the single most valuable post
type in the product — silently became a caption.

Files cannot survive a round trip through a browser form, so `core/staged_uploads.py`
holds the validated bytes server-side and the member carries only an opaque handle:

- names are server-generated (`secrets.token_urlsafe`), so the uploaded filename is never
  used for anything and there is no path traversal to reason about;
- the manifest lives in the **server-side** session, so a handle lifted from one member's
  form names nothing in another member's session;
- a claim **consumes** the bytes, so a replayed confirmation cannot clone photos onto a
  second post;
- a daily sweep walks the staging directory **by mtime**, so an abandoned confirmation —
  including one whose session has expired — cannot leave family photographs on disk.

**Live repro** (running compose instance, real multipart upload, confirm sent with no
files exactly as a browser does):

```
=== 1. compose WITH photo + yard audience -> confirmation page ===
  -> 200
  page says: will be posted too
  staged handle: pwoMxITKhG...
=== 2. confirm (NO files in this request, exactly like the browser) ===
  -> 302
=== 3. did the photo actually land on the post? ===
  post id: 162 | yards: ['wavebrepro']
  MEDIA ATTACHED: 1
  staging dir now: []
```

## 2. BLOCKER — "bring your own SMTP" was impossible

`settings.py` reads all six `EMAIL_*` variables. **Neither compose file passed any of
them**, and compose's `.env` is substitution-only, so they could not reach the container
at all. An operator who set `EMAIL_BACKEND=...smtp.EmailBackend` hit the boot guard's
"EMAIL_HOST is empty" and crash-looped with nothing explaining why. The only reachable
transport was a hosted SaaS account — against a README that promises the opposite.

**Differential proof** — identical operator config, the only difference being the fix:

```
=== A. after the fix ===
  backend : django.core.mail.backends.smtp.EmailBackend
  host    : smtp.example.com port 587
  BOOTS OK — the boot guard is satisfied

=== B. the SAME config on main (before) ===
  CRASH-LOOP: Outbound email transport misconfigured: EMAIL_HOST is empty.
```

A new guard fails the build if a setting read from the environment is not passed into
**both** mail services, mutation-proven: deleting `EMAIL_HOST` from the worker block fails
with `assert not ['worker.EMAIL_HOST']`. `.env.example` documents a worked SMTP example
and the honest limitation the README commits to — **inbound reply-by-email is Resend-only
today**; with SMTP alone the digest still sends and replies happen on the web.

## 3. HIGH — the feed hard-stopped at 100 posts and then lied about it

`[:100]` with no pagination, no archive route, under an **unconditional** "You are all
caught up." A ~40-person family passes 100 posts in a few months; from that moment the
product amputated its own history and told the member they had seen everything. That also
breaks the archive promise the whole S-803 upgrade guard exists to protect: the data
survives every migration and is then unreachable in the product.

Keyset pagination on `(created_at, id)` — not OFFSET, so paging stays cheap and cannot
skip or repeat a post when a new one lands mid-read. Paging back does **not** advance the
unread boundary: going to look at Grandpa's birthday post must never silently mark
everything new above it as seen (S-303).

**Live repro**, 130 posts seeded:

```
=== 1. FEED (page size 100) ===
  'You are all caught up.' present: 0  (must be 0)
  'Show older posts' present   : 1  (must be 1)
  newest / oldest on page 1    : bpost-129 / bpost-030
=== 2. ARCHIVE PAGE ===
  oldest bpost on page 2       : bpost-000  (must be bpost-000)
  'You are all caught up.'     : 1  (must be 1 — the real end)
```

Writing the hostile-cursor test caught a **second, real defect**: a malformed cursor went
through `_int` and **404'd the member's own feed**. It now degrades to page one.

## 4. HIGH — the one notification opt-in was a dead toggle

`notify_on_reply` was written by the settings page and read by nowhere. The member ticked
"Tell me when someone replies to my post", waited, and got silence indistinguishable from
nobody having replied.

Web push stays post-v1 (ADR-002); the nudge goes out as **email** over the existing Anymail
path, gated on the same one boolean. S-305 is a negative guarantee and this honours it:
four conditions all required — opted in (default False), a reply on your own post that is
not your own, an address **confirmed through the digest double opt-in** (T-EMAIL-6, so a
nudge is never the first mail to an unverified inbox), and a replier still visible to you,
re-resolved live at send time. The mail carries **no reply text and no photograph** — a
notification that quoted content would be a second content path around the audience query.

Fired from `create_comment`, not the two call sites, so the opt-in cannot be honoured on
the web route and forgotten on the inbound-email one.

## Also found while testing

`DATA_UPLOAD_MAX_NUMBER_FILES` was **20 — equal to the composer's own photo cap** — so 21
photos hit Django's parser first and the member got a bare **400** rather than the
composer's explanation. Raised to 40: the application should be the thing that explains
itself. This also means the audit's ">20 silently truncated" was only half right; the
reachable silent drops were the size cap and undecodable files, and both now speak.

## Security review — 6 blocking findings, all closed

An adversarial pass live-reproduced **five of six probes** against the first cut. Two of
them **reintroduced the exact silent-data-loss failure this branch exists to eliminate**,
one boundary further along — which is the strongest argument for the review existing.

| # | Sev | Finding | Fix |
|---|-----|---------|-----|
| 1 | HIGH | Caps applied per-request, **not to the merged claimed+new list** — looping the error path piled **60 photos on one post** and held every raw in memory against a 768 MB container | Caps re-applied after the merge |
| 2 | HIGH | `unsubscribe()` flips `enabled` and leaves `confirmed_at` intact, so the one-click unsubscribe silenced the digest **but not the nudge** — unstoppable mail for an address-only member | Gated on `enabled`, re-queried live; every nudge carries its own unsubscribe link |
| 3 | HIGH | A claim that came up short was **silent** — a sweep crossing the TTL mid-hesitation gave `MEDIA: 0, MESSAGES: ''` | The shortfall is part of the `Claim` value and is said out loud |
| 4 | HIGH | The SMTP send ran **inside the member's write transaction**; a hung mail server outruns gunicorn's timeout → worker killed → **the reply is destroyed** | Deferred to the worker on commit |
| 5 | HIGH | 6h TTL swept **once daily** (~30h real retention), no quota anywhere | Hourly sweep, per-session byte budget with oldest-first eviction, manifest pruning |
| 6 | MED | `str.isdigit()` accepts codepoints `int()` rejects → `?before=..._²` returned a **500 on a one-click GET** | The parse decides, with a bigint bound |

Also closed: Cancel was a bare link (`discard()` had zero callers and the comment claiming
otherwise was false) — now a POST that releases immediately; and the staging docstring
claimed photos were validated before reaching disk, when only videos are.

**Re-verified after the fixes:** the reviewer's own probe files go from 5-of-6 failing to
6-of-8 passing. The two that still fail model the *old* architecture (an inline send, a
GET-based cancel); both underlying properties were re-checked directly — CRLF in a display
name is still neutralised on the deferred path (`'SamBcc: attacker@evil.example replied to
your post'`, single-line).

## Full verification gate

`ruff check` + `ruff format --check` + `mypy` (**146 files, no issues**) + full `pytest`
(**613 passed**, 8 deselected). Never a subset.

## Still open from the audit (NOT closed here)

- **S-502's production webhook is still unregistered** — an ops step needing the Resend
  console and the prod `RESEND_INBOUND_SECRET`, plus the separate hole that `BOUNCE_TEXT`
  is built and never sent. Until it is registered, SES accepts a reply with a 250 and the
  message is never delivered to the app: no bounce, no error, total silence.
- The audit's remaining blockers (S-702 content choice, S-802 plaintext backups, S-901
  profiles, S-103 PWA identity, the install/self-host guide) are untouched.
