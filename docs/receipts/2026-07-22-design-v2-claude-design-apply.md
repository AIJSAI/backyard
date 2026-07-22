# Claude Design system v2 applied (criterion 3) — close receipt

Date: 2026-07-22. Phase 3, **criterion 3** of the founder goal: the definitive design system,
**produced by Claude Design** (claude.ai/design) from the kickoff prompt
(`docs/design/claude-design-kickoff-prompt.md`), applied to the app and re-verified. The founder
ran Claude Design; this receipt covers integrating its output. Supersedes the S-720 baseline
(which existed as the functional substrate Claude Design built on).

## The identity Claude Design produced

**"The backyard at dusk."** A disciplined, modern system: **one brand colour — navy `#234a78` —
cool neutrals, and red reserved only for errors.** No decorative accents (the earlier tan/gold was
retired). Warm, calm, elder-first; legible to a 9-year-old and a 79-year-old at once. Mark:
**Homestead** — a house with an arched door, one `currentColor` path, legible at 16px flat.

## What was applied (verbatim drop-ins from the handoff)

- **`base.html`** — new `<style>` (navy tokens + component CSS), the Homestead `.brand` SVG,
  `theme-color = #234a78`. Claude Design **preserved every load-bearing bit**: the
  `{% if user.is_authenticated %}` PWA `<head>` block, the nonce'd service-worker `<script>`, the
  `{% block body %}`/`{% block title %}`, the brand link, and the exact **token names + class hooks**
  (the CI contract) — only values changed, a few tokens added, none removed.
- **`elder_feed.html`** — navy accents + the flat Homestead mark; the reading surface stays
  black-on-white (**17.4:1**, pinned), 48px targets, the `26px/21px` big-text toggle and all Django
  logic intact.
- **`email/digest.html`** — table-based, ~600px, hardcoded hex, light-only, with the flat Homestead
  mark; **every variable and line of copy** (`{{ separator }}`, reply-address, unsubscribe, URLs,
  pluralize) textually unchanged.
- **`pwa_views.py`** (the one orchestrator action, handoff §3) — `_THEME`→navy `#234a78`,
  `_BG`→`#f7f8f9`, and `_render_icon` rewritten to draw the **Homestead mark** (a light house with an
  arched door on a navy rounded field) deterministically in Pillow, tracing the app-icon path from §6.

## Verification

- **ruff + ruff format + mypy(strict, 136)** clean.
- **The two WCAG guards pass with the new navy palette:** `test_design_system_wcag.py` (17
  text/background pairs × both themes, all ≥ 4.5:1 — worst light **5.55**, dusk **6.99**) and
  `test_elder_wcag.py` (elder **17.4:1**, ≥48px, single-column, big-text toggle). The token-contrast
  claim is not taken on faith — the CI guard recomputes it and fails the build on any regression.
- **pytest: 542 passed** (all copy-string / structural tests hold with the new templates; the
  destructive-`×` / reacted-`✓` / flag-diamond non-colour cues are CSS `::before`, so they don't
  perturb the copy assertions). **Required `e2e`: 8 passed** (iOS Safari + Android Chrome onboarding
  through the changed shared DOM).
- **security-reviewer** on the token/email/media diff: **CLEAN — no CRITICAL/HIGH/MEDIUM/LOW.**
  Confirmed the SW `<script>` + PWA `<head>` stay `is_authenticated`-gated (ADR-002 holds on token
  surfaces), no `|safe`/`mark_safe`/inline-handler introduced, the brand link leaks no token, the
  elder page stays standalone + worker-less with `26px/21px` intact, the email is purely
  presentational (every variable preserved, `mailto` auto-escaped), and the icon renderer takes no
  user input (constant geometry). "Safe to proceed to the founder design-QA step."
- **Live-repro (visual):** rendered from the applied `base.html` CSS + the real elder template and
  screenshotted — the member app in **both themes** (light "open daylight" + dusk) and the elder
  view. Navy identity, non-colour cues, and the Homestead brand all render correctly.
- **Deployed + re-verified on the box** (https://backyard.family): the live authenticated feed
  renders the navy identity clean. The redeploy surfaced (and the loop fixed, PR #76) a real
  **multi-line-`{# #}`-comment leak** — Django's `{# #}` is single-line only, so the multi-line PWA
  comment (pre-existing) + the new Homestead/email comments rendered as literal text on authenticated
  pages; converted to `{% comment %}` with a non-vacuous CI guard (`test_template_hygiene.py`).
- **Axe-in-browser WCAG 2 A/AA sweep on the live instance: 0 serious/critical violations** across 8
  surfaces (setup, home, feed, members, metrics, profile, invite, elder) — the automated AA check
  beyond the token-contrast guard, completing criterion 3's "WCAG AA on every surface."

## No CSP / no Python-security change

System-font stack (no webfont); `font-src 'self'`, nonce `script-src`, `style-src 'unsafe-inline'`
all unchanged. No inline handlers, no JS-dependent states (every hover/focus/active and the elder
toggle is pure CSS). The only Python touched is the deterministic icon renderer (constant geometry,
no user input).

## Files

`src/core/templates/core/base.html`, `elder_feed.html`, `email/digest.html`; `src/core/pwa_views.py`.
Source package: `docs/design/claude-design-kickoff-prompt.md` (the prompt) → Claude Design → this apply.
