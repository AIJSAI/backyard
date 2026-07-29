# Design v3.2 — the visual pass, and the two defects underneath it

**PR:** [#96](https://github.com/AIJSAI/backyard/pull/96) · **merged** as `d3f71b3` ·
**deployed and re-verified live** at https://backyard.family

v3.1 made the layout coherent. It had never had a pass on **type, density or layout
craft**, and every screen showed it. This is that pass, plus two real defects it turned
up on the way — both of which had already survived a green suite and a clean axe sweep.

## How this was judged

By rendering every surface at **1440 and 1728 and looking**, then by **measuring
geometry in the browser**. Not by axe: the previous sweep reported *154 renders, 0
violations* with every defect below present, which is the standing lesson on this
project. Where a number is quoted here it was measured, not estimated.

## What changed

**Type.** The scale ran 1.04 / 1.18 / 1.55rem against a 1.0625rem body — an `h3`
*smaller* than a paragraph and an `h2` four percent above one, so nothing on a page said
what mattered. Now 1.75/2.05rem display, 1.28/1.35rem section, and the post body set a
shade above the interface around it at a reading line-height.

**Density.** The composer was ~560px of form standing between a member and the first
photograph in their family's feed. Same fields, same names, same action, grouped onto
rows: ~365px. A birthday had month, day and year on three full-width rows, twice on the
profile page. The directory's search box and its button were two rows.

**Shell 46rem → 52rem.** At 46rem a three-photo post rendered three 166px stamps at 1440.
Prose stays capped at 34rem, so the reading measure did not move — only the photographs
got their room back.

**Craft, per surface.** The thread page had no `h1` and its replies had no grouping (the
gap between one reply's text and the next reply's *name* equalled the gap between a name
and its own text). The members roster rendered five expanded removal forms at once —
2383px, four-fifths of the page — with a supervised child's name vertically centred
beside the form that deletes them. Two of three create-pod fields were placeholder-only.
The visibility selects carried only an `aria-label`. Sign-in shipped allauth's `Login:` /
`Password:` / `Remember Me:` with Django's colon suffix. Back links had four different
treatments across four pages, three of them duplicating a header nav link.

**Fluff cut:** the footer tagline, `(optional)` on both composer pickers, the redundant
landing sentence, the decorative tick on "You are all caught up".

**SC 3.2.6:** the help sentence keeps its pinned substring; only the trailing
"— they can fix it" came off. Neither test in `test_accessibility_modes.py` was moved.

## What was tried and rejected

The pass warmed the page ground to a linen cream (`#f7f4ed`), chasing "warmth" from the
brief. **The founder rejected it on sight** as the palette of a design run he had already
turned down, and reverted it in-branch. The colour system is v3.1's again, token for
token.

Nothing in the repo stopped that. The guard on the rejected identity —
`test_no_surface_still_carries_the_rejected_v2_navy` — pinned **exactly one hex**, the
navy. A guard that names one value from a rejected direction reads as covering the
direction when it covers only that value. It now holds a map of rejected colours, names
which is which in the failure, and is proven non-vacuous both ways.

Three regressions the founder caught by eye, all introduced by this pass, all now
measured rather than eyeballed:

| | before | after (1440 / 1728) |
|---|---|---|
| "You are all caught up" vs the well's centre | visibly left | **+0.00 / +0.00px** |
| footer sentence vs the page centre | left-aligned | **−0.01 / −0.01px** |
| lone photo vs its card's centre | left-aligned | **−0.01 / −0.01px** |
| composer row, select vs sides (top / bottom) | 3.5px apart | **0.00 / 0.00px** |
| checkbox vs its label | **−4.59px** | **+0.80px** |

Two of the three were **cascade collisions in this pass's own new CSS**: `.caught-up` is
(0,1,0) against `main.wrap > p` at (0,1,1), so the 34rem prose cap boxed it into a 544px
column at the left of the well; and the `margin` shorthand in the same rule reset the
`margin-inline: auto` written to fix it.

## Two defects a green suite and a clean sweep both missed

**1. Every primary button was below AA while hovered.** `--btn-bg-hover` in dark mode was
`#35906d` — **3.92:1** against the white label. It shipped in v3.1 and survived two
138-render axe sweeps reporting zero violations, **because an automated sweep never
hovers**. Found by accident (a pointer happened to rest on a button after a form submit),
then made deliberate: the sweep now parks the pointer for the resting scan and runs a
second scan with the primary button hovered. Same page, same tool: **0 violations at rest,
the failure when hovered.** Fixed to `#226047` (7.41:1) and `("btn-ink", "btn-bg-hover")`
added to `test_design_system_wcag`'s pair list, proven by reverting the token and watching
the guard fail.

**2. Five form controls shared one accessible name.** The visibility selects began with
field-specific `aria-label`s. This pass replaced them with a visible label — right for
sighted users, and in its first cut a bare "Who can see it" on all five, which is strictly
worse for a screen reader than what it replaced. Caught by Copilot on the PR, conceded,
and fixed by putting the noun in the **visible** text rather than an `aria-label` (an
`aria-label` differing from the visible label would have been a fresh SC 2.5.3 Label in
Name failure). Guarded by `test_no_page_gives_two_controls_the_same_accessible_name`.
**axe reports nothing here** — duplicate accessible names violate no single success
criterion — so this class needs the test.

## Verification

| | |
|---|---|
| ruff + ruff format + mypy(152) | clean |
| pytest | **657 passed / 2 skipped** |
| axe WCAG 2 A/AA + 2.2 AA — **local** | **136 renders, 34 surfaces**, desktop + mobile, light + dark, each with a deliberate hover pass — **0 violations at any severity** |
| axe — **production** | **96 renders, 24 surfaces** — **0 violations at any severity** |
| geometry | measured in-browser at 1440 and 1728, table above |

Raw reports: `2026-07-29-axe-v32-local.json`, `2026-07-29-axe-v32-PROD.json`.

**Coverage honestly stated.** The production sweep covers 24 surfaces, not 34: eight
admin surfaces (`members`, `members-invites`, `invite-household`, `new-elder`,
`family-sides`, `metrics`, `digests`, `quarantine`) need an instance-admin login that the
session did not have on production, and the sweep **names what it skipped** rather than
reporting a smaller number as a clean sweep. They are covered in the local run. One
surface from the v3.1 list, `login-code-confirm`, does not exist in this configuration
(`LOGIN_BY_CODE_ENABLED` is unset).

## Not changed, deliberately

- **The elder path.** Standalone, serif, light-only, single-purpose, already passed, and
  guarded by `test_elder_wcag` plus the every-href rule. Reviewed in source, left alone.
- **`home.html`'s `h1`.** "Backyard is running" reads like a status page rather than a
  front door. It is pinned by `test_setup.test_home_shows_landing_to_a_logged_out_visitor`
  and rewording it was not authorised. Flagged, not touched.
- **A lone photo's size.** The feed serves the 400×400 thumbnail rendition
  (`core/media._THUMB_MAX`), so one photo cannot fill a 52rem column without upscaling.
  Capped at 25rem and centred. Filling it properly needs a mid-size rendition out of the
  media pipeline — not a stylesheet's decision.
