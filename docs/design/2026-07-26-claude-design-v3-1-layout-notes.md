# 06 — v3.1 layout addendum notes

Apply: replace the <style> block in src/core/templates/core/base.html with the FULL
01-base-style.css in this bundle (it is the complete v3.1 file, not a fragment).
Nothing else in the bundle changed; do not re-apply the elder/email/allauth/error files.

## Breakpoints (mobile-first, all @media AFTER the guarded token blocks)
- base — one column, 40rem well. Unchanged phone layout.
- sm 37.5rem (600px) — gutters 1.25rem -> 2rem, h1 1.55 -> 1.8rem,
  directory becomes a 2-column card grid.
- md 64rem (1024px) — the shape change: main.wrap becomes a two-region grid,
  a 44rem reading well + sticky 19rem "signpost" rail (aside.rail), 4rem gutter,
  shell 72rem. Pages with no aside.rail get a single centred 56rem well.
  Prose keeps a 34rem measure; feeds/galleries/tables take their region's width.
- lg 75rem (1200px) — well 46rem, rail 21rem, 5rem gutter, shell 80rem,
  directory 3 columns.
- Shell caps at 80rem: 1440x900 and 1920x1080 render the same centred composition.
- Why not a persistent left app-rail: five quiet links cannot honestly fill one,
  and a fixed rail reads as a dashboard — against the product principles. The
  margin rail is wayfinding beside a path: secondary, sticky, absent where a page
  has nothing to say.
- The elder reader is untouched and stays single-column at every width (pinned).
- Container queries deliberately not used: every adaptive region tracks the
  viewport-driven well directly, so @media is sufficient and cheaper to audit.

## Photo grid rules (class hooks unchanged: .photos, .photos a > img, .clip)
- 1 photo — natural aspect-ratio, max-height 26rem, centred (never cropped;
  a lone portrait or 21:9 panorama is height-capped, not blown up).
- 2-up — 2 equal columns, cells aspect-ratio 1/1, object-fit cover.
- 3-up — 3 equal columns, square cells, cover.
- 4+ (incl. the 20-photo cap) — repeat(auto-fill, minmax(8.5rem,1fr)) square
  tiles, cover; 20 photos = ~4-5 uniform rows inside the well.
- Mixed ratios in one post (e.g. 21:9 panorama + 3:4 portrait): identical square
  tiles, centre-cropped; the untouched original is one tap away (the existing
  serve_media <a> wrapper). Vertical rhythm is therefore fixed per layout.
- Video .clip: aspect-ratio 16/9, cover (poster frames stop varying row height).
- Counting is pure CSS (:has + :nth-last-child) — no JS, no template change.

## Table/list reflow < 40rem (SC 1.4.10 fix)
Tables collapse to stacked cards; td::before prints the column name from
data-label. Admin ULs (members, invites, digests, quarantine, pods) drop to
stacked blocks with actions on their own line. directory reflows via its card
grid (1 col below 37.5rem).

## Implied template edits (small, server-rendered, no JS)
1. aside.rail — wrap each page's wayfinding in <aside class="rail"> as the
   element right after <h1>:
   - feed.html: the "Your pods · Family directory" link line + the date-banner.
   - members.html: the invite/add-grandparent/invites action links.
   - directory.html: the edit-profile/export links (search stays in the well).
   Pages without the aside automatically get the single centred well.
2. members_metrics.html: add a real <thead>/<tbody> (also fixes the unstyled
   header defect) and data-label="Week|Yard|Connected|..." on every td.
3. members_digests.html: data-label on every td.
4. Block-seam check (carry-forward from the entrance-layout defect): this round
   wraps no Django blocks — aside.rail is plain markup inside {% block body %},
   and the reflow CSS keys on attributes only.
