# Backyard — Claude Design kickoff (v2)

> **Message 1** = the 18 images of `message-01`, then the three source files from `source/`, then
> this whole document last. Images first, instructions last — that ordering applies **within every
> message**. Messages 2–8 are additional reference images and arrive after this brief; that is
> deliberate and they are labelled so you can slot them in.
>
> The three files in `source/` are the artifacts you are replacing and must hand back:
> `base-style.css` (the current single `<style>` block, verbatim), `elder_feed.html` and
> `email-digest.html`. You cannot produce a byte-for-byte replacement for a file you have never
> seen, so read them before Phase 3.
>
> See `UPLOAD-PLAN.md` for the label lines, and `docs/design/README-design-pass-v2.md` for the
> full procedure.

---

## 0. How this session runs — do not skip ahead

You are redesigning a shipped product, not mocking up a concept. A previous pass built a complete
system in a direction that was rejected on sight, and the whole build was wasted. So:

**Phase 1 — diverge.** Produce **10 numbered directions**, each rendered as **one 1440×900 frame of
the signed-in feed showing at least one photo post, one text-only post, and the page chrome**. Flat,
static, no other surfaces, no build-out, no code. Before the pixels, write each direction's spec as
numbers: page-ground hex, surface hex, ink hex, one accent hex and its chroma, the display and body
type stacks, the base type size and scale, the spacing unit, the radius set, and the elevation policy
in one line. Then stop.

**Divergence is assigned, not hoped for.** Ten directions produced freely collapse into one. So each
of the ten takes a named thesis, and each thesis must change the *structure* as well as the palette:

1. **Civic** — the confidence of good public signage. Heavy sans, large size contrast, wide margins,
   near-zero ornament, ink-dominant.
2. **Record** — the family archive as a ledger. Horizontal rules as the primary structure, date-led
   hierarchy, tabular discipline, metadata in mono.
3. **Reading application** — typography carries everything. Serif body at a strict measure, chrome
   almost absent, no card ever.
4. **Domestic instrument** — a well-made household object. A committed, non-brand-y ground colour,
   high-legibility sans, controls that feel physical and pressable.
5. **Mount board** — the interface as a passe-partout. Photos framed with real margin on a mount
   tone; chrome reduces to mount, rule and caption.
6. **Letterpress** — one ink and one paper. Deep ink, tight heading tracking, borders instead of
   shadows, zero tints anywhere.
7. **Dense** — for the relative who checks it daily. More content per screen, tighter rows, ruled
   tables, small-but-never-under-16px type.
8. **Soft** — genuinely warm without cream or terracotta. Cool-warm neutrals, larger radii, low
   contrast between surface layers, elevation carried by tint.
9. **Nightfall** — dark authored *first* as the primary theme, light derived from it. Deep ground,
   photographs luminous against it.
10. **Handset** — designed as though the phone is the only device and the desktop is the
    accommodation. Thumb-zone actions, large targets everywhere, the desktop a widened version of
    the same rhythm rather than a different layout.

Do not soften a thesis toward the others. If two of the ten could be swapped without anyone noticing,
they have both failed.

**Phase 2 — remix.** I name two winners. You return **5 riffs** that combine them. Each riff shows
**three** surfaces: the feed, the sign-in screen, and the members admin table. A direction that only
works on a content surface is not a system — half this product's problem is that its credential
screens were never designed, and "production-grade" is judged on dense surfaces, not on a feed.
Then stop.

**Phase 3 — build.** Only after I pick one riff do you build every surface and write the handoff.

Build only the surfaces the current phase names — one in Phase 1, the three named in Phase 2,
everything in Phase 3. If you find yourself producing final CSS in Phase 1, you have misread this.

**More image messages follow this one.** When you read this you have seen the first eighteen images
only. Do the §3 defect table now — it is scoped to exactly those — then wait: I will say "all images
sent" before you begin Phase 1.

Ask me clarifying questions before Phase 1 if you have them. I will answer specifically; do not
accept "you decide" from me on art direction.

---

## 1. What Backyard is

A private, self-hosted social network for **one extended family** — about 25 to 80 people, aged 9 to
79, across two family "sides" that are hard isolation boundaries. Server-rendered Django. It is not a
startup product, has no marketing surface, no growth loop, no public sign-up, and never will. Every
person who ever sees it was handed a link by a relative.

Its principles are load-bearing design constraints, not vibes:

- **The feed ends.** There is a real end-cap and you reach it. No infinite scroll, no "load more",
  no skeleton shimmer, no unread badge counts.
- **Nothing is amplified.** Every post carries equal visual weight. No ranking, no hero post, no
  featured treatment, no counts, no streaks, no leaderboards. Reactions show *who* reacted, never
  *how many*.
- **Separate is a feature.** The boundary between one family side and the other, and between a
  household and the wider yard, reads as a calm threshold — never a wall, never an alarm.
- **Reciprocity.** Replying and reacting are inviting and large. The elder surface's "send love"
  button is the single most important control in the product.
- **Calm over engagement.** Quiet by default. Never assume a smartphone, a fast connection, or a
  young eye.

The audience is the whole point: this must be legible to a nine-year-old and a seventy-nine-year-old
**at the same time**, on a five-year-old Android and on a 27-inch monitor.

---

## 2. The brief

### 2.0 The character to aim at

Left undirected you will reach for a house style, so here is the direction. It is deliberately a
thesis about *behaviour*, not a palette — the palette is what Phase 1 is for.

**Backyard is a room, not a product.** It is the same twenty-five to eighty people for the next
thirty years. Nobody is being acquired, converted, retained or re-engaged. So it should look like
software someone *maintains*, not software someone *launched*: the considered restraint of a
well-made reading application, the row-by-row trustworthiness of a serious information tool, and the
warmth of a physical keepsake — without pastiche. No scrapbook textures, no torn-paper edges, no
handwriting fonts, no "cosy" clip art.

Warmth still has to come from somewhere, so here is where it is *allowed* to come from, since the
usual routes are closed: the hue bias and lightness of the ground itself; generous line-height and
margin; a display face with real character; the rhythm and restraint of the spacing; the copy; and
the photographs. Not from texture, illustration, ornament, or a cream-and-terracotta palette. If the
result feels cold, the fix is a warmer ground and better type — not decoration.

Four operational consequences, which I will hold you to:

1. **The photographs must stay the most colourful thing on the page.** Family photos are the
   content; the interface must not compete with them. The test: put an empty feed beside a
   photo-filled one — if the interface changes character between them, it is too loud.
   **This is a ceiling, not a recipe.** It caps *chroma*, not *character*: the ground, the ink, the
   type and the structure are still yours to commit to, and a committed ground colour at low chroma
   is very much allowed. Do not read this as "neutral grey chrome plus one small accent" — that
   reading produces the standard 2026 SaaS dashboard, which §2.1's fintech test then correctly
   rejects. Name your accent's chroma so the ceiling is a number, not a vibe.
2. **Hierarchy is typographic, not decorative.** Size, weight, measure and space do the work. Boxes,
   fills, tints and coloured surfaces are a last resort, not the first move. The current design
   reaches for a card whenever it needs a boundary; that is why every screen reads the same.
3. **Content is the first thing on every screen.** Not a page title, not a breadcrumb, not a welcome.
   The family's actual words and faces begin as high as the layout allows.
4. **Age-neutral, not age-targeted.** Generous line-height and target sizes, but never enlarged-print
   scale or "senior-friendly" styling. A nine-year-old and a seventy-nine-year-old use the same
   screen and neither should feel it was built for the other.

> **Founder note:** if you have visual references you actually like — products, books, signage,
> anything — paste them here before sending. Two or three concrete references will do more for the
> outcome than another page of constraints. If this block is empty, that is deliberate: it means
> Phase 1's ten directions are genuinely open.

### 2.1 What "production-grade" means here, in numbers

I rejected the current design as *not sophisticated, not production, not enterprise-grade*. That is
a real judgement but a useless instruction, so here it is converted into things you can check.

**Do not use, and do not design toward, these words:** modern, clean, sleek, polished, sophisticated,
elegant, premium, minimal. Every one of them must be replaced in your reasoning by a hex, a pixel
value, a ratio, a named stack or a viewport.

**Scales before hues.** Deliver four numeric tables *before* choosing a colour: type, spacing, radius,
and a neutral ramp per theme. Every font-size, padding, margin, gap and radius in the final CSS
resolves to one of those tokens — zero ad-hoc values at call sites. The current stylesheet declares
**24 distinct rem padding values, 18 of them off any 4px grid** (0.12rem, 0.15rem, 0.35rem, 0.55rem,
0.85rem, 1.15rem, 1.6rem…) and has **no spacing scale at all**. Hand-tuned-by-eye two-decimal rem
values are the single loudest amateur signal in the file.

**Type.** Six to seven named steps, each with a prescribed line-height and letter-spacing. Adjacent
steps differ by at least 1.125×. Do not impose a strict modular ratio — hand-tune for perceptual
distinctness. Today there are **14 distinct font sizes** including three indistinguishable clusters
(0.8/0.82/0.85rem, 0.9/0.92rem, 1/1.0625/1.08rem) and an `h3` that is **1.6% larger than body text** —
a level that does not read as a level. Body sits on a 65–75ch measure at 1.5–1.6 line-height. No UI
text below 16px anywhere; `rem` resolves against the 16px root, so `0.95rem` is 15.2px, not 16.

**Give desktop an actual page.** At ≥64rem, the single centred column must become a real information
design — and **what that design is, is part of the direction.** A persistent rail plus content region
is one answer; so is a wide content well with a floating index, a two-column reading layout, a
header-led wayfinding structure, or something better. **Do not default all ten directions to the
fixed-left-rail app shell** — that chassis is shared by every SaaS product on earth and choosing it
ten times is how the ten directions collapse into one. Whatever you choose, feeds, galleries, tables
and member grids get their own wider containers while prose stays at a ch-based measure. Today **one rule caps header, main and footer at `--measure: 40rem`**, the repo
contains **zero `display:grid`, zero container queries and zero width breakpoints**, so a 1440px
screen renders 600px of content — 41.7% of the viewport, and it looks like a phone page someone
forgot to finish. Design and show **360×640, 768, 1024, 1440×900 and 1920×1080**, and state what
changes at each: column count, nav pattern, type step, spacing step, image aspect, table reflow.
(Exception: the elder reader stays deliberately single-column. That is a pinned accessibility
decision, not an oversight.)

**Neutrals.** Build a role-mapped ramp per theme — app background, subtle background, element
background, hover, selected, subtle border, border/focus, hover border, solid, solid hover,
low-contrast text, high-contrast text — and **author the dark ramp independently**, never as a
computed inversion. Light mode currently ships 8 neutrals with 5 crowded between `#cdd1d6` and
`#ffffff` and then jumps to `#565b64`: the entire mid-band that separates a border from a fill is
missing, which is why every surface reads flat. Bias the greys toward your accent hue and state the
hue angle and chroma you used. One accent only; semantic danger/success/warning are a separate axis
and may never be reused as decoration.

**Elevation.** Exactly four levels — sunken, base, raised, overlay — and for each level in each theme
state whether depth comes from a hairline border, a surface-lightness shift, a shadow, or a
combination. Light may lean on shadow; dark must carry elevation with surface lightness plus a
hairline, because shadows are invisible on dark grounds. Dark ground is never pure black.

**Hierarchy is the actual craft.** A row of equal-width cards sharing one radius and one padding is
the tell — not any particular pixel value. Every group must differ in span, weight or density,
justified by what a family actually reads first.

**One deliberate exception, and it is a principle, not an oversight: posts in the feed are uniform.**
"Nothing is amplified" means no post may outrank another, so the feed *is* a stream of equal-weight
items and must stay that way. Its rhythm therefore has to come from **content shape** — a text-only
post, a one-photo post, a five-photo post, a link card, a long thread all read differently — and from
the boundary and date markers, never from ranking or emphasis. If your feed is monotonous, the fix is
better differentiation between content *shapes*, not a featured treatment.

**Motion.** CSS only, animating `opacity`, `transform` and colour — never layout. 120–180ms for
micro-interactions, 180–250ms for small transitions, nothing over 400ms. Publish your own named
easing tokens with their cubic-bezier values. Every animated rule needs a
`prefers-reduced-motion: reduce` counterpart that *substitutes an instant state change*, not one that
deletes the feedback. Banned: fade-in-on-scroll, parallax, staggered reveals, skeleton shimmer,
looping decoration, pulsing "live" dots.

### 2.2 The information-design decisions that carry this product

These five are where the design is actually won or lost. Make each one explicitly and say what you
chose; do not let them fall out of a component library.

**These are Phase-3 obligations, not Phase-1 work.** In Phase 1 answer each in one sentence inside
the direction's spec block — no comps, no grids, no matrices. Build them out only once a direction
is chosen.

**1. The two family sides.** This is the product's defining structure — two extended families that
are a hard isolation boundary, bridged by one household that belongs to both. Express the boundary
through **structure, position and labelling**. Do **not** give each side its own hue as the primary
distinction: it produces team colours, dies in forced-colors and in greyscale, and hard-codes one
family's shape into the palette. A member of one side must never be able to infer anything about the
other, so the boundary is a threshold in the layout, not a legend.

**2. Photographs, at every shape they really come in.** Photos are the primary content and they
arrive uncropped from phones. Specify, separately, each of: one landscape, one portrait, one square,
two-up, three-up, four-or-more grid, and the thirty-photo case. Each gets a fixed `aspect-ratio` plus
an `object-fit` rule. **A portrait photo must not blow out the feed's vertical rhythm** — today one
does. Say what happens to a 21:9 panorama and to a 3:4 portrait in the same post.

**3. A named action-tier system.** Three tiers — **primary**, **secondary**, **tertiary-destructive**
— and every control on every surface is assigned one. Destructive is text-weight only: no filled
surface, last in its row or behind an overflow affordance. This is how the "Take down" pill stops
competing with "Open thread" on every post, and it must be a system, not a one-off fix.

**4. The first five minutes, as an ordered arc.** Not a checklist of empty states — a sequence, in
order, as comps: **invite email → join → a near-empty feed → the first post → the first reply → the
first digest**, plus the state that matters most for this product, **"one person has posted and
nobody has replied yet."** That is where reciprocity either happens or the family quietly stops
coming. Design it deliberately.

**5. The age span, with no senior ghetto.** A 79-year-old uses the main app too. It must be legible
to them and unpatronising to a nine-year-old *on the same screen*. There is exactly one simplified
surface — the elder reader — and there is no "senior mode" for the main app and no "kid mode" at all.

**What the data actually looks like** — design against these numbers, not against a mock. From the
code: the feed renders **at most 100 posts** in one page and there is no pagination beyond that, so
the end is genuinely reachable; a post body is capped at **5,000 characters** but in practice runs
one to three short paragraphs; a post carries **up to 20 photos and up to 4 videos**; a thread shows
up to 500 comments, and the reactor name list on a post is capped by the same ceiling. Reactions display **who reacted, by name — never a count**. There are **no
notifications anywhere in the product** — no unread badges, no activity counters, no bell. Most weeks
are quiet, and a quiet week must look intentional rather than broken. Design the 3-post week and the
40-post week, not just the tidy 8.

### The anti-defaults — banned by name, each with its replacement

Generic negation relocates a default rather than removing it, so **every ban below must be answered
with the specific value you are shipping instead, in the same breath.**

- **Banned page grounds:** warm cream / beige off-white — `#F4F1EA`, `#faf8f5`, `#f5f1e8`, `#f3eee3`,
  `#fdfbf7`, `#f7f3ec` or anything in that family.
- **Banned accents:** terracotta, rust, amber-as-brand, sage, forest green (`#15573a`, `#1a4d3a`),
  and any indigo/violet/purple anywhere.
- **A serif or old-style display face is explicitly permitted and encouraged.** What was banned is
  the *cream-plus-serif-plus-terracotta* package, not serif type. Do not read the bans below as a
  reason to default to a sans display face — that is its own tell.
- **Banned token architecture, by name, because these are exactly what a 2026 designer reaches for
  and all three break or silently vacate the guard:** a two-tier primitive-`:root` + semantic-`:root`
  layout; `light-dark()` single-block theming; CSS nesting inside the token blocks.
- **Banned instinct: renaming a token to make it honest.** `--green` currently holds a navy and
  `--amber` currently holds a retired grey. Renaming them is the most natural thing in the world and
  it fails CI at perfect contrast. Give them the right *values*; leave the names alone.
- **Banned wholesale, all three of the known default looks:** (a) cream ground + high-contrast serif
  display + terracotta accent + one italicised word in the headline; (b) near-black ground with a
  single bright acid-green or vermilion accent — **this is the navy "backyard at dusk" direction I
  already rejected, and repainting it a different hue is not an escape**; (c) broadsheet pastiche — a
  masthead with a rule beneath it, a dateline, drop caps, narrow justified body columns. Hairline
  rules themselves are fine and are in fact required elsewhere in this brief; it is the newspaper
  *grammar* that is banned, not the device.
- **Banned effects:** gradient text of any kind, full-bleed gradient hero washes, coloured glows,
  coloured box-shadows, glassmorphism, noise/grain overlays, a 3–4px coloured stripe on a card's left
  or top edge.
- **Banned marketing grammar on an authenticated app:** centred hero, eyebrow or badge above a
  heading, three equal icon-topped feature cards, a numbered 1-2-3 step strip, stat banner rows,
  testimonial blocks, all-caps letterspaced microcopy. Every page opens directly on the family's
  real content.
- **Banned iconography:** emoji anywhere in interface chrome — not as nav icons, not as status, not
  as empty-state art, not inside a button label. Icons ship as inline SVG using `currentColor`, one
  family only. **Specify your own icon system** — grid size, stroke logic, terminal and join
  treatment, optical corrections — and say what it is. Do not reproduce the look of the familiar
  open-source stroke set; a rounded 24×24 1.5px-stroke line icon is itself a 2026 default.
- **Set every heading roman.** No italicised accent word inside a headline.

This list is open and drifting, not exhaustive. A surface that passes every row above and still reads
machine-made has failed. The honest test, per surface: *could this palette be lifted unchanged onto a
fintech dashboard?* If yes, it is wrong — this is one family's shared room, not a product.

---

## 3. What is actually wrong today

Observed directly on a running instance. The screenshots are labelled `BY-01` … `BY-74`; refer to
surfaces by those handles.

1. **Roughly half the application has no design at all.** 34 templates carry the design system.
   **Thirty django-allauth surfaces render the library's raw defaults** — no CSS whatsoever, Times
   New Roman, a literal `Menu:` bulleted list, and a live "Sign Up" link on an invite-only site
   (`BY-01`). **Sign-in is the first surface every family member sees and the one they see most.**
   Plus Django's unbranded `404` (179 bytes, `BY-02`), `500` (145 bytes) and `403 CSRF`.
2. **No desktop design.** ~600px of content in a 1440px viewport (`BY-05`).
3. **The front door reads "Backyard is running / Your family's private instance is up"** (`BY-03`) —
   a health check, shown to an invited relative.
4. **A red "Take down" pill renders on every post** at equal weight to "Open thread" (`BY-05`). A
   destructive moderator action is competing with the primary read action, forever.
5. **No media layout system.** A 4:3, a 3:4 portrait and a 21:9 panorama each render at natural ratio
   at full column width, so a five-photo post is a ragged vertical stack (`BY-07`).
6. **Form controls are browser defaults** — raw `Choose Files / No file chosen`, unstyled selects and
   checkboxes, inside otherwise-styled cards.
7. **Tables are half-styled and the header rule never fires.** Zebra striping, row rules and
   tabular figures already exist in the stylesheet and work — do not re-specify them. What is
   actually broken: neither `members_metrics.html` nor `members_digests.html` declares a `<thead>`,
   so the `thead th` rule is dead CSS, the header renders as an ordinary cell, and the
   `:nth-child(even)` zebra counts the header row and stripes the wrong ones. Adding `<thead>` is a
   template edit — list it in `08-risk-ripple.md`. Genuinely missing: numeric alignment (every cell
   is `text-align: left`, count columns included), headers that wrap mid-word ("Posting / breadth",
   "Catch- / up"), and any reflow strategy — **at 390px the connection-health table renders about
   744 CSS px wide, so the page scrolls sideways at roughly 1.9×. That is a live WCAG 2.2 SC 1.4.10
   failure**, not a nicety.
8. **Dark theme is a near-black IDE ground**, not a designed dusk.
9. **The app icon is illegible at 16px** (`BY-44`).
10. **The weekly digest email is the best-looking surface in the product.** The app does not live up
    to its own email.

**Before you propose any direction**, output a defect table for the **twelve `BY-01`–`BY-12` handles
only** (the first upload message): three specific defects per handle, each with a position in the
frame, and — *where the surface has a stylesheet at all* — the custom property or class hook
responsible. `BY-01` and `BY-02` have no CSS whatsoever, so name the missing decision instead of a
property. Twelve rows, none skipped, none merged. That is the gate; do not design until it exists.
Do not table the other fifty-two handles — they are reference for the build, and forensics on a
design being thrown away is not where your effort belongs.

**The screenshots are the artifact being replaced.** Read them for structure, content inventory and
state coverage. Replicate the structural layout where it is sound, but do **not** carry over the
current palette, typography, spacing or hierarchy.

---

## 4. Scope — and the shortcut nobody noticed

Everything user-facing is in scope. But thirty of those surfaces are not thirty designs:

```
allauth/layouts/base.html      <- the raw HTML document (this is where "Menu:" comes from)
allauth/layouts/entrance.html  <- signed out: login, signup-closed, 5 password-reset pages,
                                  MFA challenge, login-by-code, inactive, verification-sent
allauth/layouts/manage.html    <- signed in: email management, password change, MFA index,
                                  TOTP activate, recovery codes, WebAuthn list/add/edit
```

Every unstyled surface inherits from those three. **So design two layouts, not thirty pages:** an
*entrance* layout (the signed-out credential surface) and a *manage* layout (account settings inside
the app shell), plus a small element kit — button, input with a persistent visible label (never a
floating label), inline error, notice, form actions, page header — that every surface inherits.
Same for errors: `404`, `500` and `403_csrf` are three templates that do not exist yet.

**The 404 is a normal, frequent surface here.** Authorization denials are 404s by design — the
isolation model never confirms that other content exists — so a member hits it in ordinary use. It
must read as ordinary, not alarming. For every error surface: one plain sentence of what happened,
one prominent route back, at most two secondary destinations. No error code as a headline, no
"Oops!", no blame, no spot illustration that displaces the recovery path.

**Credential-surface content rules, non-negotiable:**
- Delete allauth's `Menu:` list and the stock "If you have not created an account yet, then please
  sign up first" line with its live signup link. Signup is invite-only and the adapter refuses it.
  State invite-only plainly and tell someone without an invite exactly what to do (ask the relative
  who runs it). Design that dead end as a finished, warm surface, not an error.
- **Account enumeration prevention is on.** Exactly one non-committal password-reset confirmation
  ("If that account exists, we've sent instructions") and one generic sign-in failure. No copy,
  icon, colour or layout may distinguish "wrong password" from "no such account". A "we couldn't
  find that email" state is a security regression, not a UX improvement.
- **Passkeys are a discrete primary button, not browser autofill.** The shipped library renders a
  separate passkey submit button and contains no conditional-mediation support. If you want the
  `autocomplete="username webauthn"` autofill pattern, list it in the handoff as a separate
  engineering item — do not assume it exists.
- Explain a passkey as "the fingerprint, face, or passcode you already use to unlock this device",
  visible by default with no hover or click. Message before the OS dialog and confirm after. One
  card per credential with a human label ("James's iPhone, added March 2026"), never a credential ID.
  Keep a visible non-biometric path on every screen that offers biometrics. Never prompt to create a
  passkey during sign-in — prompt at join, in settings, and after a password reset.
- A 79-year-old is expected to transcribe a TOTP secret today (`BY-64`). Never require anyone to
  remember, manipulate or transcribe anything; never block paste or a password manager.

**Also in scope, and easy to miss:**

- The weekly digest email (§8).
- **The other transactional emails.** The auth library ships **42 email template files**, all raw
  plain text with stock wording — password reset, email confirmation, email changed, account already
  exists, and so on. Every one of them is a message a family member receives from us. Give them a
  single shared plain-text house style (they must stay text; do not turn them into HTML) with our
  wording, our signature, and the same anti-phishing line the digest carries.
- **There is no photo viewer.** Tapping a photo opens the raw image file served by the access-checked
  media view — no template, no chrome, no next/previous, no caption, no way back except the browser.
  For a family photo product that is the most-used interaction in the app. Decide deliberately: either
  design a real full-size view (server-rendered, no JS) and say so, or state on the record that the
  raw-image behaviour is acceptable and why.
- The PWA identity — icons, maskable safe zone, monochrome silhouette, apple-touch-icon, light and
  dark `theme-color`, a manifest background that does not flash white — and the favicon at 16px.

---

## 5. The platform contract — refuse rather than violate

This is a server-rendered Django app with no bundler. If any part of your proposal needs something
below, **say so explicitly and propose a conforming alternative** rather than quietly emitting it.

**Cannot ship, ever:** React/JSX/Vue/Svelte, Tailwind or any utility-class taxonomy, CSS-in-JS, an
npm package, a token pipeline that needs a build step, `@import`, any external/CDN URL, any **new**
`<script>` or inline event handler.

One script already exists and must survive byte-identical: the nonce'd service-worker registration
at the end of `core/base.html`, inside its `{% if user.is_authenticated %}` block. Keep it, keep the
`{{ request.csp_nonce }}` on it, and keep it authenticated-only. Two small nonce'd handlers also
drive the hand-over page's copy and share buttons; leave them alone too.

**All application CSS is plain CSS inside ONE `<style>` block in
`src/core/templates/core/base.html`** (currently lines 20–479 of a 519-line file). Two documented
exceptions: `elder_feed.html` is standalone with its own `<style>`, and the `500` page must be
standalone with its own inlined `<style>` because it renders when the app is already broken — no
`{% extends %}`, no context processors, no DB values, no template tags.

**Content-Security-Policy, verbatim from the middleware:**
```
default-src 'self'; script-src 'self' 'nonce-{nonce}'; style-src 'self' 'unsafe-inline';
img-src 'self'; object-src 'none'; frame-src 'none'; base-uri 'self'; form-action 'self';
frame-ancestors 'none'; connect-src 'self'; worker-src 'self'; manifest-src 'self'
```
Consequences: **`script-src` is nonce-based, so no core UI state may depend on JavaScript** — no JS
dropdowns, tabs, modals, carousels, spinners or scroll-triggered motion. Every hover, focus-visible,
active, open/closed state and the elder big-text toggle must be pure CSS plus a server round-trip.
**There is no `font-src` directive**, so fonts fall back to `default-src 'self'`: same-origin fonts
are allowed and **`data:` URI fonts are blocked**. Same for `img-src 'self'` — no `data:` images, so
inline `<svg>` in markup, never a data-URI `<img>`.

**Static files — corrected, because this was wrong in the previous brief.** WhiteNoise with
`CompressedManifestStaticFilesStorage` is configured and `collectstatic` runs at boot. `{% static %}`
**works** for any file that actually exists (an installed library asset resolves fine); it 500s only
for a path that was never collected. The project simply ships no static directory of its own yet.

**So a real, self-hosted webfont is available to you** — put a `.woff2` in a new
`src/core/static/backyard/fonts/` and reference it with `{% static %}` inside the one `<style>`
block; `default-src 'self'` permits it. **Conditions if you use one:** at most two faces, subset,
`font-display: swap`, a metrics-matched system fallback stack, total added weight stated in KB and
justified against a grandparent on a slow connection, and the licence named. A system stack remains
a legitimate choice — but it is now a choice, not a cage. Say which you picked and why.

**Copy is testable.** Many pytest tests assert exact user-facing strings. Copy changes are welcome
and often needed — but every changed string must be listed separately, old → new, or the build goes
red.

---

## 6. The two CI guards — the arithmetic is part of the deliverable

Guard 1 text-parses `base.html`; guard 2 renders the elder page and parses the returned HTML. Ship
the numbers, not an opinion. **Never route around a guard**; if you find a way to satisfy one
without meeting the bar, report it as a guard defect to be closed.

**Guard 1 — `test_design_system_wcag.py`** text-parses the stylesheet.

- Token regex: `--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6}|var\(--[a-z0-9-]+\))`. Inside the two parsed
  blocks, every **colour** custom property must be **exactly** `--name: #rrggbb;` or a
  **single-level** `var(--other-token-declared-in-the-same-block)`. Forbidden *there*: `oklch()`,
  `color-mix()`, `rgb()`, `hsl()`, `light-dark()`, 3-, 4- and 8-digit hex, `var(--x, #fallback)`,
  and any two-level alias chain. **8-digit hex is the dangerous one: it is silently truncated to 6
  digits, so CI goes green while the browser paints near-invisible text.**
  **The non-colour tokens are unaffected** — the regex only *captures* declarations already shaped
  like a colour, so `--radius`, `--radius-sm`, `--shadow`, `--font-display`, `--font-body`,
  `--font-mono`, `--measure` and `--step` live happily in the same `:root` with any valid CSS value
  (`--shadow` is `rgba()` layers today and must stay that way — an alpha shadow cannot be 6-digit
  hex). Do not try to hex-ify them. Modern colour syntax is fine in **rule bodies** — the file
  already uses `color-mix()` in seven of them with CI green — but never in a custom-property
  declaration in *any* of the four palette blocks, including the two `[data-theme]` blocks nothing
  checks. Derive your ramp in OKLCH offline and emit hex.
- **Structure is contract.** The light `:root {` must be the **first** `:root` in the file. The dark
  override must be literally `@media (prefers-color-scheme: dark) { :root { … } }` — no compound
  query, no `:root, :host` list, no sibling rule before it. **Neither block may contain a nested
  `{}`** (no CSS nesting, no `@supports` inside). Both capture regexes are lazy and stop at the first
  `}`. Put every other `@media` block — breakpoints, forced-colors, reduced-motion, print — *after*
  the token blocks. Get the ordering wrong and both themes resolve to the dark palette, every pair
  passes against itself, and the suite reports PASS while the light theme is never tested.
- **13 frozen token names** must exist, spelled exactly, in both parsed blocks — a rename fails
  before any ratio maths runs:
  `--ink --ink-soft --paper --surface --surface-sunk --green --green-tint --amber --amber-tint
  --danger --danger-tint --btn-ink --btn-bg`
  (Note `--green` is currently navy `#234a78` and `--amber` is a retired neutral `#55585f`. The names
  are frozen; the values are yours.)
- **The palette is declared four times**: `:root`, the dark `@media :root`, `:root[data-theme="light"]`
  and `:root[data-theme="dark"]`. Only the first two are guarded. **Update all four** or the manual
  theme toggle silently drifts below AA.
- **26 token names total and 66 class hooks** are consumed across the templates. Add freely; never
  rename or remove. The full lists are in §9.
- Deliver the **34-row contrast table** (17 pairs × 2 themes): `theme | fg token | fg hex | bg token |
  bg hex | ratio | pass/fail vs 4.5`, computed with the WCAG 2.x sRGB relative-luminance formula.
  Plus a second table for every new text pair you introduce, flagged for addition to the guard.

**Guard 2 — `test_elder_wcag.py`** renders the live elder page and parses the HTML.
`src/core/templates/core/elder_feed.html` is a standalone document with its own `<style>` and no
`{% extends %}` — **nothing in `base.html` reaches it. Treat it as a second, separate stylesheet.**
It asserts: the first `body { }` rule declares both `color:` and `background:` as literal 6-digit hex
at **≥17.0:1**; the literal `#444444` clears 4.5:1 against that background (a legacy floor — the
colour is no longer on the page, so darkening the elder background can fail on a colour you never
used); at least one **integer-px** `min-height:` and one **integer-px** `min-width:` still exist and
**no integer-px min dimension on the page is below 44** — the enforced constant is `_MIN_TAP_PX = 44`
and the page currently declares 48, which is the design intent; hold 48 (rem, decimal px and `var()`
are invisible to the regex, so tokenising *all* elder tap sizing silently vacates the guard — keep at
least one literal integer px so it still bites); exactly one `<main>`;
and every `href` on the page equals the elder-feed URL.

**Elder carve-out — read this before applying anything from §7 or §8 to the elder page.** That last
assertion collects **every `href` attribute in the returned HTML, `<link>` elements included**, and
requires each one to be the elder-feed URL. So on `elder_feed.html` — and only there — you must not
add a `<nav>`, a skip link (`href="#main"`), a favicon or icon `<link>`, a manifest link, a
"Need help?" link, or any other anchor. The single obvious way back is the only link that page gets.
Two more strings on that page are frozen by the same guard: the rendered output must still contain
the `elder_text_size` URL **and** the literal text `Bigger text` or `Regular text`. §7's verb-first
copy rule does **not** apply to those two labels — renaming them reds the build.
Express elder breakpoints in rem/em, because a `min-width: <N>px` media query is scraped as if it
were a tap target.

---

## 7. Accessibility — WCAG 2.2 AA is the floor, and it is not just contrast

Design to **WCAG 2.2 Level AA** using WCAG 2.x relative-luminance maths: 4.5:1 normal text, 3:1 large
(≥24px, or ≥18.66px bold) and non-text. Do not design against WCAG 3.0 and do not use APCA anywhere —
the guards compute 2.x luminance and will red-build a palette that assumes different maths.

**Known failures you are fixing (SC 1.4.11 Non-text Contrast, unguarded today):** the composer
textarea's border is `#e4e7ea` on `#ffffff` = **1.24:1** — on the primary posting surface. Input
borders are 1.34–1.53:1 across the three grounds; the dark primary button fill is 2.21–2.43:1 on its
grounds. Add a **new** token (for example `--line-input`) at ≥3:1 rather than reusing the decorative
`--line`/`--line-strong`.

**Focus.** Keep `:focus-visible { outline: 3px solid var(--ring); outline-offset: 2px; }` — an
outline survives forced-colors (it is re-coloured, not stripped) whereas `box-shadow` computes to
`none`. **Never redraw a focus ring with `box-shadow`.** Fix one latent bug: light `--ring` is
byte-identical to `--btn-bg` (`#234a78`), so the ring vanishes on primary buttons the moment the
offset is lost.

**Add `@media (forced-colors: active)` — the repo has none.** Forced colours strip `box-shadow` to
`none`, which removes the *only* boundary on feed and comment cards (five shadow declarations), kills
both gradients, collapses the tint-only `.role` pill into plain text, and erases the `color-mix()`
divider under the feed end-cap. Give those a real `border: 1px solid ButtonBorder`/`CanvasText` and a
`currentColor` glyph. Add `@media (prefers-contrast: more)` too.

**Targets.** ≥44×44 CSS px in the member app, ≥48×48 on the elder surface and on primary actions,
with ≥8px separation in wrapped action rows. Current offenders: reaction buttons at 40px, and the
inline action buttons at ~24px inside a row whose wrapped gap is ~6.4px. For a checkbox, make the
whole label the target and size *it*.

**Never colour alone.** Every stateful control pairs colour + a shape or glyph + text. The codebase
already does this correctly for the `.flag` pill and the reacted checkmark — extend it to `.role`,
selected pod, errors, and the moderator control. And **deliberately de-weight destructive actions**:
"Take down" drops to a tertiary tier — text colour, no fill, last in its row, separated by at least
8px. If you want it behind a disclosure, the only mechanism available is native
`<details>/<summary>`, which needs no JavaScript and no ARIA; say so if you use it
while "Open thread" stays primary.

**Also required, and routinely dropped:** 320px reflow with no two-dimensional scrolling (SC 1.4.10 —
give the explicit table-to-stacked-card CSS for the six admin tables and the directory); 200% text
zoom and 400% browser zoom; SC 1.4.12 text-spacing with no clipping; `<html lang>`; landmark
structure **in the member app only — the elder page takes no nav and no skip link, see the carve-out
in §6** — there is currently **no `<nav>` element in any of the 34 templates** and only six
`aria-label`s app-wide; a persistent "Need help?" affordance in the same position on every surface
except the elder reader (SC 3.2.6) — note there is **no help route in this app and none is being
added**, so it is one plain sentence naming the relative who runs the instance, not a link; preserved entries across validation errors and back-navigation (SC 3.3.7); and if you
introduce any sticky chrome it must never obscure a keyboard-focused element (SC 2.4.11) — pair it
with `scroll-margin-top` and state the px value.

Prefer semantic HTML over ARIA. In a no-JS, nonce-CSP Django app there is no legitimate need beyond
`aria-hidden` on decorative SVG and `aria-current` on the active nav item. No roles, no
`aria-expanded`, no live regions.

**Language.** Every control has a visible text label at a 6th–8th grade reading level. No icon-only
controls anywhere; if an icon is unavoidable it is icon *plus* visible text, never icon plus
`aria-label` alone. Active voice, present tense, device-neutral verbs ("choose", never "click" vs
"tap"). Errors render inline beside the field, say what to do next, and preserve what was typed.
Every destructive action gets an explicit confirm with a plainly-worded consequence and a visually
larger Cancel.

**The voice, positively stated:** plain, warm, literal. Written the way a family member writes a
note, not the way a product writes onboarding. Sixth-to-eighth grade reading level, active voice,
present tense, device-neutral verbs. It should never sound like it is trying to be liked.

**Print.** `base.html` already carries an `@media print` block and elders are the likeliest people in
this family to print a post or a digest. Keep and update it: black on white, legible, with URLs
expanded. Say so in the handoff rather than dropping the rule silently.

**Copy discipline:** buttons start with a verb and name the outcome ("Post to the Backyard", "Save
changes") — never "Submit", never a bare "OK". At most one "not X, it's Y" construction in the entire
product; at most two or three em-dashes across all UI copy; zero exclamation marks outside one
genuine celebration; no three-item list unless exactly three things exist. Banned words: seamless,
robust, elevate, empower, unlock, delve, leverage, streamline, holistic, revolutionise, cutting-edge,
best-in-class, game-changer, tapestry, landscape, realm, harness.

---

## 8. The email, and the identity assets

**Rebuild the digest as a complete standalone HTML document**, not the current 66-line fragment:
`<html lang="en" dir="ltr">`, a `<head>` with `<title>`, `<meta name="color-scheme">` and
`supported-color-schemes`, `lang`/`dir` on the body's children, `role="presentation"` on every layout
table, exactly one `<h1>`, discernible link text, real `alt` on every image. Keep the table layout
and inline hex — the Word rendering engine is supported for years yet.

**Fix the one real defect:** `#8a8f98` on `#ffffff` is **3.25:1**, used at 12px and 14px where the
4.5:1 bar applies with no large-text relief — and it renders the two most load-bearing strings in the
product: the `=== reply above this line ===` separator the inbound reply parser depends on, and the
standing notice "Backyard will never ask for your link or password by email." Take it to ≥4.6:1 and
set email body copy at ≥16px. **No CI guard reads any email template**; that gap is an obligation to
self-certify, never permission to ship below AA. State every computed ratio.

**Dark mode in email is additive, in three layers, never a single bet:** (1) the authored light
palette must still clear 4.5:1 after a naive brightness inversion, because no Gmail surface honours
`prefers-color-scheme`; (2) ship `@media (prefers-color-scheme: dark)` in an embedded `<style>` —
Apple Mail honours it and is roughly 65% of opens; (3) add duplicated `[data-ogsc]`/`[data-ogsb]`
rules for the Outlook partial-invert family. Never `#ffffff` or `#000000` in the email.

**Do not use inline `<svg>` for the email brand mark** — Gmail, Outlook, Yahoo and AOL do not render
it, and the current markup's wordmark is a sibling `<span>`, not a fallback, so those clients get a
wordmark beside an empty box. Ship a type-only lockup, or a hosted PNG authored at 2× and displayed
at 1× with styled alt text. Deliver the images-off state as a named comp.

**Identity assets.** The mark must survive four rungs: 16px favicon → header wordmark → flat
one-colour on the elder page → flat one-colour in email and print. It fails the first rung today
(`BY-44`). Ship the full icon set — 192 and 512 "any", 192 and 512 maskable, and a 512 **monochrome
alpha silhouette** for Android notification badging — with the maskable mark drawn to a circular safe
zone of 80% of the icon's minimum dimension over an opaque bleed, proved against circle, squircle and
rounded-square masks. `apple-touch-icon` is a separate 180×180 opaque pre-padded PNG. Give
`theme-color` a light and a dark value. Move the icon `<link>` tags out of the
`{% if user.is_authenticated %}` block — only the manifest and service-worker registration stay
authenticated-only. Icons may now be real static files under `src/core/static/`, since `data:` is
blocked by `img-src 'self'`.

---

## 9. The frozen contract

**26 CSS custom-property names** — values are yours, names are not. Adding new ones is encouraged.

```
--paper  --surface  --surface-sunk  --ink  --ink-soft  --line  --line-strong
--green  --green-deep  --green-tint  --amber  --amber-tint  --danger  --danger-tint
--btn-bg  --btn-bg-hover  --btn-ink  --ring  --radius  --radius-sm  --shadow
--font-display  --font-body  --font-mono  --measure  --step
```

**66 class hooks in use across the templates** — style these, add freely, never rename or drop one.

```
actions anniversary author back back-wrap birthday boundary brand byline caught-up clip
clip-status comments composer contact contacts danger date-banner delivery digests directory
edited empty errors expiry feed flag handover handover-actions house-rule inline inline-check
invites kinship members metrics muted notice on photos pod pod-name pods post preview
preview-desc preview-image preview-title preview-url qr quarantine react-buttons reacted
reaction-label reactions redeemers role site skip-link top uses via-email visually-hidden
when wrap yards
```

**Element IDs and attribute hooks — also frozen**, because label associations and the two pieces of
nonce'd JavaScript that do exist bind to them:

```
ids:   main  photos  videos  pod_id  yard_id  username  password  display_name  kinship_name
       elder_name  household_name  pod_name  yard_name  setup_secret  cadence  phone
       contact_email  address
attrs: data-handover-link  data-handover-copy  data-handover-copied  data-handover-share
       data-share-title  data-theme  [hidden]
```

`data-theme` is the manual light/dark override on `:root`. The `data-handover-*` set drives the
copy-link and share buttons on the hand-over page; `[hidden]` is how the "copied" confirmation stays
honest without JavaScript-dependent state. Style them; never rename them.

---

## 10. The handoff — this is the final deliverable

Export via **Hand off to Claude Code**. Prose in the chat is not a deliverable; the bundle ships the
chat transcript by default, so *also* state rationale and computed ratios in chat — but **no file may
depend on the chat being read.** Write exactly these files:

| File | Contents |
|---|---|
| `00-APPLY-ORDER.md` | What lands first and what breaks CI if applied out of order; which steps are file **creation** versus **edit**; which steps need my authorization (a new route, a new static asset, any change to a test file); and what to run after each step |
| `01-base-style.css` | A complete, literal, copy-paste-whole replacement for everything between `<style>` and `</style>` in `base.html`. No fragments, no "…unchanged…", no diff hunks, no interleaved commentary. It will be applied by replacing those bytes verbatim and immediately running the two guards. If it does not survive that exact operation it is not done. |
| `02-tokens.json` | Every token, old value → new value, per theme, all four blocks |
| `03-state-matrix.md` | One row per interactive element type; columns default / hover / focus-visible / active / disabled / submitted (server round-trip) / invalid / required / read-only / selected / visited / empty. Each cell gives the exact CSS declarations that change, not a description. Every state must fire without JavaScript. Where a state has no CSS-only mechanism, write `n/a — <one-line reason>`; that counts as a pass. There is no client-side pending state in this app and `:visited` is restricted by every browser to colour-ish properties only. Name the non-colour cue in every error/success/selected/required cell. |
| `04-surfaces/<name>.md` | One per surface — all 34 project templates, the 30 allauth surfaces, and 404/500/403. Fixed template: purpose and who uses it; anatomy; desktop spec; 320px spec; every state cross-referenced to `03`; empty and error states with **real copy, never lorem**; heading and landmark map; numbered focus order; alt-text policy; class hooks used; do/don't; WCAG SCs claimed. The admin long tail and the no-login token surfaces are not optional — they are what a design pass always drops. |
| `05-elder.css` | The standalone elder `<style>`, with its own numeric proof |
| `05b-auth-kit/` | The *entrance* layout, the *manage* layout, and the element kit, as complete template bodies — this is template **creation**, not restyling: no override directory exists yet, so roughly thirty-three new files follow from these |
| `05c-error-pages/` | Complete literal HTML for `404`, `500` (standalone, self-contained `<style>`) and `403_csrf` |
| `05e-static-assets.md` | Every binary you need but cannot author as text. For a webfont: family, version, licence, source URL, the exact subsetting command, the resulting KB, and the literal `@font-face` block. For the PWA rasters: the source SVG plus the exact sizes and the safe-zone geometry. I generate the binaries; you specify them. |
| `05d-icons/` | Every icon as **literal SVG source**, plus the exact template edit each one implies — inline SVG means editing 33+ templates, and those edits belong in `08-risk-ripple.md` too |
| `06-email-digest.html` | The complete standalone email document |
| `07-proofs.md` | The 34-row contrast table, the new-pairs table, the elder table, the email table (authored **and** inverted) |
| `08-risk-ripple.md` | Everything outside the stylesheet this changes — `theme-color`, manifest colours, every icon, `elder_feed.html`, the email template, every template markup edit a new hook implies — **plus one separate list of every changed user-facing copy string**, because pytest asserts exact copy. Finish with what you deliberately did not change, and why. |
| `09-self-audit.md` | PASS/FAIL with evidence, per line (below) |
| `ASSUMPTIONS.md` | Everything you assumed, and everything you could not do inside the constraints |

**`09-self-audit.md` must answer PASS or FAIL with evidence on each of these**, and you must fix any
FAIL before handing back — never hand me a package with a known FAIL:

- every token in both parsed blocks is 6-digit hex or a same-block single-level `var()` alias
- no 8-digit hex anywhere in either block; neither block contains a nested brace
- the light `:root` is first in the file; the dark block is the exact `@media` form
- all 13 frozen names present in both blocks; all four palette blocks updated
- all 34 contrast rows ≥ 4.5; every new pair computed
- elder body ratio ≥ 17.0; `#444444` ≥ 4.5 on the elder background; at least one integer-px
  `min-height` and `min-width` remain and none is below 48; exactly one `<main>`; no added hrefs
- no `{% static %}` reference to a file you did not also deliver; no `@import`, no external URL, no
  `<script>`, no inline handler, no `data:` font or image
- every state-matrix cell has a CSS-only trigger
- the forced-colors block covers cards, `.role` and the end-cap divider, and preserves the outline
  focus ring
- every surface has a `04-surfaces/` file
- **the anti-default audit**: one row per surface, pass/fail against every banned item in §2, plus
  the one-line answer to "could this palette be lifted unchanged onto a fintech dashboard?"

Finally, self-grade every surface and every variant as **bad** (fails the spec), **thin**
(insufficient visual coverage) or **variantsIdentical** (variants that do not actually differ), and
report the counts. Any non-zero count blocks handoff. In Phase 1 this is the anti-clone gate: if the
ten concepts share a palette or a type system they are `variantsIdentical` and must be regenerated.

I will re-capture every surface at the identical handles, viewports and DPR after applying this.
Structure each recommendation so it is verifiable from the same-handle screenshot.

**Say explicitly whether the wordmark changes.** The mark appears in three places — the app chrome,
the email lockup, and the PWA icon set. If it changes, deliver all three. If you are leaving it
alone, say that too, rather than leaving me to infer it.

---

## 11. If this still disappoints me

One complete pass has already been rejected, so plan for the possibility.

- **Name your three least-confident decisions** at the end of Phase 3, before I look. If I dislike
  the result, that list is where we start.
- **If I reject the direction, go back to Phase 1 and give me directions that are not neighbours of
  the rejected one.** Do not re-skin the same structure in a different hue — that is what "backyard
  at dusk" was, and it is why it failed twice over.
- **If I say only "it still feels AI-generated" without more,** do not guess. Ask me for exactly two
  things: the single worst surface, and one **non-software** reference artefact I like — a book, a
  sign, an object. Then work from those.
- **Never respond to dissatisfaction by adding decoration.** More texture, more illustration, a
  bigger hero: every one of those makes it worse. But do not reach for subtraction either — stripping
  a page back further is how you arrive at the neutral SaaS default that was rejected in the first
  place. **The fix is more conviction, not less design:** a stronger type idea, a more committed
  structure, a real colour decision held consistently. If the page is boring, it usually needs a
  louder thesis, not a quieter one.
- **The ban list in §2 is not exhaustive and passing it is not proof of distinction.** Space Grotesk
  became a tell because it was the popular escape from Inter. If a surface clears every row and still
  reads machine-made, it has failed, and the honest thing is to say so rather than cite the checklist.
