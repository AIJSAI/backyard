# Design pass v2 — how to run it

The v1 pass was rejected ("not sophisticated, not production enterprise grade"). This is the retry,
built from live-sourced research on how Claude Design actually responds, plus a full capture of every
user-facing surface in the product.

## How to run it

Claude Design already has the repository, so this is **one paste and nothing else**.

1. Open `~/Downloads/backyard-design-package/PASTE-THIS.md` (same file as
   `docs/design/claude-design-kickoff-v2.md`). Optional, two minutes, high leverage: find the
   *Founder note* in §2.0 and drop in two or three visual references you actually like — ideally
   not software.
2. Select all, copy, paste into Claude Design. Send. No attachments.
3. It returns a defect table for twelve surfaces, then **10 direction concepts of the feed**, each on
   an assigned thesis so they cannot collapse into one look. Pick **two**.
4. It returns **5 riffs**, each showing the feed, sign-in and the members table. Pick **one**.
5. Only then does it build every surface and write the handoff bundle.
6. Export via **Hand off to Claude Code** and give me the bundle.

`optional-screenshot-route/` holds the 117-tile screenshot package and its per-message paste blocks.
It is a fallback only — use it if Claude Design turns out not to read the repo well, or if you want
it to see the current rendering rather than infer it from the templates.

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
