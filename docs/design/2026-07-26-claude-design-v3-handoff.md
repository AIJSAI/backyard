# Handoff: Backyard design v3 — "Signage"

## Overview
The design-v3 pass for Backyard (repo AIJSAI/backyard): one warm, elder-first identity
— clean white grounds, sign green #1e5c46, Atkinson Hyperlegible — applied to every
surface, plus the three structural fixes this pass exists for: the ~30 raw django-allauth
pages, the three unbranded Django error pages, and the measured contrast failures
(SC 1.4.11 composer border 1.24:1; digest-email greys 3.25:1).

Chosen direction: riff 2a "Signage" (Wayfinding x Golden Hour), picked by the founder
from 10 concepts -> 5 riffs.

## About the Design Files
The .dc.html files in the project workspace ("Backyard v3 — Member App.dc.html",
"Backyard v3 — Admin and Tokens.dc.html") are **design references created in HTML** —
canvas prototypes showing intended look, not production code. The CSS and Django
templates in THIS folder, however, are written to drop directly into the Django app:
apply them, re-run the two WCAG guards and the full gate, re-capture, diff.

## Fidelity
**High-fidelity.** Colors, type, spacing, radii and copy are final. Recreate exactly;
the token names and class hooks match the app's existing contract.

## Files in this bundle
- 01-base-style.css — replaces the ENTIRE <style> block inside src/core/templates/core/base.html
  (tokens light + dark + data-theme overrides + all component CSS). Apply verbatim.
- 02-allauth-layouts/base.html, entrance.html, manage.html — place under a project template
  dir as allauth/layouts/*.html. NOTE: 'core' sits AFTER 'allauth' in INSTALLED_APPS, so
  either add a TEMPLATES['DIRS'] entry (recommended) or reorder the apps.
- 03-error-pages/404.html, 500.html, 403_csrf.html — project-level templates. 500.html is
  deliberately self-contained (no extends/url/DB). Wire 403_csrf via CSRF_FAILURE_VIEW or
  the default 403_csrf.html lookup.
- 04-elder-style.css — replaces the <style> in src/core/templates/core/elder_feed.html.
  Keeps the pinned contract (17.4:1 reading text, 48px targets, big-text toggle).
- 05-email-digest.html — replaces src/core/templates/core/email/digest.html. Inline hex
  only; every Django variable and line of copy unchanged.

## What changed (v2 navy -> v3 Signage)
1. Brand color: navy #234a78 -> sign green #1e5c46 (ripples below).
2. Type: system stack -> Atkinson Hyperlegible self-hosted woff2 (regular/bold/italic),
   system fallback. Ship the three files at static/fonts/atkinson-hyperlegible-*.woff2
   (download from https://fonts.google.com/specimen/Atkinson+Hyperlegible, subset latin),
   add the project static dir, run collectstatic. font-display: swap.
3. SC 1.4.11 fix: .composer textarea border now uses --line-strong (3.40:1 light /
   3.64:1 dark, was 1.24:1). All control borders use --line-strong.
4. Target-size fix: .actions .inline button min-height 44px (was auto ~28px); all
   buttons/inputs >= 44-48px.
5. --amber restored to a warm accent (#8a5a12 / #e2b878) — boundary + flags regain a
   warm, non-color-only distinction (label pill + diamond/circle glyphs).
6. header.site is the one bold move: green band, white wordmark (dark: green-tint band,
   green wordmark). Everything else stays quiet.
7. .caught-up is a confident end-cap (green, checkmark ::after).
8. .handover::before adds the once-only warning pill (D11).
9. Table headers style through thead th AND table tr:first-child th — covers
   members_metrics.html, which writes bare <tr><th> with no <thead> today. Recommended
   template fix: add a real <thead> and a mobile per-week card reflow (<640px).
10. Email digest greys: #8a8f98 (3.25:1) -> #5d6a61 (5.68:1) on the reply separator and
    the anti-phishing notice. Recommended: add an email-template contrast guard to CI.
11. New allauth hooks (.entrance, .brand-inline, .lede, .manage-card) added to base CSS;
    no existing hook renamed or removed.

## Contrast proof table (computed WCAG 2.1 ratios)
Light theme:
| pair | hex | ratio |
|---|---|---|
| ink / paper | #1c211e / #fbfcfb | 15.88:1 |
| ink / surface | #1c211e / #ffffff | 16.33:1 |
| ink / surface-sunk | #1c211e / #eef3ef | 14.55:1 |
| ink / green-tint | #1c211e / #eef4f0 | 14.65:1 |
| ink / danger-tint | #1c211e / #f9e9e6 | 13.87:1 |
| ink-soft / paper | #4c5a52 / #fbfcfb | 7.06:1 |
| ink-soft / surface | #4c5a52 / #ffffff | 7.26:1 |
| ink-soft / surface-sunk | #4c5a52 / #eef3ef | 6.47:1 |
| green / paper | #1e5c46 / #fbfcfb | 7.63:1 |
| green / surface | #1e5c46 / #ffffff | 7.85:1 |
| green / green-tint | #1e5c46 / #eef4f0 | 7.04:1 |
| green / surface-sunk (.preview-url) | #1e5c46 / #eef3ef | 6.99:1 |
| amber / paper (boundary) | #8a5a12 / #fbfcfb | 5.75:1 |
| amber / amber-tint (.flag) | #8a5a12 / #f6efe0 | 5.16:1 |
| danger / paper | #b23b2e / #fbfcfb | 5.74:1 |
| danger / surface | #b23b2e / #ffffff | 5.90:1 |
| btn-ink / btn-bg | #ffffff / #1e5c46 | 7.85:1 |
| ring / paper | #8a5a12 / #fbfcfb | 5.75:1 |
| line-strong / surface (border, needs 3:1) | #7f8f85 / #ffffff | 3.40:1 |

Dark theme:
| pair | hex | ratio |
|---|---|---|
| ink / paper | #e8ece9 / #121714 | 15.20:1 |
| ink / surface | #e8ece9 / #1a211c | 13.77:1 |
| ink / surface-sunk | #e8ece9 / #0d110f | 15.94:1 |
| ink / green-tint | #e8ece9 / #16281f | 12.97:1 |
| ink / danger-tint | #e8ece9 / #2a1815 | 14.20:1 |
| ink-soft / paper | #a8b3ab / #121714 | 8.37:1 |
| ink-soft / surface | #a8b3ab / #1a211c | 7.59:1 |
| ink-soft / surface-sunk | #a8b3ab / #0d110f | 8.79:1 |
| green / paper | #7fc9a4 / #121714 | 9.32:1 |
| green / surface | #7fc9a4 / #1a211c | 8.44:1 |
| green / green-tint | #7fc9a4 / #16281f | 7.95:1 |
| green / surface-sunk | #7fc9a4 / #0d110f | 9.77:1 |
| amber / paper | #e2b878 / #121714 | 9.81:1 |
| amber / amber-tint | #e2b878 / #241c10 | 9.10:1 |
| danger / paper | #eb9a8d / #121714 | 8.24:1 |
| danger / surface | #eb9a8d / #1a211c | 7.46:1 |
| btn-ink / btn-bg | #ffffff / #2c7a5c | 5.19:1 |
| ring / paper | #e2b878 / #121714 | 9.81:1 |
| line-strong / surface (border, needs 3:1) | #6b7a71 / #1a211c | 3.64:1 |

Elder proof: reading text #1a1a1a on #ffffff = 17.40:1 (unchanged, pinned).
Email digest: faint #5d6a61 = 5.68:1, muted #4c5a52 = 7.26:1, green #1e5c46 = 7.85:1,
all on #ffffff. Weakest text pair anywhere: 5.16:1 (flag pill) — comfortably past AA.
Both WCAG guards (test_design_system_wcag.py, test_elder_wcag.py) should pass unmodified;
suggested extensions: assert line-strong >= 3:1 per theme, and add an email-hex guard.

## CSP / font consequence
- Chosen path: self-hosted woff2 (option a-plus). The CSP has NO font-src directive, so
  fonts fall back to default-src 'self' — same-origin woff2 is already allowed. No CSP
  change strictly required; adding an explicit "font-src 'self'" is recommended for
  clarity. Do NOT use data: fonts (blocked today).
- The project ships no static directory yet; {% static %} works (WhiteNoise +
  collectstatic configured) but 500s on a missing file — ship the three font files
  BEFORE applying 01-base-style.css, or temporarily drop the @font-face block (the
  system fallback stack is designed to hold).

## Brand-color ripple (navy -> green)
- base.html <meta name="theme-color" content="#234a78"> -> #1e5c46
- Deterministic PWA icons (icon_192 / apple-touch-icon views) — regenerate on #1e5c46
- Flat one-color mark: elder page + email digest SVGs now fill #1e5c46 (included here)
- Favicon: 16px Homestead mark reads monochrome at #1e5c46 (unchanged geometry)

## Interactions & behavior
Pure CSS + server-rendered HTML only (nonce CSP): hover via :hover, focus via
:focus-visible (3px var(--ring)), no new JS anywhere. Reduced motion honored globally.
Members "Manage" disclosure and composer "+ Photos" affordances shown in the prototypes
should be server-rendered expand/collapse (GET param or details/summary), not JS.

## Screens / views
See the two workspace canvas files for every surface in situ: feed (light + dark),
post & replies, sign-in + password reset (entrance), account security (manage),
404/500/403-CSRF, home/join, members, invites, metrics, quarantine, hand-over,
digest states, elder feed, email digest, digest web. Layout metrics: page column
max-width 40rem, card padding ~1rem 1.1rem, radius 12px (9px controls), body 17px/1.6.

## Verification loop (what the founder runs after applying)
make up; apply files; collectstatic; run test_design_system_wcag.py + test_elder_wcag.py;
full gate; python capture.py populated; diff captures against the pre-v3 set.
Security review note: the allauth overrides touch auth surfaces — review per policy.
