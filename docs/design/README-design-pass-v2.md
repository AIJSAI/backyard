# Design pass v2 — how to run it

The v1 pass was rejected ("not sophisticated, not production enterprise grade"). This is the retry,
built from live-sourced research on how Claude Design actually responds, plus a full capture of every
user-facing surface in the product.

## What is in the package

`~/Downloads/backyard-design-package/`

| Item | What it is |
|---|---|
| `00-KICKOFF-PROMPT.md` | The prompt. Identical to `docs/design/claude-design-kickoff-v2.md`. |
| `UPLOAD-PLAN.md` | The label line to paste before each image, message by message. |
| `message-01 … message-08` | 117 screenshot tiles, pre-sized and pre-ordered. One folder = one message. |
| `source/` | The three files being replaced: the current `<style>` block, `elder_feed.html`, `email-digest.html`. Attach these in message 1 — Claude Design cannot hand back a verbatim replacement for a file it has never seen. |
| `manifest.json` | Machine-readable index of file → label. |

The images are already sized so Claude never downscales them. **Do not merge folders and do not
exceed 20 images in a message** — past that the API applies a stricter per-image size limit.

## Run it

1. **Optional but worth 60 seconds:** open `00-KICKOFF-PROMPT.md`, find the *Founder note* in §2.0,
   and paste in two or three visual references you actually like. This is the single highest-leverage
   thing you can add — with it, the ten Phase-1 directions are aimed; without it they are a fair
   sample of the space.
2. Open Claude Design. Drag in **message-01** (18 images), pasting each label line from
   `UPLOAD-PLAN.md` immediately before its image, then the three files from `source/`, then
   paste the whole kickoff prompt last.
   Images first, instructions last — that ordering measurably improves how the images are used.
3. Send **message-02** through **message-08** as follow-ups, same labelling.
4. It will produce a **defect table** (the twelve message-01 surfaces) and then **10 flat direction
   concepts of the feed**, each on an assigned thesis so they genuinely differ. Do not let it build
   more than that. Pick **two**.
5. It returns **5 riffs**, each showing the feed, the sign-in screen and the members table.
   Pick **one**.
6. Only then does it build every surface and write the handoff bundle.
7. Export via **Hand off to Claude Code** and give me the bundle.

## What I do with the handoff

Apply `01-base-style.css` verbatim, run the two WCAG guards and the full gate, build the three
allauth layout overrides and the three error templates, redeploy, then **re-capture every surface at
the identical handles** and diff against the current set — so the improvement is measured, not
asserted. Security review runs on anything touching auth, tokens, media, email or roles.

## The tools, so this is repeatable

`docs/design/tools/` holds the harness that produced the package:

- `seed_demo.py` — deterministic demo data: two family sides, 17 members across every role, and posts
  that exercise every visual state (galleries at five aspect ratios, a pending and a failed video, an
  eight-reply thread, email-arrived replies, invites in every lifecycle state, digests in every
  delivery state, six weeks of metrics, two elder tokens). Writes a manifest of logins and tokens.
- `capture.py` — Playwright capture of every surface at 390×844 @2x and 1440×900, light and dark,
  plus 320px reflow, 200% text zoom and forced-colors. Asserts its own logins so a silent
  auth failure cannot masquerade as a clean run.
- `capture_supplement.py` — the flows a plain GET cannot reach (hand-over page, digest confirm and
  unsubscribe, break-glass).
- `package.py` — tiles the full-page masters and batches them under the upload limits.

Run against a local stack:

```bash
make up
make setup-secret                       # paste into /setup/ or let capture.py firstrun do it
python capture.py firstrun              # setup wizard + genuine day-one empty states
docker compose exec -T web sh -c 'export DJANGO_SECRET_KEY=$(cat /data/secret_key); \
  python manage.py shell' < seed_demo.py
python capture.py populated
python capture_supplement.py
python package.py
```

## What this pass found that was not a design problem

- **~30 django-allauth surfaces render the library's raw defaults** — no CSS at all, a literal
  `Menu:` bulleted list, and a live "Sign Up" link on an invite-only site. Sign-in is the first and
  most-repeated surface in the product. All thirty inherit from three templates
  (`allauth/layouts/{base,entrance,manage}.html`), so this is a three-file fix once the layouts are
  designed. Note `core` sits *after* `allauth` in `INSTALLED_APPS`, so overriding also needs either a
  reorder or a project-level `TEMPLATES['DIRS']` entry.
- **404, 500 and 403-CSRF are Django's unbranded defaults.** The 404 is a *normal* surface here
  because authorization denials are 404s by design.
- **`{% static %}` is not broken.** WhiteNoise + `collectstatic` are configured and library assets
  resolve; it only 500s for a project-owned file that does not exist, because the project ships no
  static directory yet. A self-hosted webfont and real icon files are therefore available — the
  previous brief wrongly ruled them out.
- **The CSP has no `font-src` directive at all**, so fonts fall back to `default-src 'self'`:
  same-origin fonts allowed, `data:` fonts blocked. Same for `img-src 'self'` and `data:` images.
- **SC 1.4.11 is failing today**: the composer textarea's border is 1.24:1 against its ground.
- **The digest email's faint grey is 3.25:1** on the two most load-bearing strings in the product —
  the reply separator the inbound parser depends on, and the anti-phishing notice. No CI guard reads
  any email template.
