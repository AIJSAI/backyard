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

## v3.1 layout addendum — the gaps above, closed

A scoped follow-up round delivered the layout work the first bundle omitted. Applied on top,
with the `.messages` styling from the HIGH-2 fix **re-grafted** (the addendum is a full-file
replacement authored against v3.0, so it would otherwise have silently dropped it) and the font
URLs routed back through `{% static %}`.

- **Desktop information design now exists.** Four breakpoints (37.5 / 64 / 75rem plus a sub-40rem
  reflow), all placed *after* the guarded token blocks. At ≥64rem `main.wrap` becomes a two-region
  grid: a reading well plus a sticky `aside.rail`. Measured on the live stack: at 1440px the shell
  is 1280 wide with a 736px well and a 336px rail — **~74% of the viewport in use, against 41.7%
  before**. At 1920px the same composition centres rather than stretching. Below 64rem the rail
  drops into normal flow and the phone layout is unchanged.
- **The designer explicitly rejected a persistent left app-rail** and said why: five quiet links
  cannot honestly fill one, and a fixed rail reads as a dashboard, against the product principles.
  The margin rail is wayfinding beside a path — secondary, sticky, absent where a page has nothing
  to say. That is the brief's "do not default to the SaaS shell" instruction being answered rather
  than ignored.
- **SC 1.4.10 CLOSED.** Both admin tables now fit exactly 390 CSS px (from 744 and 636 in v2).
  Below 40rem they collapse to stacked cards, with `td::before` printing each column name from
  `data-label`. 320px reflow measures 320px.
- **Photo layout is now a system.** One photo keeps its natural ratio, height-capped at 26rem;
  2-up and 3-up are square grids; 4+ (to the 20-photo cap) is an auto-fill square tile grid; video
  posters are pinned 16/9. Counting is pure CSS (`:has` + `:nth-last-child`) — no JS, no template
  change. The desktop feed is **28% shorter** (8088 → 5804 px) purely from fixed vertical rhythm.

**Template edits this required** (small, server-rendered, no JS): `aside.rail` wrappers in
`feed.html`, `members.html` and `directory.html`; real `<thead>`/`<tbody>` plus `data-label` on
every cell in `members_metrics.html` and `members_digests.html`. The `<thead>` addition also closes
the v3.0 defect where the header rule never matched and the zebra striped the wrong rows.

Re-gated after the addendum: ruff + format + mypy(138) clean, **pytest 558 passed**, both WCAG
guards still pass unmodified, 259 surfaces re-captured.

## Accessibility modes and landmarks — closed 2026-07-26

The three items left open after v3.1 are now done, and two guards were found to be
enforcing less than they appeared.

- **`@media (forced-colors: active)`** added; the repo had none. In Windows High Contrast
  the UA computes `box-shadow` and non-`url()` `background-image` to `none`, and this
  design carried feed/comment/composer/handover card boundaries in `--shadow` **alone**,
  the select arrow in two gradients, and both the unread divider and the feed end-cap in
  `color-mix()` pseudo-elements — all of it silently gone. Repaired with real borders and
  system colour keywords, and **verified live rather than asserted**: with forced colours
  active a feed card computes `box-shadow: none` and `border: 1px solid`, and the select's
  `background-image` is `none`. The outline focus ring is deliberately untouched —
  `outline-color` is force-*adjusted* rather than stripped, so an outline survives where a
  `box-shadow` ring would be deleted for exactly these users.
- **`@media (prefers-contrast: more)`** tightens the ramp: `--line` takes `--line-strong`,
  `--ink-soft` collapses to `--ink`, hairlines double.
- **`<nav>` landmarks** — there were none in any of the 34 templates. On directory and
  members the rail element *is* the `<nav>`; on the feed the `<nav>` sits inside the
  `<aside>`, because that aside also carries the date banner, which is genuinely
  complementary rather than navigation.
- **SC 3.2.6 Consistent Help** — there is no help route in this app and none is being
  added, because a link to a page that does not exist is worse than no link. The mechanism
  is a sentence in the shared footer naming the person who can actually act; for a family
  instance that is the honest answer. A test pins that it is **not** a link.

**Two guards hardened, each proven non-vacuous by probe:**

1. `test_elder_wcag` was enforcing "no links off this surface" **by quoting style** — its
   regex matched only double-quoted `href`, so a single-quoted one passed untouched. It
   also missed `formaction`, which navigates exactly like an `href`, and a meta refresh,
   which leaves without either. On the one surface where a stray outbound link would carry
   an elder's session. All three now fail the build; the clean page still passes.
2. The messages region shipped `role="status"` on the `<ul>`, which overrides the implicit
   list role and orphans every `<li>`. axe flagged it **serious** on the MFA pages —
   surfaces the earlier 8-surface sweep never reached because they had no design then.

**axe-in-browser sweep, broadened from 8 surfaces to 138 renders** — 35 surfaces including
every allauth credential page and the three error pages, at desktop **and** mobile, in
light **and** dark, plus the elder path, against `wcag2a`/`wcag2aa`/`wcag21a`/`wcag21aa`/
`wcag22aa`: **0 violations at any severity.** Raw report:
`docs/receipts/2026-07-26-axe-v31-sweep.json`.

Gate: ruff + format + mypy(139) clean; **pytest 565 passed**.

## Deployed and re-verified live — 2026-07-26

`main` @ `577504b` deployed to **https://backyard.family** (the same Ubicloud VM; tree synced,
`web` + `worker` rebuilt, Caddy untouched). The image ships a static directory for the first time,
so this was the first deploy where `collectstatic` mattered — it worked, and the runbook now says
to rebuild rather than restart.

Verified against the LIVE instance, not localhost:

| Check | Result |
|---|---|
| `/healthz` | 200 |
| Sign-in inherits the design system | `.entrance` present, invite-only lede present, `Menu:` **gone** |
| Passkey sign-in | `id="mfa_login"` present — the form the button submits to |
| Self-hosted font | `atkinson-hyperlegible-regular.d444e1815a3a.woff2` → **200 `font/woff2`**, 11,208 b |
| Brand colour | `#1e5c46` on the page (navy retired) |
| SC 3.2.6 help affordance | present |
| Branded 404 | `<title>Not here — Backyard</title>`, "There's nothing at this address" |
| **axe WCAG 2 A/AA + 2.2 AA** | **138 renders, 35 surfaces, desktop + mobile, light + dark — 0 violations at ANY severity** |

Raw production report: `docs/receipts/2026-07-26-axe-v31-sweep-PROD.json`.

## Still open

Nothing engineer-actionable on the design pass. What remains is founder-gated:
**criterion 4** (his personal manual QA) and **criterion 7** (the go-public decision;
the family share comes first).

Container queries were deliberately not used — the designer's stated reason is that every
adaptive region tracks the viewport-driven well directly, so `@media` is sufficient and
cheaper to audit. Recorded as a decision, not a gap.

## What the first bundle (v3.0) asked for and did NOT arrive — now historical


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
