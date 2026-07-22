# S-101 close: tap an invite link, stand in the pod feed (mobile, cross-browser)

Date: 2026-07-22. Story **S-101** (epic E1). Branch
`feat/s-101-feed-landing-mobile-e2e` off `main`. This is the LAST built story in the
v1 cut. It has two parts: (1) completing an invite signup lands the newcomer DIRECTLY
in their pod feed (not a bare hello-world root, never a create-a-community screen), and
(2) the flow is verified on iOS Safari and Android Chrome with a real cross-browser
mobile e2e. Every claim below is run, never asserted.

## What shipped

- **`core/join.py`**: after a successful invite signup the member is redirected to
  `feed` (was `home`); an already-signed-in re-visitor is likewise sent to `feed`.
  Nothing else in the invite-signup security path changed (atomic account+invite
  creation, the login rate limit, and the byte-identical 404 for an unusable invite
  are all untouched).
- **`core/views.home`**: a signed-in member visiting `/` is routed to their feed, so
  the root is never a dead-end hello-world for someone with an account; a logged-out
  visitor to a set-up instance still sees the public landing. `home.html` copy was
  corrected (it no longer claims "there is no feed yet") and now links to sign-in.
- **`core/tests/test_onboarding_mobile.py`** (NEW): the cross-browser mobile e2e. There
  are no physical devices in CI, so it drives the real join -> feed flow in the two
  browser ENGINES those products use — WebKit for iOS Safari, Chromium for Android
  Chrome — under mobile device emulation (iPhone 13 / Pixel 5: viewport, touch, mobile
  UA), against a live server. It is a real browser rendering and submitting the real
  form, not a request-client simulation.
- The e2e is excluded from the default unit run (`addopts = -m 'not e2e'`, needs
  browsers) and runs in its own CI job (`e2e`) that installs WebKit + Chromium and runs
  `pytest -m e2e`, so the cross-browser gate is durable and non-vacuous.

## Full verification gate (never a subset)

`ruff check` + `ruff format --check` + `mypy` (**128 files**) + full `pytest`
(**482 passed, 2 e2e deselected** in the default browser-free run) + the **e2e run**
(**2 passed**: `test_onboarding_on_ios_safari` [WebKit/iPhone 13],
`test_onboarding_on_android_chrome` [Chromium/Pixel 5]) + `docker build` (web + worker
clean). New unit assertions pin the feed-landing (join redirects to `feed`, follows
through to the feed page with no community screen; `home` routes a member to their feed
but shows the landing to a logged-out visitor).

## Security review (auth-flow-adjacent)

A `security-reviewer` pass (the signup flow is auth) traced both changed views, the feed
re-scoping, the URL map, the new e2e, the template, and both CI jobs. **Verdict: clean,
no findings at any severity.** Confirmed: no open redirect (every changed redirect is a
fixed named URL, `redirect("feed")`, nothing reads a user-supplied `next`); the `home`
member-check is a parameterized existence gate on the session user's own pk and the feed
independently re-derives the actor via `_acting_member`, so no cross-member routing; the
TS-DJ-5 invite properties (atomic account+invite create, login rate limit, byte-identical
404) are untouched; `DJANGO_ALLOW_ASYNC_UNSAFE=1` is set only in a test module and can
never reach the gunicorn/WSGI runtime; and the new CI `e2e` job uses the same throwaway
CI credentials and pinned actions as the existing jobs. It also noted a fail-closed
improvement: an authenticated non-member re-hitting `/join/<token>/` now gets
`feed → 404` (more restrictive than the old `home` 200), consuming no invite and
disclosing no invite-validity.

## Live repro on the running compose stack (through Caddy)

`docker compose up --build` on fresh volumes (`healthz` 200). An admin bootstraps (setup
wizard) and mints a household invite through the delegated-onboarding surface (S-201).
Then a fresh person redeems it, on the production-posture stack, through Caddy:

| # | Step | Result |
|---|---|---|
| 1 | Admin mints a household invite | `create household → 200`, 43-char token |
| 2 | `GET /join/<token>/` | `200`, the simple join form, **no create-a-community screen** |
| 3 | `POST /join/<token>/` (name + username + password) | `302 → http://127.0.0.1:8000/feed/` — **lands directly in the feed** |
| 4 | `GET /feed/` as the brand-new member | `200`, the composer renders (**standing in the pod feed**), the page renders through production static via Caddy with no template 500 |

**Cross-browser mobile verification (S-101 acceptance #4)** is the committed e2e, run
against a live server in the two real browser engines: **2 passed** —
`test_onboarding_on_ios_safari` (WebKit / iPhone 13) and
`test_onboarding_on_android_chrome` (Chromium / Pixel 5), each tapping the invite link,
filling the real form, landing in the feed, and seeing a pod-mate's post. (Django's CSRF
correctly rejects a browser whose `Origin` does not match the instance's configured base
URL; the app is served over HTTPS in production, where secure cookies and origin match by
design. The compose stack here is plain HTTP on a loopback, so the browser form path is
covered by the live-server e2e above rather than driven against the loopback, while the
redeem→feed flow on the compose stack is proven via the request path.)

## Cleanup

The compose stack + volumes and the throwaway test Postgres are torn down after this
receipt. Playwright browsers are a dev/CI dependency, not shipped in the app image.

## Result

**S-101 → tested.** With this, **Phase 2 is 34/34 v1 stories tested — 100%**, every
wave proven live with a committed receipt.
