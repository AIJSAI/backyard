# Design v3 "Signage" applied — close receipt

Date: 2026-07-26. The v2 navy identity was rejected by the founder ("not sophisticated or
production enterprise grade"), reopening PATH-TO-100 criterion 3. This receipt covers applying
the Claude Design v3 handoff produced from `docs/design/claude-design-kickoff-v2.md`.

Source bundle: `docs/design/2026-07-26-claude-design-v3-handoff.md` (Claude Design's own README,
committed verbatim). Chosen direction: riff 2a "Signage" — sign green `#1e5c46`, Atkinson
Hyperlegible, white grounds.

## What was applied

- **`base.html`** — the entire `<style>` block replaced (22.8 KB → 24.6 KB). Every one of the 26
  token names and 66 class hooks preserved; values changed throughout.
- **`elder_feed.html`** — its standalone `<style>` replaced. The pinned contract holds: reading
  text `#1a1a1a` on `#ffffff` = 17.4:1, ≥48px targets, the big-text toggle.
- **`email/digest.html`** — replaced. Every Django variable and copy string unchanged; the faint
  grey that carried the reply separator and the anti-phishing notice moves `#8a8f98` (3.25:1) →
  `#5d6a61` (5.68:1), closing a real AA failure no CI guard reaches.
- **`allauth/layouts/{base,entrance,manage}.html`** — new project-level overrides. **~30 credential
  surfaces that rendered the library's raw unstyled defaults now inherit the design system.**
- **`account/login.html`** — new override: allauth's markup verbatim except the stock "please sign
  up first" paragraph and its live `{{ signup_url }}` link, which sent a new relative to a dead end
  on the first screen of the product (signup is invite-only, S-101, and the adapter refuses it).
- **`404.html` / `500.html` / `403_csrf.html`** — new. The 404 is a *normal* surface here because
  authorization denials answer 404 by design, and it now reads as ordinary rather than broken.
  500 is deliberately standalone: no extends, no URL resolution, no DB.
- **Atkinson Hyperlegible** self-hosted, latin subset, 3 faces, **33 KB total** (SIL OFL). Served
  same-origin through `{% static %}`; `default-src 'self'` already permits it, so no CSP change.
- **`TEMPLATES['DIRS']`** now carries a project template root. This is the mechanism that makes the
  allauth overrides win: `core` sits *after* `allauth` in `INSTALLED_APPS`, so the app-dirs loader
  would otherwise find the library's own layouts first.

## Four defects found and fixed during application

The handoff was high quality but not drop-in. Each of these was caught by applying and rendering,
not by reading:

1. **The entrance wrapper never rendered.** The layout wrapped `{% block content %}`, but every
   allauth leaf page defines `content` itself, so Django discarded the wrapper wholesale — the page
   picked up the stylesheet while the brand lockup and the invite-only explanation silently vanished.
   Fixed by introducing a `{% block auth_shell %}` seam in the layout that no leaf defines, with
   `content` rendered inside it. Pinned by `test_auth_surfaces.py`.
2. **`500.html` did not compile.** Its header comment used `{# … #}` across two lines — Django's
   `{# #}` is single-line only — and the leaked text contained a literal `{% extends %}`, which then
   parsed as a real tag: `TemplateSyntaxError: 'extends' takes one argument`. This is the same bug
   class as PR #76, and the existing guard missed it because it only scanned `src/core/templates`.
   Fixed, and the guard now scans **both** template roots, asserts each root is non-empty (so it
   cannot go vacuous), and **compiles every template** — which catches this class outright.
3. **The font URLs were hardcoded `/static/fonts/…`.** Under `ManifestStaticFilesStorage` the served
   filenames are content-hashed, so those would have 404'd in production while working in DEBUG.
   Routed through `{% static %}`; verified against the built manifest.
4. **The wordmark rendered twice** on every signed-out surface — once in the site header band, once
   in the entrance lockup. The site header is now a `{% block site_header %}` the entrance suppresses.

A fifth was cosmetic: a CSS comment in the elder sheet contained the literal `26px`, which defeated
`test_bigger_text_toggle`'s substring assertion. Reworded the comment; the test stands as written.

## Verification

- **Both WCAG guards pass unmodified** — `test_design_system_wcag.py` (17 token pairs × 2 themes)
  and `test_elder_wcag.py` (17.4:1, ≥44px enforced / 48px declared, one `<main>`, no off-surface
  links). The v3 palette was not tuned to the guards after the fact; it passed on first application.
- **ruff + ruff format + mypy(strict, 138 files)** clean.
- **pytest: 553 passed** (baseline 545: +2 template-hygiene guards, +6 auth-surface guards).
- **Live-repro through Caddy** on the local stack with real seeded family data: 259 surfaces
  re-captured at 390×844 @2x and 1440×900, light and dark, plus 320px reflow, 200% text zoom and
  forced-colors, and diffed against the pre-v3 set.
- **SC 1.4.11 closed**: the composer textarea border moves 1.24:1 → 3.40:1 light / 3.64:1 dark.

## What the brief asked for and did NOT arrive

Stated plainly because the founder's headline complaint is in this list:

1. **No desktop information design.** The delivered CSS contains **zero width breakpoints, zero
   `display:grid`, zero container queries**; the page is still one column capped at `--measure:
   40rem`, so 1440px still renders ~600px of content. The brief asked for a real two-region layout
   at ≥64rem and showed the 41.7% figure. This is the single largest gap.
2. **SC 1.4.10 still fails on two admin tables.** `members_metrics` renders 652 CSS px and
   `members_digests` 591 against a 390px viewport (improved from 744/636, but still sideways-scrolling).
   No table-to-card reflow was delivered; the handoff recommends it as a follow-up.
3. **No `@media (forced-colors: active)` and no `prefers-contrast` block.** The repo still has zero
   forced-colors handling, so card elevation carried by `box-shadow` still disappears in Windows
   High Contrast.
4. **No `aspect-ratio` / crop policy for photos.** Mixed aspect ratios still render at natural
   height, so a five-photo post is still a ragged stack.
5. **No `<nav>` landmark** anywhere, and no "Need help?" affordance (SC 3.2.6).
6. **`members_metrics.html` still ships no `<thead>`.** The new CSS works around it by styling
   `table tr:first-child th` as well, so the header now renders correctly — but the markup fix was
   recommended, not made.

## Files

`src/core/templates/core/base.html`, `elder_feed.html`, `email/digest.html`;
`src/templates/{404,500,403_csrf}.html`, `src/templates/account/login.html`,
`src/templates/allauth/layouts/{base,entrance,manage}.html`;
`src/core/static/backyard/fonts/*.woff2`; `src/config/settings.py`;
`src/core/tests/test_auth_surfaces.py`, `src/core/tests/test_template_hygiene.py`.
