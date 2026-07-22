# S-301 close: link-preview og:image re-hosting (rich card, never a hotlink)

Date: 2026-07-21. Story **S-301** (epic E3). Branch
`feat/s-301-preview-image-rehost` off `main`. This closes the last piece of the
link-preview card: the **image**. The card already showed title + description + a
tracking-stripped URL; the og:image was captured but never rendered, because
hotlinking a remote image is the TS-PP-6 tracking-beacon and IP-disclosure leak.
Wave 3's media pipeline now exists, so the image is RE-HOSTED: re-fetched
SSRF-safely, re-encoded through the media store, and served through the one
access-checked media path. Every claim below is run or measured, never asserted.

## What shipped

- **`link_preview.fetch_image_bytes`** re-fetches the og:image through the SAME
  SSRF-hardened path as the HTML: the fetch was refactored so `fetch_preview` (HTML)
  and `fetch_image_bytes` (image) both go through one `_fetch_following` /
  `_fetch_once` that runs the identical gate (http/https on 80/443, no userinfo,
  resolve-then-check every resolved address including IPv4-mapped/NAT64/6to4/SIIT
  embedded-internal forms, pin the connection to the validated IP, re-validate every
  redirect hop). Only the accepted content type and byte cap differ.
- **`media.ingest_link_preview_image`** re-encodes the fetched bytes through the
  photo `_decode`/`_reencode` (strips EXIF/GPS/XMP/COM, defuses SVG/HTML/polyglots to
  an inert raster, pins the content type to our own JPEG) and stores it as a new
  `MediaAsset.LINK_PREVIEW` kind on the post.
- Rendered via the existing **access-checked `serve_media`** (inherits the post's
  audience through `visible_media`; cross-yard is a byte-identical 404), cleaned up by
  `purge_post_media` on delete, and **excluded from every gallery/enumeration** — feed,
  post-detail, the member export, and the digest photo count — via a new
  `scoping.visible_attached_media` (the exclusion lives in the scoping layer, so
  `digest.py` stays TM-2-confined to reads through `core.scoping`).
- Migration `0020`; the card templates render only the re-hosted asset token, never
  the remote `image_url`.

## Full verification gate (never a subset)

`ruff check` + `ruff format --check` + `mypy` (**127 files**) + full `pytest`
(**480 passed, 0 skipped** — ffmpeg installed locally so the video/transcode tests ran
for real) + `docker build` (web + worker clean). Run against a Postgres 18 matching CI.

New tests: `fetch_image_bytes` SSRF (internal-literal block, redirect re-validation,
image-only content type), `ingest_link_preview_image` (re-encode, metadata strip,
reject-undecodable, oversize-dimension reject), the end-to-end re-host (asset kind +
served-with-access-check cross-yard 404 + gallery exclusion + delete purge), export
exclusion, digest-count exclusion, the shared fetch deadline, and the broadened
error guard.

## Security review (mandatory — SSRF + remote-image decode + media serving)

A `security-reviewer` pass traced the full diff, the refactored fetch path, the
redemption/serve path, both templates, and the models. **Verdict: no CRITICAL, no
HIGH.** SSRF parity after the refactor, mandatory re-encode (payload defusal),
access control (cross-yard 404), no-hotlink, and cleanup all confirmed solid. Its
findings, all folded before close:

- **MEDIUM-1 (fixed) — digest `photo_count` over-counted the re-hosted image**, so a
  link-only post would say "1 photo" then show none on click. Fixed via
  `scoping.visible_attached_media` + test.
- **MEDIUM-2 (fixed) — the member data export bundled the re-hosted third-party
  image** as if it were the member's own photo. Excluded from the export + test.
- **DoS bound (fixed) — the second synchronous fetch + an attacker-sized decode.** Now
  the page fetch and the image fetch share ONE `_TOTAL_BUDGET` wall-clock deadline
  (not two), and a preview image is held to a tighter decoded-pixel budget
  (`_LINK_PREVIEW_MAX_PIXELS`, rejected by header dimensions before the bitmap is
  allocated) so a small file cannot inflate to tens of megapixels in the web tier.
- **LOW (fixed) — the re-host could 500 an already-committed post** on an unexpected
  storage/DB error. The re-host now degrades to no-image on any failure + test.

Left on the record (not a blocker): moving the whole link-preview fetch to the worker
on its own network segment (TS-CO-4) remains the right longer-term home for the
SSRF-sensitive fetch; it applies equally to the already-shipped synchronous HTML
fetch and is tracked separately, not introduced by S-301.

## Live repro on the running compose stack (through Caddy)

`docker compose up --build` on fresh volumes, reached through Caddy. The SSRF guard
correctly rejects any private origin, so the target was a REAL public URL
(`https://github.com/AIJSAI/backyard`, whose page carries an og:image on
`opengraph.githubassets.com`) — a fully representative exercise of the fetch path.
Verified end to end:

| # | Step | Result |
|---|---|---|
| 0 | Public target really has an og:image | `<meta property="og:image" ...opengraph.githubassets.com...>` |
| 1 | `GET /healthz`; web → public internet | `200`; outbound `ok` |
| 2 | Bootstrap admin (setup wizard) | `302 → /` |
| 3 | Compose a post pasting the public URL | `302`; the card renders with a `preview-image` |
| 4 | The image is RE-HOSTED, not hotlinked | the remote image host `opengraph.githubassets.com` appears **0** times in the page |
| 5 | The re-hosted image serves through the access-checked endpoint | `GET /media/<token>/` → `200`, `Content-Type: image/jpeg`, `X-Content-Type-Options: nosniff`, body starts `ff d8` (a real re-encoded JPEG, 63,721 bytes) |
| 6 | Compose a post whose URL is `http://169.254.169.254/latest/meta-data/` | `302`; the card carries no image — the total `preview-image` count stays **1** (only the safe card), proving the SSRF gate blocks the internal target live |

The metadata URL still appears as the bare link the member typed (nothing was fetched
from it); no content was retrieved from the blocked address.

## Cleanup

The compose stack + volumes, the cloudflared tunnel, and the throwaway local origin
are torn down after this receipt. No ephemeral infra persists.

## Result

**S-301 → tested.** v1 now 33/34 tested; the one remaining built story is S-101
(feed-landing redirect + mobile e2e harness).
