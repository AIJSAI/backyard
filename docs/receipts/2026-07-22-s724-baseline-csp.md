# S-724 baseline Content-Security-Policy — close receipt

Date: 2026-07-22. Phase 3, step 3 (batched hardening). Adds the second net over Django's
autoescape that TS-DJ-9 called for: a member-authored string can never inject an executing
script even if autoescape were somehow bypassed.

## What shipped

- **`core.middleware.ContentSecurityPolicyMiddleware`** — stamps a baseline CSP on every
  response with a fresh per-request nonce. The policy: `default-src 'self'`,
  **`script-src 'self' 'nonce-…'` (NOT `'unsafe-inline'`)**, `style-src 'self'
  'unsafe-inline'`, `img-src 'self'`, `object-src 'none'`, `base-uri 'self'`,
  `form-action 'self'`, `frame-ancestors 'none'` (the CSP twin of X-Frame-Options DENY),
  `connect-src`/`worker-src`/`manifest-src 'self'`. The nonce is set on the request before
  the view renders and stamped into the header on the way out, so the two always match.
- **The nonce control is the point:** `script-src` is nonce-based, so an injected inline
  `<script>` without this response's nonce does not execute. `style-src` keeps
  `'unsafe-inline'` because the templates carry inline `style=` attributes and `<style>`
  blocks a nonce cannot cover, and the XSS lever is script execution, not CSS. Every
  subresource is same-origin — the CSP-surface inventory found **zero external resources**
  (no CDN) — so the rest is a tight `'self'`.
- **The three inline scripts carry the nonce** (`nonce="{{ request.csp_nonce }}"`): the
  service-worker registration (base.html), the client-side photo resize (feed.html), and
  the hand-over copy/share enhancement (_handover_artifacts.html). Added the `request`
  context processor so templates can read the nonce.

## Verification

- ruff + mypy(strict, 135 files) clean; **532 unit** (+4 `test_csp.py`) + **8 e2e** (+2)
  green.
- Unit (`test_csp.py`): the header is a tight nonce-based baseline, `script-src` is NOT
  `'unsafe-inline'`, the header nonce matches the rendered `<script>` tags, **no bare
  nonce-less inline script slips through**, a fresh nonce per request, and the policy is
  present even on an anonymous 404.
- **Browser e2e (both engines):** `test_csp_allows_inline_scripts_on_{ios_safari,android_chrome}`
  loads the feed under the ENFORCED policy and asserts the browser records **no CSP
  violation** in the console — the only way to prove the browser actually executes the
  nonce'd inline scripts (a unit test can prove the nonce is present, not that it works).
- **Live-repro (running compose stack):** the CSP header is present and correct through the
  real Caddy edge (Caddy passes it through unchanged; it sets no CSP of its own).

## Files

`src/core/middleware.py` (the middleware), `src/config/settings.py` (MIDDLEWARE + `request`
context processor), `src/core/templates/core/{base,feed,_handover_artifacts}.html` (nonces),
`src/core/tests/test_csp.py` (new), `src/core/tests/test_onboarding_mobile.py` (CSP e2e).
