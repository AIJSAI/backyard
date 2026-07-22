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

## Files

`src/core/tasks.py` (the task), `src/core/feed_views.py` (defer + import + comment fixes),
`src/core/tests/test_tasks.py` (3 tests).
