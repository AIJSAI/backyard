# Backyard — Claude Design brief

**Purpose.** This is the prompt + reference package to hand to **Claude Design** (claude.ai/design)
so it produces the *definitive* visual identity and design system for Backyard. The design pass
already in the repo (S-720) is a **functional baseline and reference substrate only** — it
establishes the token/component structure and proves accessibility, but the real look-and-feel,
the logo, and the finished visual system are Claude Design's to make. Whatever Claude Design
produces gets pulled back into the app (via `/design-sync` or applied to `base.html`) and
re-verified.

How to use: paste the **Prompt** section into Claude Design, attach/point it at the **Visual
reference** (the published artifact + the screenshots), and give it the **Brand & logo** and
**Implementation constraints** sections so its output is both beautiful *and* shippable.

---

## Prompt (paste this into Claude Design)

> Design the complete visual identity and design system for **Backyard**, a private, self-hosted
> social network for one extended family (roughly 25–80 people across two "sides" of the family,
> ages from small kids to grandparents). It is the calm opposite of a feed app: chronological,
> it *ends*, nothing is amplified, no counts or streaks or notifications-by-default. People post
> links, photos, short videos, and small updates; family pulls on their own schedule.
>
> **Who it must serve — the hardest user first.** Grandparents, some of whom don't own a
> smartphone, reach it through a no-login "elder" link that opens a big, high-contrast reading
> view where they can read and "send love" with one tap. Never assume a smartphone; never trade
> legibility for style. The design has to feel warm and human to a 9-year-old and a 79-year-old
> at once.
>
> **Feeling.** Warm, calm, safe, unhurried — a well-kept backyard at golden hour, not a startup
> dashboard. Think keepsake and hand-tended, not slick. It should feel private and gentle. The
> feed visibly ends ("you're all caught up") rather than baiting the next scroll.
>
> **Deliver a full system, both light and dark themes:**
> - A logo / brand mark for "Backyard" that works from a 16px favicon up to a header wordmark and
>   on the elder page (see Brand & logo below).
> - A color palette expressed as tokens (page ground, raised surface, sunk surface, primary text,
>   secondary text, hairlines, a primary/brand color, a warm accent, a semantic danger, focus
>   ring) — for **both** a warm light theme and a warm dark theme, all meeting **WCAG 2.1 AA**
>   contrast (4.5:1 for text).
> - A type system (a display/heading face and a UI/body face and their scale, weights, spacing) —
>   see the font constraint below.
> - Spacing scale, corner radii, shadow/elevation, borders.
> - Component styles for every surface listed under "Surfaces to cover."
> - Mobile-first layouts, and an explicit treatment for the elder view.
>
> **Non-negotiable accessibility:** WCAG 2.1 AA across the board; the elder reading surface must
> keep ~17:1 text contrast (it is pinned in code); every interactive target ≥ 44px (elder ≥ 48px);
> a clearly visible keyboard focus state on every control; honor reduced-motion; never rely on
> color alone to carry meaning.
>
> Show the system applied to the real surfaces (below), not just swatches, so it can be judged in
> context. Where you make a bold move, spend it in one place and keep the rest quiet.

---

## Product principles (these are design constraints, not just values)

1. **Calm over engagement** — chronological, it ends; no infinite scroll, streaks, counts, or read
   receipts. The UI should feel quiet and finite.
2. **Nothing is amplified** — no ranking; every post gets equal visual weight.
3. **Separate is a feature** — the family has two "sides" (yards) that stay apart, and households
   (pods) scope every post. Boundaries should read as *gentle* (a soft divider), never as walls or
   alarms.
4. **Reciprocity is designed in** — every surface, including the elder view, can post back with one
   tap or one email reply. Post-back affordances should be inviting and large.
5. **Never assume a smartphone** — token links with no account, email in and out, a big readable
   elder view. Fast on any device and any connection.

## Brand & logo

- Name: **Backyard**. Domain: **backyard.family**.
- Current placeholder mark (starting reference, not a decision): a simple two-leaf **sprout** in
  garden green — see `base.html`'s inline SVG. It stands for growth, warmth, something tended.
- Please propose **2–3 logo directions** + the wordmark lockup. Metaphor space: a backyard element
  rendered warmly and timelessly — a sprout/leaf, a small tree, a fence gate, a lawn/yard, a home.
  It must read at 16px (favicon), as a header wordmark, and in one flat color (for the elder page
  and email). Warm and friendly, not corporate; timeless, not trendy.
- The existing theme color is a deep garden green `#2f5d3a`; treat it as a strong starting point,
  not a mandate.

## Surfaces to cover (every one)

- **Feed** — the composer (text + photo/video + which pod/side to post to), the post card
  (author, time, body, photos, video, link-preview card), the quiet "new since your last visit"
  divider, the "you're all caught up" end-cap, empty states, and the today's-dates banner.
- **A post & its replies** (thread) — reactions, the reply composer, comments.
- **Onboarding / join** — the invite `join` form, the first-run `setup` form.
- **Elder view** (standalone, no-login) — the big-text reading view + "send love" + the bigger-text
  toggle. Highest-contrast, simplest, most generous targets.
- **Hand-over** — the one-time invite/elder-link share block (readonly link, copy/share buttons,
  printable QR).
- **Admin** — family members list (roles, "supervised" flags, set-role/remove), outstanding
  invites, connection-health metrics table, quarantine.
- **Notices & errors**, flags/badges/role pills, buttons (primary / secondary / destructive).
- **Digest** — both the web digest page and the **email** digest (email needs inline styles +
  robust, client-safe layout).

## Visual reference (current baseline — attach these to Claude Design)

- **Published artifact (the best single reference — every component, both themes, side by side):**
  https://claude.ai/code/artifact/f23514ee-26a2-4905-8bf7-9186ff766417
- Screenshots (rendered from the app's real CSS / real templates):
  - `specimen-desktop.png` — the full component gallery, light + dark.
  - `specimen-mobile.png` — the same at 390px (mobile-first reflow).
  - `elder-real.png`, `elder-real-big.png` — the real elder view (regular + bigger text).
  (These live in the working scratchpad; copy them into `docs/design/reference/` if you want them
  versioned. The artifact URL alone is enough for Claude Design to judge the current state.)

## Implementation constraints (so the output is actually shippable)

Backyard is a **server-rendered Django app** — the design ships as CSS, not a JS component library.
Keep these in mind so the handoff is clean:

- **CSS lives inline in `base.html`** as CSS custom properties (tokens) + component rules; there is
  **no build step and no static-assets dir** (ManifestStaticFilesStorage would 500 on `{% static %}`).
  So: express the system as **design tokens + plain CSS**, mapped to the existing class hooks
  (`.composer`, `.feed`, `.post`, `.author`, `.preview`, `.actions`, `.notice`, `.errors`, `.flag`,
  `.role`, `.react-buttons`, `.handover`, `.qr`, `.date-banner`, `.boundary`, `.caught-up`, tables,
  forms). A tokens sheet + component CSS is ideal; a React/Tailwind kit is not directly usable.
- **Fonts:** the Content-Security-Policy sets `font-src 'self'` and there's no static dir, so a
  custom webfont must be embedded as a **data-URI** `@font-face` (and the CSP `font-src` extended to
  `data:`). If you want a custom face, keep it to **one or two lightweight faces** (elder
  connections may be slow) or design against a refined **system-font stack** (the current baseline
  uses a system serif for headings + a humanist system sans for UI). Call this out explicitly in the
  handoff.
- **CSP:** `style-src 'unsafe-inline'` (inline styles OK); `script-src` is nonce-based (no inline
  event handlers, no `onclick=`). Design must not depend on injected inline scripts.
- **Both themes** via `prefers-color-scheme` (plus a `data-theme` override is fine). Design both;
  don't naively invert.

## The handoff back into the app

Deliverable Claude Design should produce: the **logo**, the **token palette (light + dark)**, the
**type + spacing + radii/shadow scales**, and **component specs/CSS** for the surfaces above —
ideally as something `/design-sync` can pull into a local component library, or as a tokens sheet +
CSS I can drop into `base.html`. I then apply it, re-run the WCAG-AA contrast guard + the full gate,
live-repro it on the persistent instance, and it goes to founder QA.
