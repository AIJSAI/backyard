# Full design-system + visual/UX pass (S-720) — close receipt

Date: 2026-07-22. Phase 3, **step 4** of the founder-refined goal sequence: the full design
system and visual/UX pass across every surface, done via Claude's design tooling, after the
flows (steps 1–3) were finished. Satisfies [PATH-TO-100](../PATH-TO-100.md) close-criterion 3.

## What this is (and is not)

A **presentation-only** pass: it gives Backyard one coherent, warm, elder-first visual
identity, applied to every surface. It changes CSS, page chrome, and a few class hooks — **no
view logic, no models, no auth/visibility/moderation behavior, no URLs, no email wiring.** The
member app previously shipped with ~13 lines of inline base CSS and a set of unstyled semantic
class hooks; those hooks are now a real design system.

## The design direction (grounded, not invented)

Grounded in the product principles and the subject itself — the name *Backyard*,
`backyard.family`, and the existing `#2f5d3a` theme colour:

- **Calm over engagement** (principle 1): quiet colour, generous rhythm, the feed visibly
  *ends* (a `❧` end-cap, a hairline "new since" divider that reads as a boundary, not an alert).
- **Warm / garden / golden-hour** identity: warm paper ground + deep garden green + a sparing
  golden-ochre accent in light; a "dusk in the yard" warm-charcoal + lightened-foliage palette
  in dark. Both themes fully designed (not a naive invert).
- **Elder-first** (principles 5–6): the standalone elder path keeps its **maximum-contrast**
  reading surface (black serif on white, the ratified ≥17:1 pin) and only takes on the warm
  identity through green *accents* — legibility is never traded for looks.
- System-font stacks only (a warm serif for headings echoing the elder Georgia, a humanist
  sans for UI): `font-src` is `'self'` (CSP S-724) and the app ships no static dir, so webfonts
  are neither available nor wanted (fast loads on any device). **No CSP or Python change.**

## What shipped

- **`base.html`**: a token-driven design system (light palette + a full dark override) covering
  every component the 32 base-extending templates render — page frame (skip-link, brand header,
  `<main id="main">`, footer), forms/buttons (primary / secondary / danger, 44px targets), feed
  & post cards, composer, notices/errors, flags & role pills, media & link previews, reactions,
  admin lists & tables, the hand-over/QR block, empty/boundary/caught-up states. Accessibility
  baked in: a visible `:focus-visible` ring on every control, `prefers-reduced-motion`, a print
  stylesheet, semantic landmarks + a skip link. The authenticated-only PWA `<head>` block and
  the nonce'd service-worker `<script>` are preserved unchanged.
- **`elder_feed.html`** (standalone token surface): warmed to the identity via green accents
  (buttons, top rule, back link, focus ring) while the reading surface stays black-on-white; the
  `26px`/`21px` big-text logic, single-column shape, 48px targets, and no-service-worker /
  no-off-surface-link guarantees are all intact.
- **`email/digest.html`**: palette harmonised (warm serif, green links) — **style attributes
  only**; the `{{ separator }}` quoted-tail anchor, reply-address, unsubscribe URL, and every
  variable are untouched.
- Small markup hooks: `class="inline-check"` on the two checkbox labels; `class="danger"` on the
  seven destructive buttons (Take down / Remove / Revoke / Delete) for an accessible destructive
  affordance. No logic moved.

## Verification (full gate + live-repro + non-vacuous a11y proof)

- **ruff** clean · **ruff format** clean · **mypy --strict** clean (136 files) ·
  **`manage.py check --deploy --fail-level WARNING`** clean.
- **pytest: 541 passed**, 8 e2e deselected (baseline before this pass was 539; +2 is the new
  WCAG guard). The 98 template-render assertions (which bind to copy, not CSS) all still pass —
  three self-inflicted collisions were caught and fixed *by the suite*: an inline CSS selector
  leaking `type="checkbox"` into a structural count guard, and a CSS comment leaking "New since
  your last visit" into a first-visit absence assertion (both root-caused to the inline `<style>`
  emitting test-matched strings; fixed by unquoting attribute selectors and rewording comments).
- **Required `e2e` job run locally: 8 passed** — the S-101 mobile onboarding flows on **iOS
  Safari (WebKit)** and **Android Chrome (Chromium)** still pass through the changed shared DOM.
- **New non-vacuous WCAG guard** (`test_design_system_wcag.py`): parses the real token palette
  from `base.html` and computes the WCAG contrast ratio for **17 text/background pairings in
  both themes**, asserting AA (≥4.5:1); it ships with a guard-the-guard test (a bad pairing must
  fail) so a future theme edit can't silently drop below AA. It **caught a real defect** during
  this pass — amber-on-amber-tint at 3.89:1 — which was fixed to 5.29:1. This mirrors the elder
  view's existing pinned-contrast test, extended to the whole system.
- **Live-repro (visual):** the member-app design was rendered from the **exact CSS extracted
  from `base.html`** and screenshotted at desktop (light + dark side by side) and 390px mobile
  (mobile-first reflow confirmed — no horizontal overflow, comfortable targets); the **elder
  feed was rendered through the real Django template engine** and screenshotted (regular + big
  text). A viewable specimen artifact was published for the founder's manual-QA gate (step 6).

## Security review

security-reviewer run on the diff (mandatory on token/email/roles surfaces, even for a cosmetic
pass). **Verdict: CLEAN — no CRITICAL/HIGH/MEDIUM/LOW.** It confirmed: no `|safe`/`mark_safe`/
inline-handler/raw-render added (autoescape + nonce-CSP second net intact); the SW `<script>`
nonce and `{% if user.is_authenticated %}` gating preserved (ADR-002 Safari-eviction rule holds
on the `/d/` surface); the new brand link leaks no token — the TM-5 `no-referrer` posture is set
**server-side** in `middleware.py`, which a markup change cannot alter, so a click from a
forwarded digest link sends no Referer; the elder surface stays standalone, worker-less, with its
only href the elder feed; the digest email change is purely cosmetic (separator / reply-address /
unsubscribe / URLs textually unchanged); and `class="danger"` was added only to buttons already
inside their pre-existing `is_moderator` / author-ownership / admin authorization guards.

## Scope boundary / what is intentionally NOT here

- This does not stand up the persistent instance (step 5, founder-provisions the Ubicloud VM +
  domain) or perform the founder's manual QA (step 6). Those remain founder-gated.
- The v1 stories stay `tested`, not `passing`: `passing` requires receipts against the
  *persistent* live instance (step 5), which this pass does not change.

## Files

`src/core/templates/core/base.html`, `elder_feed.html`, `email/digest.html`, `feed.html`,
`post_detail.html`, `members.html`, `members_invites.html`, `delete_confirm.html`,
`notification_settings.html`; new `src/core/tests/test_design_system_wcag.py`.
