# S-713 single-item takedown — close receipt

Date: 2026-07-22. Phase 3, slice 2 (flows-first, sequence step 2). The content-level
moderation lever the retro reconciled and James ratified: a per-side delegate can take
down one bad post or comment without the nuclear person-level `remove_member`. Scoped to
what the moderator can see; reversible member-suspend and member-visible notice deferred.

## What shipped

- **`core/moderation.py`** — `take_down_post` / `take_down_comment`: set `deleted_at` (the
  same soft delete the author path uses, so the ONE audience query treats the item as gone
  in the feed and the digest) and record `moderated_by`. Idempotent — an already-removed
  item is left as-is, so a takedown never revives a tombstone or overwrites the record of
  who first removed it (an author self-delete stays `moderated_by = null`, distinguishable).
- **`feed_views.take_down_post` / `take_down_comment`** — POST-only, admins only. The item
  resolves through the MODERATOR's read guard (`scoping.require_visible_post` /
  `require_visible_comment`), so a post/comment they cannot see is a byte-identical 404 —
  **structurally** bounded to what they may already see (the reach-vs-visibility rule).
  Post takedown also hard-purges the post's photos (`media.purge_post_media`, T-MEDIA-6).
- **Model** — one nullable `moderated_by` FK (SET_NULL) on `Post` and `Comment` (migration
  `0021`), the accountability trail a moderation lever needs before real families, without
  building the audit/restore surface (deferred, like suspend and the member-visible notice).
- **UI** — a "Take down" affordance on the feed and the thread (post + each comment), shown
  only to admins (`is_moderator` in context). Distinct from the author-only self-delete.
- **Story** — S-713 added to `stories/stories.yaml` (E7), `status: tested`.

## Design decisions (ratified-scope-faithful)

- **Content visibility is membership-scoped for EVERY role, including the instance admin.**
  The founder's instance-wide power is over members/config (`administrable_members`), NOT
  content omniscience: `visible_posts` is keyed on pod/yard membership, so even the founder
  cannot take down a yard's content they do not belong to. Each side's delegate moderates
  their side; this is coherent with the seed-ally model and the "scoped to visible" ruling.
- **Reuse the existing `deleted_at` soft delete + media purge** (the author path's exact
  mechanism), triggered by a moderator rather than author-gated — no second removal path to
  drift. **Silent** (no member-visible notice — ratified). Person-level lever stays
  remove-only (reversible suspend deferred).

## Verification gate (all green)

- `ruff check` + `ruff format --check`: clean. `mypy src` (strict): 133 files, no issues.
- `pytest` (unit): **523 passed** (+9 `test_moderation.py`), 6 deselected. `pytest -m e2e`:
  **6 passed** (WebKit + Chromium, unchanged). `check_stories.py`: PASS.
- The load-bearing test is `test_takedown_of_a_post_the_admin_cannot_see_404s` (+ the
  instance-admin twin): a maternal admin takes down a paternal post → 404, untouched. Plus
  non-admin 403, POST-only, idempotency + author-self-delete-record-preserved, feed/thread
  affordance admin-only.

## Live-repro (running compose stack, through Caddy)

Seeded a yard admin who can see a maternal post but not a paternal one, then drove the real
CSRF-authenticated takedown HTTP path through Caddy:

- Takedown of the **visible** maternal post → **302** → `/feed/`; DB shows `deleted_at` set
  and `moderated_by = ModRepro` (the admin); the post is **gone from the admin's feed**.
- Takedown of the **cross-yard** paternal post the admin cannot see → **404**, and the post
  is **untouched** (`deleted_at` null). The reach-vs-visibility rule holds on the real edge.

## Review panel (no CRITICAL, no HIGH) + folded findings

- **security-reviewer**: guard reuse, oracle ordering, CSRF/POST-only, idempotency/tombstone,
  media-purge TOCTOU safety, and silence all confirmed sound. One MEDIUM: the lever is
  bounded by *visibility* (membership), faithful to the ratified "scoped to visible," but
  it diverges from the person-lever's T-AUTH-G2 *subset* scope for the both-side/bridge
  case (a member in both yards via a bridge household, or a single-side admin removing a
  both-side post — one object in both feeds). **Resolution: keep the ratified visibility
  rule** (a stricter audience-subset rule would go beyond what was ratified and block a
  single-side admin from moderating a both-side post in their own feed) and **document the
  divergence** in the story hardening + the threat model, flagged for the founder's manual
  QA. Two LOWs noted and deferred as conscious v1 choices: a takedown drops the author's
  own removed post from their S-704 export (their data withheld from themselves — a
  data-portability judgment for a later export refinement); no per-endpoint rate limit
  (parity with the sibling delete endpoints; admin-gated, ~60-person instance).
- **code-reviewer**: APPROVE. Two MEDIUM folded — **service-level defense-in-depth authz**
  (`moderation.take_down_*` now re-checks is_admin + visibility independently of the view
  guard, matching `posting.delete_post` / `commenting.create_comment`), and a **direct
  service test** for idempotency + the defense-in-depth refusals (the HTTP path can never
  reach the service's idempotency branch because the guard 404s a deleted item first).
  LOW coverage gaps folded: a comment reach-vs-visibility 404 test and a media-purge test.

## Files

Logic: `core/moderation.py` (new), `core/feed_views.py` (take_down_post/comment + is_moderator
context), `core/models.py` (moderated_by on Post + Comment), `core/migrations/0021_*`,
`config/urls.py`. Templates: `feed.html`, `post_detail.html`. Tests: `test_moderation.py`
(new). Stories: `stories/stories.yaml`.
