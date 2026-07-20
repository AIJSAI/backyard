# OSS Landscape 2026: Private Family / Small-Community Social Networks
(GitHub API sweep, fetched live 2026-07-19/20 UTC — raw agent report, verbatim)

**Method:** ~15 GitHub search queries via GitHub MCP (phrase, topic, and direct-repo lookups), README pulls on the 8 closest candidates, commit checks where search indexing failed. Anything not API-verified is tagged [UNVERIFIED].

## Headline

**There is no active, polished, family-focused OSS social network.** The phrase "family social network" matches only 25 repos on all of GitHub; the best-starred genuine one has **222 stars** (zusam) and the most feature-complete one has **2 stars** (cousins-matter). The GitHub topic `private-social-network` contains **zero repositories**. Meanwhile the *adjacent* shelves are crowded: photo infrastructure is a solved, world-class problem (Immich 108k★), and 2026 has produced a flood of self-hosted family *organizers* (calendar/chores/meals) — but nobody is executing well on the async family *feed* job.

## Repo table

### Tier 1 — Family/friends network attempts (the actual category)

| Repo | Stars | Last push | Status | What it is | Relevance |
|---|---|---|---|---|---|
| zusam/zusam | 222 | 2026-07-14 | ACTIVE | PHP/Symfony + Preact SPA; private **groups** to share messages, photos, videos, **links**; link previews, albums, AGPL-3.0, SQLite, Docker, public demo (demo.zusam.org), mobile-responsive | **Closest match.** Groups ≈ pods; link-sharing first-class. But: web-only, pre-1.0 for years, one maintainer |
| leolivier/cousins-matter | 2 | 2026-07-19 | ACTIVE | Django, MIT, Docker. "A family social network": member mgmt + invitations, **managed profiles for elders/kids**, galleries, forums, chat, polls, events, classifieds, theming, 6 languages, demo, readthedocs, v2 | Most feature-complete family network in OSS — and nobody knows it exists. 1 maintainer, 0 forks. "Features ≠ traction" case study |
| Pure-Karma-Labs/Orbital-Mobile | 0 | 2026-07-19 | ACTIVE (created 2026-03) | "Private family social network for iOS & Android" — E2EE threaded **family discussion board** (anti-group-chat pitch), Signal protocol, React Native, 4K video ≤500MB, AGPL | Someone else sees the same gap in 2026, same framing. Backend repo NOT public — not fully OSS today |
| dfmcphee/simplifeed | 50 | 2014-12 | ABANDONED | "Private social network for close friends and family" (Node/Geddy) | Graveyard exhibit A — same pitch, died 2014 |
| knotworks/knot-server | 23 | 2026-03 | ACTIVE-ish | Decentralized private-social server (PHP) | 9 years, near-zero traction |
| paullouisageneau/Teapotnet | 81 | 2022-02 | ARCHIVED | Distributed private social network (C++) | Graveyard |
| RocketChat/Rocket.Chat.RaspberryPi | 353 | 2023-03 | ARCHIVED | "Private social network on your Pi" | Even corporate-adjacent attempts shelved |
| npfoss/gravity-protocol | 16 | 2023-06 | ABANDONED | Decentralized private social protocol | Protocol-first overreach |
| ~20 zero-star "family social network" repos (la-famiglia, Family-connect-, jencogram, familygram, Lentik…) | 0–1 | 2015–2026 | mostly dead | Hobby/student PWAs, several 2026 vibe-coded | Everyone starts this app; nobody finishes it |

### Tier 2 — Generic private/community platforms (the "fork instead?" shelf)

| Repo | Stars | Last push | Status | Notes |
|---|---|---|---|---|
| humhub/humhub | 6,704 | 2026-07-19 | ACTIVE | PHP/Yii2 enterprise social network; Spaces (= pods), modules. Enterprise-flavored UX, not grandparent-flavored. Mobile app exists [UNVERIFIED] |
| diaspora/diaspora | 13,654 | 2026-07-16 | ACTIVE | Federated; "aspects" = per-user audiences, not shared family pods; Rails, heavy |
| friendica/friendica | n/a* | commit 2026-07-18 | ACTIVE | *Excluded from GitHub search (mirror; canonical at git.friendi.ca) — stars unverifiable via API |
| mastodon/mastodon | 50,132 | 2026-07-19 | ACTIVE | Public-network DNA, no pods — wrong shape |
| pixelfed/pixelfed | 7,041 | 2026-06-29 | ACTIVE | Same caveat |
| GoToSocial | — | — | GONE from GitHub | superseriousbusiness/gotosocial 404s; moved off GitHub (Codeberg [UNVERIFIED]) |
| Elgg/Elgg | 1,678 | 2026-07-14 | ACTIVE | Engine/framework, not product |
| monicahq/monica | 24,874 | — | ACTIVE | Personal CRM — one-player, not a network |

### Tier 3 — Photo/memory adjacent (solved; integrate, don't rebuild)

| Repo | Stars | Last push | Status | What it is |
|---|---|---|---|---|
| immich-app/immich | 108,198 | 2026-07-20 | ACTIVE | Self-hosted photos/videos; native iOS+Android (Flutter), partner sharing, shared albums, AGPL |
| photoprism/photoprism | 39,985 | 2026-07-19 | ACTIVE | AI photo app (Go) |
| ente/ente | 27,883 | 2026-07-20 | ACTIVE | E2EE photo cloud (org renamed ente-io → ente) |
| immichFrame/ImmichFrame | 2,219 | 2026-07-17 | ACTIVE | Digital photo frame client for Immich — de-facto OSS "grandparent display" |
| impworks/bonsai | 208 | 2026-07 | ACTIVE | Family wiki + photoalbum + pedigree |
| sweetmeats83/memories | 2 | 2026-07-11 | ACTIVE | Elder storytelling: **time-limited token link; elder taps and records — no account, no login**; Whisper transcription; Android APK shell |
| tymrtn/family-book | 21 | 2026-07-15 | ACTIVE | Private family tree + archive (FastAPI/HTMX) |
| Segelzwerg/FamilyFoto | 9 | 2025-08 | ARCHIVED | Graveyard |

### Tier 4 — The 2026 "self-hosted family organizer" wave (adjacent, instructive)

`topic:self-hosted + topic:family` = 60 repos, dominated by: ulsklyc/yuvomi (1,006★, created 2026-03! — 16-module planner, PWA, 23 languages, web installer, TrueNAS/Umbrel/Unraid listings, MCP endpoint), cmintey/wishlist (602★), pablitofernandez/FamilyNido (74★, .NET10+Angular21 household PWA with a "Wall" message board, openly pair-programmed with Claude Code), tribu (13★), ~20 fresh 0–1★ entries. Organizer ≠ feed, but this is where the energy and the modern polish bar are.

## A. Any active, polished family-focused OSS social network?

**No.** Contenders honestly ranked: **zusam** (right concept, real demo, alive; 222★ after 9 years, web-only, pre-1.0); **cousins-matter** (astonishingly complete incl. elder-managed profiles, demo + docs + CI + Docker — 2 stars, 0 forks, one French maintainer); **Orbital** (2026-born, family-specific, Signal-E2EE, real iOS/Android codebase — 0 stars, backend not public). HumHub is the only *polished* thing in range and it's enterprise community software. The category is genuinely empty at the "serious project" bar.

## B. Where exactly is the whitespace?

- Photo storage/backup: **fully occupied** (Immich, Ente, PhotoPrism). Integrate, don't compete.
- Family organizers (calendar/chores/meals): **saturated as of 2026**, high polish, AI-built entrants monthly.
- Generic fediverse/private platforms: occupied but structurally wrong — instance-level or per-user privacy (diaspora aspects), not per-pod family layers; UX built for admins/netizens, not grandmothers.
- **The empty square:** a low-friction, mobile-first, async **family feed** — links + photos + short updates — with **nested privacy pods** (my household → siblings' families → whole extended clan) and **grandparent-grade onboarding**. Nobody active does pods-plus-shared-layer at all (zusam's flat groups closest). The best onboarding idea in the sweep — Memories' tokenized no-login links for elders — exists only in a 2-star app. Immich-grade execution applied to zusam's job, with Memories' onboarding and ImmichFrame's ambient display as the grandparent surface: **that combination does not exist.**

## C. What the graveyard has in common

1. Single maintainer, zero bus factor.
2. Generic-platform ambition (or decentralized-protocol overreach) instead of the family job — scope killed them pre-PMF.
3. No mobile story (2010–15 cohort uniformly web-only exactly as users moved to phones; Facebook Groups + WhatsApp ate them).
4. No distribution (never reached awesome-selfhosted / NAS-app-store flywheel).
5. The 2025–26 micro-cohort dies differently: AI-assisted 0-star PWAs shipped in a weekend, never marketed — **building is no longer the moat.**

## D. Strongest adopt-or-fork candidates, honestly

1. **zusam** — if the goal is running-this-month. Right shape; you'd add PWA/push/mobile + pods and effectively co-maintain.
2. **HumHub** — maturity + per-Space pods today; enterprise UX tax.
3. **Immich (integrate, don't fork)** — photo backend; ImmichFrame as grandparent display.
4. **cousins-matter** — sleeper: Django, MIT, 80% of features, 0% community; you'd *be* the project.
5. **Friendica/diaspora** — only if federation is a requirement; operationally heavy, UX-wrong for a closed family.

Net: no candidate removes the core work (pods + grandparent UX + mobile) — which is why the whitespace persists.

## E. Table stakes for portfolio-grade OSS in this niche, 2026

(Inferred from what Immich/Ente/yuvomi actually ship; even 1-star entrants have half of this — the bar is the complete set.)
1. One-command deploy + store presence: docker-compose with GHCR images; TrueNAS SCALE/Umbrel/Unraid catalog listings; a web installer/setup wizard is now differentiating.
2. Public demo instance — even 2-star cousins-matter has one; non-negotiable.
3. Real mobile: minimum installable PWA with web-push; credible = native (Flutter/React Native). Niche-specific: an elder path with **no account/app-store step** (token links) plus an ambient display client (ImmichFrame pattern).
4. Docs site with a non-technical-member onboarding page distinct from the admin install guide; screenshots incl. dark mode; CHANGELOG; SECURITY.md; CI badges.
5. i18n from early (yuvomi 23 languages, cousins-matter 6, zusam on Weblate).
6. License intentionality — AGPL-3.0 niche default (Immich, Mastodon, diaspora, zusam, Orbital) vs MIT for adoption-maximizing (yuvomi, cousins-matter).
7. Cadence + sustainability signals: tagged releases, Renovate-style upkeep, funding link, visible momentum.
8. 2026 wildcard: API + MCP endpoint (yuvomi ships /mcp) — cheap, disproportionately portfolio-worthy.

Strategic footnote: dozens of Claude-Code-built family apps launched since March 2026 — feature-building is commoditized; the defensible work is grandparent UX, pod modeling, mobile distribution, and staying alive — exactly what every graveyard repo lacked.
