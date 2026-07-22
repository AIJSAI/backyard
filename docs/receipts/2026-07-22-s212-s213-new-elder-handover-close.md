# S-213 new-elder + S-212 hand-over/resend — close receipt

Date: 2026-07-22. Phase 3, slice 1 (flows-first). Closes the two remaining rollout-flow
gaps from the Phase-2 retro (§5a): a delegate can now onboard a net-new grandparent onto
the no-login elder path (S-213), and the invite hand-over has a fast copy/share plus a
re-issue-a-fresh-link path (S-212) — both entirely in-product, no shell.

## What shipped

- **S-213 create-new-elder (`new_elder`, `core/provisioning_views.py`).** A delegate names
  a net-new elder and picks a side; their household pod, a token-only member (no `User`,
  non-supervised), and their elder token are created in one atomic flow, and the hand-over
  link + printable QR are shown once. Delegate-usable and scoped exactly like a household
  invite: the yard picker + the authoritative in-transaction `can_issue_invite(pod)` gate
  give an instance admin any side (incl. one they are not a member of, for the seed-ally
  rollout) and a yard admin only their own (T-AUTH-G2). The elder's whole visibility is
  that household's side — a subset of the acting admin's authority — so no yard admin can
  stand up an elder who sees a side they do not control. Refresh-safe (intent nonce). Route
  `GET/POST /members/new-elder/`, linked from the roster ("Add a grandparent").
- **S-212 resend (`resend_invite`, `core/admin_views.py`).** From the outstanding-invite
  ledger, an admin mints a fresh one-time link for a household whose earlier link expired,
  filled, was revoked, or needs another copy. Additive (the prior invite is left untouched
  — it may still be live in someone's hands); authorized/404'd exactly like issue and
  revoke (`can_issue_invite` over the invite's pod, byte-identical 404 for out-of-scope /
  unknown, S-202 parity); POST-only. Route `POST /members/invites/<id>/resend/`.
- **S-212 hand-over UX (`_handover_artifacts.html`).** One shared partial — the one-time
  link field, a one-tap **copy**, a native **share**, and the inline QR — reused by the
  household invite, the elder link, the new-elder flow, and the resend result. Copy/share
  are a progressive enhancement: they reveal only where the browser supports the APIs and
  degrade to the selectable field + scannable QR, so the flow never depends on them.
- **Stories.** S-213 and S-212 added to `stories/stories.yaml` (epic E7), `status: tested`.

## The security-header defect this slice's browser e2e uncovered (and fixed)

The new cross-browser mint e2e is the first time the admin hand-over **form** and the elder
**react** form were ever driven by a real browser. They failed:

```
Forbidden (Origin checking failed - null does not match any trusted origins.): /members/new-elder/
```

Root cause: `Referrer-Policy: no-referrer` was set on these surfaces — at the **app** layer
(the TM-5 hand-over header set; `TokenSurfaceHeadersMiddleware` for `/e/`) **and globally at
the Caddy edge**. Per the Fetch spec, `no-referrer` forces the browser to send `Origin:
null` on a same-origin form POST, and Django's CSRF Origin check rejects it. So **every form
was broken in a real browser on the deployed compose stack** — join, household invite,
new-elder, elder one-tap react, digest confirm/unsubscribe, break-glass. It stayed latent
because every prior "live-repro" used **curl** (sends no Origin → CSRF passes) or the
**live_server** fixture (no Caddy); the memory even recorded the symptom
("browser form-POST CSRF-403s on plain-HTTP compose loopback") but misattributed it to
plain-HTTP rather than this root cause. This is exactly the false-green class the Phase-2
retro flagged: "proven live" that skipped the real browser + edge combination.

Fix — the **app is the single source of truth** for `Referrer-Policy`, per surface:

- **`same-origin` floor** everywhere (`SECURE_REFERRER_POLICY`, pinned explicitly in
  settings). It leaks nothing cross-origin (a token in a URL never reaches a third party)
  while sending the same-origin Origin the CSRF check needs, so **all forms work**.
- **`no-referrer`** kept only on the token-in-URL surfaces that have **no form** and where a
  same-origin Referer could carry the URL-token: `/t/`, `/d/`
  (`TokenSurfaceHeadersMiddleware`, split from `/e/`) and `/media/` (`serve_media`). `/t/`
  is the load-bearing case — it prevents the token riding the `/t/`→`/e/` redirect's
  `Referer` (gunicorn access logging is deliberately off, so nothing else logs it either).
- **`same-origin`** on the interactive surfaces: `/e/` (elder session; middleware), the
  `/members/` hand-over pages (`handover.apply_token_body_headers`, a new shared helper so
  the invariant lives in one documented place).
- **The Caddy edge no longer forces `Referrer-Policy`** (active block **and** the
  production-example template, so real deployers don't reintroduce it). A global
  `no-referrer` at the edge would override the app's per-surface value and re-break every
  form.

Net cross-cutting effect: join / digest / break-glass forms — broken in a real browser on
the deployed stack for the same reason — are now unblocked too.

## Verification gate (all green)

- `ruff check src` + `ruff format --check src`: clean.
- `mypy src` (strict): `Success: no issues found in 130 source files`.
- `pytest` (unit, `-m 'not e2e'`): **514 passed**, 6 deselected. (+ the S-213 suite
  `test_new_elder.py`, the S-212 resend + copy/share tests, and the middleware header-split
  guard `test_elder_feed_surface_uses_same_origin_but_token_url_keeps_no_referrer`.)
- `pytest -m e2e` (WebKit = iOS Safari, Chromium = Android Chrome): **6 passed** — join→feed,
  admin mint+hand-over→redeem→feed, and new-elder mint→open→**one-tap react**, on both
  engines.
- `scripts/check_stories.py`: `gates: PASS`. `scripts/check_digest_confinement.py`: OK.
- `manage.py check --deploy --fail-level WARNING` (production-like env): 0 issues.

## Live-repro (running compose stack + real browser through Caddy)

Bit-for-bit the path that was never tested before:

1. **Header split through Caddy** (curl, after the edge fix): `/t/`→`no-referrer`,
   `/d/`→`no-referrer`, `/e/`→`same-origin`, `/join/`→`same-origin`,
   `/members/new-elder/`→`same-origin`, `/members/invite-household/`→`same-origin`.
   (Before the fix, Caddy forced `no-referrer` on all of them — captured during diagnosis.)
2. **Real browser THROUGH the Caddy edge** (`http://localhost:8000`, Chromium): an instance
   admin drove the `/members/new-elder/` mint **form** (its CSRF Origin now accepted),
   received the hand-over link, then the elder opened `/t/<raw>/` → `/e/`, saw the family
   post in large text, and **tapped react** (its POST accepted). Full new-elder mint +
   hand-over + elder react in a real browser through the real edge — PASS.

## Files

Views/logic: `provisioning_views.py` (new_elder), `admin_views.py` (resend_invite),
`handover.py` (apply_token_body_headers helper), `middleware.py` (Referrer-Policy split),
`config/urls.py`, `config/settings.py` (SECURE_REFERRER_POLICY). Edge: `caddy/Caddyfile`.
Templates: `_handover_artifacts.html`, `new_elder.html`, `handover_link.html`,
`invite_household.html`, `provision_elder.html`, `members.html`, `members_invites.html`.
Tests: `test_new_elder.py`, `test_invite_household.py`, `test_onboarding_mobile.py`,
`test_elder_tokens.py`, `test_provisioning.py`. Stories: `stories/stories.yaml`.
