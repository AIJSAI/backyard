# Wave A: a no-login grandparent can finally see a photograph

Date: 2026-07-26. Branch `feat/wave-a-elder-media`. Closes the **headline blocker** of
[the honest 100% audit](../audits/2026-07-26-honest-100-audit.md): *"a no-login
grandparent cannot see a photograph ANYWHERE — elder page, digest email, digest web."*
Every claim below is measured against a running instance, never asserted.

## What was actually broken

`serve_media` — the one access-checked path every media byte is served through — carried
`@login_required`. Two credential classes that could **already read the owning posts**
therefore could not fetch a single byte off them:

- a **token-only elder**, who has `user_id = NULL` *by design* (TM-10 forbids her an
  account), and
- a **digest token**, whose whole purpose is a page with no session.

So the elder feed rendered "Camp dump, finally" with the five camp photos and the three
replies invisible, and the emailed digest's deep link opened a page whose images were
equally unreachable. She got captions. This is the PR-FAQ's entire elder case, and 39/39
stories were `passing` over the top of it.

## The change

`src/core/viewers.py` (new) resolves a `Reader` from **any** read credential — member
session, elder session, digest token. It **widens authentication, never authorization**:
every viewer still resolves through the one audience query (`scoping.visible_media` over
`visible_posts`). The elder feed and both digest web surfaces now render photos, video
posters and replies.

`Reader` also carries the **capability ceiling**, so it travels with the credential
instead of waiting on each caller to remember it (see the first finding below).

## Two real defects found while building this, both caught before merge

**1. The digest token escaped its capability ceiling on the media path.** `digest_views`
has always enforced that a digest token reaches only its own issue's slice — it must
never widen into a general read credential for that member's other yards and other
weeks. The first cut of the media path ran only `scoping.visible_media(member)`, which is
strictly wider than the page the token was minted to render. **Proven, not argued** — the
guard was mutation-tested by deleting the narrowing:

```
assert Client().get(f"{url}?d={raw}").status_code == 404
E       assert 200 == 404
E        +  where 200 = <FileResponse status_code=200, "image/jpeg">.status_code
```

A digest token reached a photo on a post **40 days outside its own window**. Fixed by
`Reader.visible_media()`, and pinned by
`test_a_digest_token_cannot_fetch_media_outside_its_own_issue`.

**2. TS-EDGE-LOG had a second, unfiltered sink: gunicorn.** The redaction filter was
attached to `django.request` and `django.security`, which log a 4xx's `request.path`.
But on any unhandled exception **gunicorn logs the raw request line** —

```
BASE: self.log.exception("Error handling request %s", req.uri)
GLOGGING: self.error_log.propagate = False
```

`req.uri` includes the query string, and `propagate = False` plus its own handler meant
neither the two Django loggers nor the root logger ever saw those records. One 500 on a
capability URL wrote a live token to the container log. This gap **pre-dates Wave A** for
path tokens (`/d/`, `/join/`, `/media/`); Wave A's `?d=` would have added a new shape to
it. `settings.LOGGING` now names `gunicorn.error` at INFO (so worker lifecycle lines
survive), and `_TOKEN_QUERY` redacts query-string credentials. Verified live in the
container:

```
$ logging.getLogger("gunicorn.error").error("Error handling request %s", "/media/MEDIATOK/?d=LIVEDIGESTSECRET")
Error handling request /media/[redacted]?d=[redacted]
```

Mutation-proven non-vacuous: removing the `gunicorn.error` entry fails
`test_settings_wire_the_redaction_filter` **and** `test_the_live_gunicorn_error_logger_redacts`.

**3. A CSS edit severed the measure rule.** Folding `img.digest-photo` into the selector
list at `base.html` cost every `main.wrap > p`, `.notice` and `.post > p` in the app its
`max-width: 34rem` and gave them a sunken background — a full-app regression on top of
the v3.1 design pass. Its own rule now, with a comment saying why.

## Live repro (running compose instance, over HTTP, no login)

```
=== 1. ELDER: exchange token for a session, then load her page ===
  /t/<token>/ -> 302
  /e/ -> 200
    <img class="photo" src="/media/<43-char media token, redacted>/"
    said: She caught the biggest fish.
=== 2. ELDER fetches the actual photo bytes ===
    HTTP/1.1 200 OK
    Cache-Control: private, no-store
    Content-Type: image/jpeg
    Referrer-Policy: no-referrer
    bytes: 2528  file: JPEG image data, 400x300, components 3
=== 3. ANONYMOUS (no cookie, no token) on the same photo ===
    -> 404
=== 4. DIGEST web page, no login at all ===
    /d/<token>/ -> 200
    <img class="digest-photo" src="/media/DJoG.../?d=c7_tyBn...">
=== 5. DIGEST reader fetches the photo, cookieless, via ?d= ===
    -> 200  bytes=2528   JPEG image data, 400x300
=== live ceiling: a post OUTSIDE this token's issue window ===
  digest token on an out-of-window photo -> 404 (must be 404)
  digest token on its OWN issue's photo  -> 200 (must be 200)
=== log redaction ===
  clean: the raw token appears nowhere in the web logs
```

## Security review (mandatory — this diff touches media, tokens and auth)

A four-lens adversarial pass (authorization · token leakage · Django correctness ·
templates/test-quality), each finding then handed to an independent agent instructed to
**refute** it: **33 raised, 11 survived refutation, 22 dismissed.** The dismissals include
several confident-sounding ones the refuters killed with primary evidence — e.g. "the
module-level `_GALLERY` Prefetch is a process-wide singleton Django mutates in place"
(traced through the installed Django 5.2.16 and shown unreachable) and "`serve_media`
pins no HTTP method" (CSRF middleware already rejects unsafe verbs). All 11 survivors are
fixed here:

| # | Sev | Finding | Fix |
|---|-----|---------|-----|
| 1 | HIGH | The **pushed tip carried no ceiling** — the fix existed only in the working tree | Committed, plus an AST drift-guard: `media_views` may not import `scoping` at all, so every audience decision goes through `Reader` |
| 2 | HIGH | `/media/` became a token-in-URL surface but was absent from `_TOKEN_URL_PREFIXES`; the view sets hygiene headers only on the 200 path, so **both 404s and the append-slash 301 (whose `Location` echoes the token) escaped** | `/media/` added to the prefixes; `@require_safe` added |
| 3 | HIGH | Elder photos served eagerly, full-size, on the lowest-bandwidth surface | `loading="lazy"`, matching the digest templates |
| 4 | HIGH | **Nothing tested that any surface actually renders a photo** — the headline fix was unverified end-to-end | Render assertions on all three surfaces + a cross-yard negative arm |
| 5 | HIGH | Every photo rendered `alt=""` — screen readers told the family photos are decorative | Byline fallback alt on all six photo tags (incl. the two pre-existing member-app templates) |
| 6 | MED | The elder WCAG fixture had **no media and no comments**, so the S-601 guard had never seen the markup the template's own comment claims it pins | Fixture now carries a photo, a done video, a pending video and a reply — plus a non-vacuity test asserting it does |
| 7 | MED | (same as 3, second lens) | — |
| 8 | MED | Elder replies dropped the **`via_email` badge the threat model requires** (T-TOKEN-8) and were unbounded | Badge carried; replies capped at 5 with a plain-text "and N more" (no link — S-601) |
| 9 | LOW | (same as 3, third lens) | — |
| 10 | LOW | Comments uncapped on all 50 posts | Same cap as 8 |
| 11 | LOW | A still-transcoding or failed video rendered as **nothing at all** | Elder-worded three-state block, matching the feed |

## Accessibility re-sweep (the surfaces this wave changed)

axe-core WCAG 2 A/AA + 2.1 + 2.2 AA, three surfaces × mobile/desktop × light/dark =
**12 renders, 0 violations at any severity**
([receipt](2026-07-26-axe-wave-a-elder-media.json)). The sweep records `media_imgs` per
render — **12/12 contained a real `/media/` photo**, so it is not a sweep of empty pages.

## Full verification gate

`ruff check` + `ruff format --check` (140 files) + `mypy` (**140 files, no issues**) +
full `pytest` (**580 passed**, 8 deselected) + `manage.py check --deploy --fail-level
WARNING` against a production-like posture (**0 issues**). Never a subset.

## Deliberately NOT done, and why

- **Photos are not embedded in the digest EMAIL itself.** The email shows a photo count
  and links to the page. Embedding capability-token image URLs would hand a live token to
  every mail client's image proxy (Gmail's fetches and caches remote images), which is a
  privacy trade on children's photographs that belongs to the founder, not to me. The
  no-login path is closed regardless: the email's link opens the digest page, and the
  photos are there.
- **The elder's photos are not clickable.** `test_elder_wcag` pins every `href` on that
  page to the elder feed itself (S-601, no dead ends), so a full-size link would red the
  build. She sees the picture; tapping it does nothing. That is the correct trade until
  the no-off-surface-links rule is revisited — **and it is a founder decision**, because
  the same rule is why the original 1am-YouTube-link use case still does not reach the
  oldest generation.
