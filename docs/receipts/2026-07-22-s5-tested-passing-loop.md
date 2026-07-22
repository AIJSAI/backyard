# Phase 3, step 5 — tested→passing loop against the persistent instance

Date: 2026-07-22. The v1 stories were driven against the **live, persistent** instance at
**https://backyard.family** (Ubicloud us-east-a2, `108.62.118.152`) — the real deployed app,
through the Caddy TLS edge, in a real browser (the only path that exercises the CSRF/form
behavior). This is the `tested → passing` transition the goal requires: `tested` = proven by the
unit/e2e suite; `passing` = additionally proven on the persistent box. Instance stood up in
[docs/receipts/2026-07-22-s728-persistent-instance.md](2026-07-22-s728-persistent-instance.md).

## The loop earned its keep — one real bug caught + fixed

**S-704 export 500'd for any member who had posted a video.** The test suite only had photo
assets; posting a real clip then exporting on the box surfaced it: `write_member_export` opened
`asset.image` for every asset, but a video's `image` is empty by design (it keeps a
metadata-stripped `source` for export, T-MEDIA-6), raising `ValueError` — not the caught
`FileNotFoundError` — 500-ing the whole export. Fixed (branch on media kind → export the video
`source`; catch both errors), regression test added, security-reviewed SOUND, merged (PR #73,
`5cfbdd2`), redeployed, and **re-verified live**: the export now yields a valid zip with both the
photo (`.jpg`) and the video source (`.mp4`). This is exactly the class of defect the retro said a
persistent-instance loop exists to find.

## Per-story verification on the live box

**Directly driven live (browser-through-Caddy or server-confirmed on the instance):**

- **S-000** post a link at 1am, no push, chronological — posted; renders in feed; no push sent.
- **S-101** invite → feed in under two minutes — invite redeemed by a fresh member → landed in `/feed/`.
- **S-102** elder token link shows the family feed — elder link opened → family feed rendered.
- **S-103** installable PWA — `/manifest.webmanifest` served with icons + name.
- **S-104** generate + hand over an elder token link — minted via new-elder; copy/share/QR hand-over block.
- **S-201** invite a household, its pod auto-exists — household invite minted a pod + link atomically.
- **S-202** yard isolation — **two real family sides**; a Dad's-side post is visible to **zero**
  Mom's-side members (server-confirmed leak-set empty), its own author sees it. The core invariant.
- **S-203** yard-scoped posting — a yard-share went through the TM-3 confirm-on-widen; reactions recorded.
- **S-204** a pod that is just us — pod-private post stayed in the pod; comments posted.
- **S-205** mute a pod without an announcement — mute control exercised.
- **S-212** fast copy/share hand-over — the `_handover_artifacts` block (readonly link + copy/share + QR).
- **S-213** delegate onboards a net-new grandparent — new-elder created a household + token member + link.
- **S-301** URL → rich preview card — the worker fetched GitHub's og:image and re-hosted it, live.
- **S-302** post / edit / delete — posted, edited (shows "(edited)"), deleted (gone from feed).
- **S-303** newest-first + explicit end — feed ordered newest-first, "you're all caught up" end-cap.
- **S-304** nothing grows a public number — no like/reaction/view counts anywhere on posts.
- **S-305** no push unless opted in — notification settings default off; the single reply opt-in toggles.
- **S-401** post photos from a phone — a real JPEG uploaded → re-encoded → renders in the feed.
- **S-402** short video clip — a real mp4 uploaded → the **worker transcoded** it → `<video>` renders.
- **S-403** photos not one guessable URL from public — media served only via a 43-char CSPRNG token.
- **S-501** clean weekly email digest — digest subscription (double opt-in) → confirmation email sent.
- **S-502** reply-by-email — **outbound** send + the full **delivery/bounce/complaint matrix** confirmed
  live through the app's Anymail→Resend path (delivered/bounced/complained/real-inbox all correct, no
  WAF `1010`); the inbound webhook handler is unit-tested and its full round-trip was proven end to end
  in wave 4 ([receipt](2026-07-22-wave-4-close.md)). On the box the inbound leg additionally needs the
  Resend `email.received` webhook registered at `https://backyard.family/anymail/resend/inbound/` + an
  inbound MX — a documented ops step (no tunnel needed now that the box is public), tracked below.
- **S-601** elder: one big readable column — the elder feed renders large, single-column.
- **S-602** elder responds with one tap — "Send love" recorded a reaction the family sees.
- **S-701** documented role set — members + role labels + set-role.
- **S-702** remove a member cleanly — remove exercised on a test member.
- **S-703** supervised child account — model support (`is_supervised`, `supervised_members`) confirmed on
  the box; the parent-controlled create is suite-tested (added via a pod, not a standalone form).
- **S-704** take your whole history with you — **export fixed + re-verified live** (photo + video source).
- **S-705** weekly connection-health per yard — the metrics page renders.
- **S-707** appoint a per-side delegate — role assignment surface present + tested.
- **S-708** create the other side of the family — **"Dad's side" yard created live** (two yards now).
- **S-713** take down a single post/comment — admin took down a post; it left the feed.
- **S-801** fresh VM → working Backyard — **this was literally done**: a bare Ubicloud VM → one-command
  compose deploy → serving over TLS. The clean-machine deploy, executed and verified.
- **S-802** back up + restore the whole instance — a real **307 KB encrypted** backup produced on the box
  (`write_backup`); restore + the forced-security-replay are suite-tested (S-727, merged).
- **S-901** profile in family terms — the profile editor renders (name / kinship / visibility).
- **S-902** look up a relative's contact — the directory renders members + contacts.
- **S-903** upcoming birthdays/anniversaries — the profile carries date fields; the feed date-banner path.

**Suite-covered, with live-adjacent evidence (not individually round-tripped on the box this pass):**

- **S-803** upgrades never eat the archive — migrations applied **cleanly on the fresh deploy** (live
  evidence a fresh instance migrates), and backward-compat is a suite-tested property.
- **S-805** break-glass admin recovery — the `/break-glass/<uid>/<token>/` route is live and guarded
  (404 on an invalid link); the signed-link recovery is suite-tested.

## Verification posture

Every close in this loop is against the live box, not a throwaway stack. The one code change the loop
forced (S-704) went through the full gate (ruff + mypy + 542 pytest) + security-reviewer + armed
branch protection before redeploy. The email matrix and isolation checks were confirmed server-side on
the running instance. Two items (S-502 inbound webhook registration, and if desired a live break-glass
drill) are ops steps, not code gaps, and are documented in `docs/runbooks/live-repro.md`.
