You are Claude Design. Design the definitive visual identity, design system, and logo for **Backyard** — a private, self-hosted, server-rendered Django social network for one extended family (~25–80 people across two family "sides," ages ~9 to ~79; domain **backyard.family**). You already have this repository mounted at `/Users/james/projects/backyard`; read the files I cite rather than asking me to paste them. This is not a greenfield mockup — your output has to drop straight into a running Django app that two CI guards are watching. Read the constraints below; they are stated inline so nothing critical is lost even if your read of the repo is shallow.

## Read these first (your real brief — I am only restating the non-negotiables inline)
- `docs/design/claude-design-brief.md` — the full brief and reference package. **Primary source; read completely.**
- `docs/principles.md` — the product principles. Treat every one as a design constraint, not a vibe.
- `src/core/templates/core/base.html` — the current design system and the **source of truth for token names + class hooks**, the dark `@media` override, and the `:focus-visible`/reduced-motion rules. Your deliverable replaces the `<style>` in this file.
- `src/core/templates/core/` — all 34 surface templates (32 `{% extends %}` base.html). Read the real DOM; design onto real content.
- `src/core/templates/core/elder_feed.html` — the standalone high-contrast elder reader (its own `<style>`, not base.html).
- `src/core/templates/core/email/digest.html` — the email digest (inline-hex fragment, not app CSS).
- `src/core/tests/test_design_system_wcag.py` and `src/core/tests/test_elder_wcag.py` — the two guards that fail the build. Read them so you know exactly what is parsed and asserted.
- `docs/PATH-TO-100.md` item 3 — the acceptance criterion this pass closes ("WCAG 2.1 AA completed across every surface, not just contrast + tap-target").
- `stories/stories.yaml` — the surface/behavior inventory.
- Baseline to **elevate, not match**: the published S-720 specimen artifact `https://claude.ai/code/artifact/f23514ee-26a2-4905-8bf7-9186ff766417` and `docs/design/reference/{specimen-desktop,specimen-mobile,elder-real,elder-real-big}.png`. S-720 is a **functional reference substrate only** — it proves the token/hook structure and the accessibility; the finished look, feeling, and logo are yours to make. Do not merely tweak it.

---

## What you must return (outcome-first — these are the integration targets)
Deliver these six artifacts, each shaped to drop straight in with no re-engineering on my side:

1. **A logo package** — 2–3 distinct directions plus the `Backyard` wordmark lockup, each as **inline SVG** (single-path where possible, ideally `currentColor`-driven) that pastes into `base.html`'s existing `.brand`. Plus, for the winning direction, a **flat one-color** variant for the elder page and email, and the 16px-favicon proof.
2. **A light-theme `:root` token block** using the **exact existing token names** (below, verbatim). Pastes over the current `:root` in `base.html`.
3. **A dark-theme override block** — `@media (prefers-color-scheme: dark){ :root{ …same names… } }` — a *hand-designed* dusk palette, not an inversion. Both blocks must coexist; a `:root[data-theme="light"]`/`[data-theme="dark"]` manual override must still win in both directions.
4. **Component CSS keyed to the exact existing class hooks** (below), mobile-first, plain CSS, pure-CSS states only. This replaces the component CSS inside `base.html`'s single inline `<style>`.
5. **A standalone elder `<style>` block** for `elder_feed.html` (does NOT use base.html's tokens — see its spec), and a **separate hardcoded-hex inline-style block** for `email/digest.html` (no CSS variables — see its spec).
6. **A handoff README** (a `/design-sync`-consumable package is ideal): a per-theme **contrast proof table** (every text/background pair, both themes, computed ratios), the elder ~17:1 proof, a "what changed" summary, and any **CSP/font consequence** I must apply — so I can drop it in, re-run the two WCAG guards, run the full gate, live-repro, and hand to founder QA.

> **Do NOT produce** React/JSX/Vue, a component library, Tailwind, a `tailwind.config.js`, utility classes, CSS-in-JS/styled-components, a Figma-only kit, an npm package, or anything needing a build, bundler, CDN, or static-assets directory. Reason (stated once): this is server-rendered Django with **no build step** and **`ManifestStaticFilesStorage` that 500s on any `{% static %}`** — the entire design system lives as CSS tokens + plain CSS inlined in one template. If it can't be pasted into one template's `<style>` and consumed by an inline `currentColor` SVG, it can't ship. If you catch yourself writing a framework config or a class taxonomy of your own invention, stop — that output cannot be applied.

---

## The fixed contract (renaming anything here breaks 32 templates + two CI guards)

**Token names — reuse verbatim.** `test_design_system_wcag.py` parses these out of `base.html`; a missing/renamed one fails the build. Redefine their **values** freely (that's the job); keep the **names** exactly. You may ADD tokens; you may not rename or remove these:
```
--paper  --surface  --surface-sunk  --ink  --ink-soft  --line  --line-strong
--green  --green-deep  --green-tint  --amber  --amber-tint  --danger  --danger-tint
--btn-bg  --btn-bg-hover  --btn-ink  --ring  --radius  --radius-sm  --shadow
--font-display  --font-body  --font-mono  --measure  --step
```

**Class hooks — style these existing selectors, don't invent a taxonomy.** 32 of 34 templates depend on them. You may add hooks; keep every name below:
```
header.site  .brand  footer.site  .skip-link  .visually-hidden
.composer  ul.feed  ul.feed>li  .post  .author  .byline  .when  .edited
a.preview (.preview-image / .preview-title / .preview-desc / .preview-url)
.photos  .clip  .clip-status  .actions  .reactions  .react-buttons  .reacted  .reaction-label
li.boundary  (the "new since your last visit" divider)   .caught-up  (the feed end-cap)
.empty  .date-banner  .notice  .errors  .flag  .role  .via-email  .muted  .kinship  .house-rule
buttons:  filled primary = button / .btn ;  secondary = .inline button / .btn-secondary ;
          destructive = button.danger / .btn-danger
forms:    label, input, select, textarea, fieldset, legend
admin:    ul.members, ul.pods, ul.directory, ul.invites, ul.digests, ul.redeemers, and tables (table/th/td)
.handover  .handover-actions  .qr
```

---

## Shippability box (non-negotiable)
- **No build step, no static dir, no CDN.** No `{% static %}`, no `@import url()`, no linked/Google webfonts, no JS component library.
- **Fonts — CSP `font-src 'self'`.** Two allowed paths only; state which you chose and its consequence: **(a) preferred — a refined system-font stack** (zero bytes, instant on slow elder connections: warm system serif for `--font-display`, humanist system sans for `--font-body`, system mono for `--font-mono`); or **(b) at most 1–2 lightweight faces embedded as data-URI `@font-face`**, in which case you must (i) hand back the base64 (or the exact face + subset + woff2) and (ii) state in the README that CSP `font-src` must be extended to include `data:`. Either way deliver a full type system: display + body + mono, a modular scale, weights, line-heights, and `--measure` (reading width).
- **CSP `script-src` is nonce-based** — no inline `onclick`, no injected scripts, **no JS-dependent core states.** Every hover / `:focus-visible` / active / open-close state, and the elder big-text toggle, must be **pure CSS + server-rendered HTML**.
- **CSP `style-src 'unsafe-inline'`** — inline styles and one inline `<style>` in `base.html` are fine.

---

## Both themes must be DESIGNED (no naive invert), AA proven per pair
- **Light = "warm paper in open light"** (warm off-white, deep garden green, golden-hour warmth; not pure `#fff`). **Dark = "dusk in the yard": warm charcoal with a green cast** — never `filter: invert`, never pure `#000`/`#fff`.
- The brand green must **shift, not stay fixed**: a deep `#2f5d3a` reads as a link/button on paper but fails on charcoal, so dark needs a **lightened foliage green** for text/links (baseline reference `#85ba90`) plus a separate filled-button green. The warm focus ring shifts too (baseline: light `--ring: #8a5a12`, dark `--ring: #e2b878`).
- `test_design_system_wcag.py` computes real WCAG ratios for **every text/background token pair in both themes** and **fails the build** below **4.5:1** normal / **3:1** large text (≥24px, or ≥18.66px bold), UI borders, and focus rings — an unproven palette is worthless. Hand back a **contrast table** with hex + computed ratio for each pair in each theme. Sweat the historically thin pairs explicitly: `--ink-soft` on `--surface` and on `--surface-sunk`; `--green` link on `--paper`/`--surface`; `--green` on `--green-tint`; `--amber` on `--amber-tint`; `--danger` on `--danger-tint`; `.preview-url` on `--surface-sunk`; table-stripe text; placeholder text. Show the dark palette applied to **real cards**, not swatches.

---

## Accessibility — the full WCAG 2.1 AA bar, every surface (PATH-TO-100 item 3, broader than contrast)
- **Visible `:focus-visible` ring on every control** (baseline: `3px solid var(--ring)`), in both themes.
- Interactive targets **≥44px** (elder **≥48px**).
- Honor **`prefers-reduced-motion`**; keep motion optional and gentle.
- Semantic markup; keyboard-operable everywhere.
- **Never color alone for meaning** — the `li.boundary` divider, `.flag`/`.role` pills, and destructive vs secondary buttons must each carry an icon or text cue too. (This also satisfies "separate is a feature": boundaries read as gentle, not alarms.) A later axe-in-browser sweep runs on the live instance; founder manual QA gates any share — design so both pass.

---

## Elder surface — a separate, non-negotiable spec (do not prettify into failure)
`elder_feed.html` is **standalone** (its own `<style>`, not base.html's tokens) and is a **single, deliberately light, high-contrast** view — **intentionally NOT auto-dark**, not part of the member palette. Pinned in `test_elder_wcag.py` (regressions fail the build):
- Reading text held at **~17:1** — baseline `#1a1a1a` on `#ffffff` = **17.4:1**. Do **not** tint or darken the reading text for aesthetics.
- Tap targets **≥48px**; one obvious **"Send love" post-back** per post; one visible focus ring; reduced-motion honored; single-column, one-way-back shape.
- **Big-text toggle** swaps body **21px → 26px** (pure CSS/server-rendered, no JS).
- Warmth here comes **only** from green accents + a warm serif (Georgia today) — **never** at the cost of legibility. Refine its craft; do not dilute it.

---

## Email digest — NOT app CSS (do not token-drive it)
`email/digest.html` renders in mail clients (Gmail, Outlook) that **strip `<style>` blocks and CSS custom properties**:
- **Inline `style=` attributes only, hardcoded literal hex** — no CSS variables.
- **Table-based, single-column, ~600px** robust layout; web-safe fonts with graceful fallback.
- **Light-only** (no dark variant), safe in clients that ignore dark mode.
- **Flat one-color logo** mark (not the header SVG).
- Palette **derived from** your light theme but **authored as concrete hex** (baseline reference: `#23241f` / `#2f5d3a` / `#5d5f52` / `#8a8676` / `#ddd6c4`). If you return tokens only, the email ships unstyled — deliver the actual hex block.

---

## Logo brief
2–3 directions + the wordmark lockup for **Backyard** (`backyard.family`). Metaphor space: a warmly, timelessly rendered backyard element — sprout/leaf, small tree, fence gate, lawn, home. Current placeholder is a **two-leaf sprout in garden green `#2f5d3a`**, an inline `currentColor` SVG in `base.html`'s `.brand` — a starting reference, not a mandate.
- Deliver each mark as **inline SVG** that drops into `.brand` (no static dir), plus the wordmark lockup.
- Each must survive the **four-rung ladder: 16px favicon → header wordmark → flat one-color on the elder page → flat one-color in email/print**, and read at **16px monochrome** (the test most AI logos fail).
- If you change the brand color, flag in the README that it ripples to `base.html`'s `<meta name="theme-color">` (currently `#2f5d3a`), the deterministically-generated **PWA icons** (`icon_192` / `apple-touch-icon`), and the flat one-color mark used by both the elder page and email.

---

## The feeling, and product principles as concrete design constraints
Warm, calm, safe, unhurried — **a well-kept backyard at golden hour**; keepsake and hand-tended, legible to a **9-year-old and a 79-year-old at once**; a family heirloom, not a startup dashboard. Encode `docs/principles.md` as visual rules:
- **The feed ends** — design a genuine, restful `.caught-up` end-cap. No "load more," no infinite-scroll skeleton, no unread dots.
- **Nothing is amplified** — equal visual weight per `.post`; no ranking, hero, or featured treatment; no counts, streaks, badges, or notification bells.
- **Separate is a feature** — yard (family side) and pod (household) boundaries read as a **gentle** `li.boundary` divider, a soft threshold — never a wall or a red alert.
- **Reciprocity** — post-back / reaction / "Send love" affordances are inviting and **large**.
- **Never assume a smartphone; calm over engagement** — quiet color, restraint; spend one bold move in one place, keep the rest quiet; mobile-first CSS, operable on old devices and slow connections.
- **Anti-target — avoid the generic AI look by name:** *not* the default cream-background + Playfair/serif-display + terracotta/rust-accent + huge-hero SaaS-landing-page look; *not* a slick startup dashboard; *not* glassmorphism or gradient-mesh.

---

## Every surface, shown IN SITU (not a swatch board) — read the real templates in `src/core/templates/core/`
- **Feed:** `.composer`, `.post` card, `a.preview` link-preview card, `li.boundary` "new since" divider, `.caught-up` end-cap, `.empty` states, `.date-banner`.
- **Post + replies:** reactions/`.react-buttons`/`.reacted`, reply composer, comments (`post_detail`, `edit_post`, `compose_confirm`, `delete_confirm`).
- **Onboarding / first-run:** `home`, `join`, `setup`, `invite_household`.
- **Elder:** `elder_feed` + big-text toggle; **and** the admin-side elder **provisioning** (`provision_elder`, `new_elder`) as distinct from the elder-facing reader.
- **Hand-over / share:** `.handover` / `.handover-actions` / `.qr` (`handover_link`, `_handover_artifacts`).
- **Admin (the long tail — do not skip):** `members` (`.role` pills + supervised `.flag` + set-role/remove), `members_invites`, `members_metrics` (connection-health table), `members_quarantine`, `members_digests`, `break_glass`, `directory`, `pods`, `family_sides`, `member_profile`, `profile_edit`, `notification_settings`.
- **System messaging:** `.notice`, `.errors`, `.flag`, `.role`, buttons (primary / secondary / `.danger`).
- **Both digests:** the web page (`digest_web`) **and** the email (`email/digest.html`), plus every digest state (`digest_confirm`, `digest_link_expired`, `digest_settings`, `digest_unsubscribe`, `digest_post`).

---

## Before you finish — self-audit (confirm each holds)
No build step / no Tailwind / no React / no static dir. Existing token names and class hooks preserved verbatim (none renamed or dropped). No linked webfonts (system stack or data-URI only; CSP consequence stated). No JS-dependent core states (nonce CSP). Both themes hand-designed with the green shifted for dark (no invert). Every text/bg pair ≥AA in both themes with ratios shown. Elder surface ≥17:1 and ≥48px, not auto-darkened or tinted. Email digest uses inline hardcoded hex, light-only, table layout — not tokens. Logo reads at 16px flat monochrome across all four rungs. All surface groups above + both digests + the admin long tail covered in situ. Visible `:focus-visible` ring, ≥44px targets, reduced-motion, and non-color cues intact everywhere. Handoff includes the contrast proof table + the CSP/font notes + any brand-color ripple (theme-color meta + PWA icons + flat email/elder mark).