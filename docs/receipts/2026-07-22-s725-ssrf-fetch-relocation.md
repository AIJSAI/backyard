# S-725 SSRF link-fetch relocation — close receipt

Date: 2026-07-22. Phase 3, step 3 (final item). Closes the TS-CO-4 relocation and the stale
comment the retro flagged as "worse than silence."

## The problem

The link-preview fetch — the one SSRF-sensitive outbound network call in the app — ran
**synchronously in the web process** (`feed_views.compose`), and the in-code comment claimed
it "moves to the worker in wave 3, where the SSRF-sensitive fetch belongs on its own network
segment (TS-CO-4)." It never moved. So the comment told a future reviewer the egress was
somewhere it was not, and the edge-facing web process (on the `edge` network with the reverse
proxy) was the one making the fetch.

## What shipped

- **`tasks.attach_link_preview(post_id)`** — a Procrastinate worker task (queue `preview`,
  non-periodic) that re-resolves the post live (TS-DJ-11; a deleted post no-ops) and delegates
  to the unchanged, already-SSRF-hardened `link_preview.attach_to_post`.
- **`feed_views.compose` now defers it** (`attach_link_preview.defer(post_id=post.id)`) instead
  of calling it inline — the SSRF fetch runs on the **worker**, which is on `worker-db` only
  (neither `edge` nor `web-db`), so a hypothetical bug in the fetcher can't pivot toward the
  reverse proxy. The card appears once the worker attaches it (like a video transcode); the
  post shows the bare link until then. The now-unused `link_preview` import is dropped, and the
  stale comment + the `compose` `non_atomic` docstring (which cited the now-moved fetch) are
  corrected.
- The application-layer SSRF defense (IP-pinning, non-global rejection incl. NAT64, per-hop
  revalidation) is unchanged and remains the primary control; this is the network-segment
  defense-in-depth on top.

## Verification

- ruff + mypy(strict, 135 files) clean; **538 unit** (+3 `test_tasks.py`) + 8 e2e + stories green.
- Unit: the task is registered and non-periodic; it re-resolves the post and delegates to
  `attach_to_post`; a post deleted before the worker runs is a no-op.
- **Live drill (running compose stack):** composed a post whose body links a real external page
  (`github.com/AIJSAI/backyard`) and deferred the task; the **worker** fetched it and attached
  the card — `title='GitHub - AIJSAI/backyard…'`, `has_image=True` (og:image re-hosted through
  the media pipeline). This proves the fetch runs on the worker, the worker has the outbound
  egress TS-CO-4 relies on, and the S-301 re-host path works from the worker end to end.

## Review panel (security-reviewer, no CRITICAL/HIGH)

Verdict: sound relocation, SSRF posture preserved (the deferred path delegates to the
UNCHANGED fetcher, so every guard — validate/resolve-once/pin-IP/NAT64/per-hop — still
runs), network segmentation a genuine net improvement, task boundary (id-only, live
re-resolve, deleted→no-op) correct, async timing benign (the template gates rendering on
the row existing, which only appears after validation), `non_atomic` retention correct.

One MEDIUM, folded: `attach_to_post` did an unguarded `create` on `LinkPreview.post`'s
OneToOne. Fine in the old synchronous path, but on the at-least-once worker queue a
re-delivered job (worker killed mid-run) would re-run the outbound fetch and then raise an
uncaught `IntegrityError` (fails closed — no duplicate — but an unhandled-exception/failed-job
regression and a latent poison-loop if a retry strategy is ever added; the sibling transcode
task is idempotent by design). Fixed with an idempotency guard BEFORE the fetch (a post that
already has a card is done) + a duplicate-delivery test.

Two LOWs accepted as residuals (not regressions): (1) the fuller TS-CO-4 posture would mark
`worker-db` `internal: true` and give the worker a dedicated egress-only network — the
relocation delivers the primary goal (egress off `edge`); the segmentation half is a future
compose refinement. (2) A compose with no link enqueues a cheap no-op task (the task returns
early with no fetch); gating the `defer` on a URL would re-couple the view to the fetcher, so
it is left; and the concurrency-1 worker serialization of real link fetches is inherent and
low at family scale.

## Files

`src/core/link_preview.py` (idempotency guard), `src/core/tasks.py` (the task),
`src/core/feed_views.py` (defer + import + comment fixes),
`src/core/tests/test_tasks.py` (4 tests).
