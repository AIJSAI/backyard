# ADR-002: The stack

Status: accepted (founder sign-off, 2026-07-20)
Date: 2026-07-20
Owner: the founder (solo maintainer)

Method: seven candidate stacks, each argued by a separate AI research agent against the 33-story v1 cut, the same agent-per-candidate method as [ADR-001](ADR-001-name.md). Every load-bearing claim was verified against current sources: GitHub releases, npm and PyPI, endoflife.date, and Context7 library docs, all fetched 2026-07-20. Four more agents ran stack-independent studies on the hard problems (inbound email, media pipeline, PWA and push, passkeys and capability tokens), and a four-lens panel of agents then scored every candidate. This is one founder running structured agent research, not a human panel, and saying so matters: the scores are only as good as the grounding behind them. The full dossier, including every version check and the claims the agents could not verify, is committed at [docs/research/2026-07-20-stack-dossier.md](../research/2026-07-20-stack-dossier.md), and the unverified claims are carried into the Phase 2 gates below. The score table here is reproduced from that dossier.

## Decision

**Django 5.2 LTS + htmx 2 + Alpine.js, PostgreSQL 18, four containers.** Specifically:

- **Framework:** Django 5.2 LTS (extended support to April 2028; one planned LTS-to-LTS hop to 6.2 in 2027). Server-rendered pages with htmx 2.0 for the interaction surface and Alpine for small client behaviors. Strict typing via django-stubs and mypy.
- **Database:** PostgreSQL 18, the only stateful service. Django migrations carry the archive-safety promise (S-803); the seeded old-database upgrade test runs in CI from v0.1.
- **Jobs and cron:** Procrastinate 3.9 (Postgres-native queue, LISTEN/NOTIFY, first-class Django integration). Digest schedules, transcode queue, link-preview fetches. No Redis, no broker container, ever.
- **Compose shape (S-801):** caddy (TLS, reverse proxy, access-checked media serving) · web (gunicorn + Django + WhiteNoise) · worker (same image, `procrastinate worker`, ffmpeg installed) · postgres. One image, four containers, one volume for media, one for the database.
- **Auth (S-101):** django-allauth 65.18 with passkey login primary (`MFA_PASSKEY_LOGIN_ENABLED`) and password fallback. Known caveat, planned as custom code: allauth's built-in passkey signup requires email verification, which conflicts with invite-token signup where email is optional; the invite flow is therefore a custom view that creates the member from the invite token, then runs allauth's WebAuthn enrollment.
- **Capability tokens (S-102, ADR-003):** one small token service rather than a library: four token families (elder master, digest deep link, signed media URL, reply address) with typed prefixes, at least 128-bit CSPRNG values, hashed at rest, all carrying the generation ID from ADR-003 so one transaction revokes everything. Signed expiring URLs via `django.core.signing.TimestampSigner`, which ships with Django; no extra dependency.
- **Email out (S-501):** Django core mail (multipart HTML plus plain text, inline images) rendered from the same template engine as the site, with django-anymail 15.0 as the transport layer so one settings change moves between a provider, self-hosted Postal, or bare SMTP submission.
- **Email in (S-502):** one narrow ingest interface, three adapters. Default posture for v1: IMAP-poll a dedicated family-controlled mailbox every 60 seconds and send digests through that same account's port-587 submission. Second adapter: provider inbound webhooks via Anymail's normalized inbound (Postmark, Mailgun, SES, and eight others). Third, later: an in-process SMTP sink for families who want full sovereignty and can stomach MX on a home connection. Reply addresses carry an HMAC token in the local part and fall back to In-Reply-To matching when a mail client mangles the address. The docs will say "bring your own submission relay" and mean it: direct-to-MX sending from a home IP lands in spam, and we will not pretend otherwise.
- **Images (S-401):** Pillow 12.3 in worker tasks: `ImageOps.exif_transpose` for orientation, explicit GPS strip on save, size renditions for feed and digest. Client-side pre-upload resize is roughly thirty lines of hand-rolled Canvas code; the popular wrapper library (browser-image-compression, last release March 2023) is dormant and will not be a dependency.
- **Video (S-402):** ffmpeg pinned in the worker image, driven as a subprocess from a dedicated Procrastinate queue with concurrency 1, following Immich's preset philosophy for the same hardware class (720p H.264/AAC, fast presets), with hardware acceleration as a documented opt-in flag. Caps enforced at the API boundary with a clear rejection, never a silent failure.
- **PWA (S-103) and push (S-305):** manifest plus a deliberately minimal service worker; no app-shell precache. Web push ships post-v1: S-305's only permitted notification is opt-in replies-to-me, and the digest plus the unread boundary carry the catch-up loop without it. When it ships: pywebpush with self-generated VAPID keys, declarative payloads. The elder token surface stays server-rendered and never depends on a service worker: Safari evicts a site's service worker after seven days of Safari use without a visit, and though an installed home-screen PWA is exempt, elders on a bare token link are the definition of intermittent visitors.
- **Testing:** pytest-django for unit and integration (including the S-202 isolation suite against a real Postgres and the S-501 no-promotional-content gate), Playwright for end-to-end across the member PWA and the elder token surface.
- **Toolchain:** Python 3.13, uv for dependency management, ruff for lint, mypy with django-stubs for types. All four in CI from the first code commit.

## The scores

Four agents, one per lens, scored every candidate 1 to 10 from the grounded dossier. DQ means the lens ruled the candidate out entirely.

| Candidate | Boring to operate | Story coverage | Solo maintainer | Five-year archive | Mean | Principle-weighted* |
|---|---|---|---|---|---|---|
| **Django 5.2 + htmx** | **9** | 8 | 7.5 | **9** | **8.38** | **8.50** |
| Next.js 16 + Drizzle | 5.5 | **9** | **9** | 5.5 | 7.25 | 6.90 |
| React Router 7 + Drizzle | 6 | 8.5 | 8 | 5 | 6.88 | 6.60 |
| Go + templ + htmx | 8.5 | 5 | 3 | 8.5 | 6.25 | 6.70 |
| Phoenix + LiveView | 8 | 6.5 | DQ | 7 | n/a | n/a |
| SvelteKit 2 + Drizzle | 7 | 7 | 5.5 | 4.5 | 6.00 | 5.95 |
| AdonisJS 6 | 5 | 7.5 | 5 | DQ | n/a | n/a |

*Principle-weighted: boring-to-operate and five-year archive at 1.5x, because [Principles 7 and 8](../principles.md) make them constitutional for a product that holds a family's archive and promises to survive maintainer neglect. Mean and weighted mean are left blank for the two disqualified candidates, since a DQ is not a low score to average.

Django is the only candidate with no lens below 7.5. It wins under both weightings.

## Why not Next.js, the founder's home framework

This was the real contest, and the honest answer is that Next.js lost on the product's own constitution, not on quality. It won story coverage (an actively maintained TypeScript library exists for every unusual need, including in-process inbound SMTP) and the maintainer lens (the founder runs Next.js in production today; the annual-major tax is already being paid across his other repos). It scored 5.5 on both weighted lenses (boring to operate and five-year archive), for reasons the agents grounded live: an annual major-version treadmill with roughly two-year support windows against an app that must build unchanged in 2031; Drizzle still on 0.x with a 1.0 release candidate already deprecating APIs; and a calm, server-rendered, mostly non-interactive product that uses almost none of what React is for. That is the call that decides this ADR: a family archive's stack should be chosen for the year the maintainer disappears, not the year the maintainer is fastest.

Revisit trigger, recorded now: if v1 story work shows the htmx interaction surface fighting the product (the audience picker and composer are the risk spots), the runner-up is Next.js with Drizzle post-1.0, and the migration cost is bounded because Postgres and the token service carry the contract.

## Why not the rest

- **React Router 7:** same family as Next.js with a smaller ecosystem for this spec; dominated on every lens by one neighbor or the other.
- **Go + templ:** the strongest operations and longevity scores of the field (8.5 and 8.5), but the maintainer lens scored it 3: the founder reads Go but doesn't write it fast, and the story-coverage judge found the most hand-assembly of any candidate (5).
- **Phoenix LiveView:** genuinely strong operations and the best upload story of the seven, but disqualified by the maintainer lens: a non-fluent language, the smallest contributor and passkey-library ecosystem, and no path to drive-by OSS contributions from either of the founder's communities.
- **AdonisJS 6:** disqualified by the longevity lens. AdonisJS has already lived the exact failure mode the archive must survive: a hard framework rewrite between major versions that broke older apps, which the agent verified against its release history this session.
- **SvelteKit:** solid on every lens but compelling on none, and the weakest five-year score of the non-DQ field (4.5), given Svelte's major-version cadence.

## Costs we accept, named

- The founder trades his strongest language for his second-strongest. Typed Python is fluent ground (two production systems), but Django idiom has a real learning curve, and drive-by UI contributors from the JS world will find server-rendered templates foreign.
- htmx 4.0 is in beta with a stated Summer 2026 target and no documented 2.x long-term-support commitment. We build on 2.0.10 pinned and absorb the major deliberately, or never; htmx's surface in this product is small by design.
- The media pipeline is assembled from primitives, not provided. That is true of every stack for video; Django adds no batteries for client resize or signed serving beyond `TimestampSigner`. This is where v1's engineering time goes, and the estimate should say so.
- Yard isolation (S-202) is application-layer discipline: membership-scoped default managers plus `get_object_or_404`, enforced by the isolation test suite as a merge gate from the first model. One missed scoped queryset is a cross-yard leak. Postgres row-level security as belt and suspenders is a Phase 2 decision, on the record.
- The Django admin is a multi-tenant footgun: a superuser sees every yard. It ships network-gated to the instance admin and documented as such (the threat model already treats operator power honestly).
- Bus factors: allauth and Anymail each rest on effectively one primary maintainer. Mitigation is the same as for the WebAuthn client library: thin internal interfaces so any of them can be swapped without touching product code.

## Carried forward as Phase 2 validation gates (claimed by no one until measured)

- ffmpeg transcode latency for a 60-second 1080p clip on Celeron/N100-class hardware: the "minutes" in S-402 is plausible and unbenchmarked. Measure on target hardware before the story's acceptance is locked.
- RAM footprint across the four containers (engineering estimate 0.7 to 1.2 GB; not measured).
- pillow-heif for iPhone HEIC ingestion (v1 avoids HEIC via mandatory client re-encode; S-503 will force the decision).
- Anymail delivery-and-bounce tracking coverage for the chosen provider, before S-501's per-member delivery-status view is promised.
- Link-preview fetching (S-301) is hand-rolled security-sensitive code: SSRF protection, private-IP blocking, timeouts, size caps. It gets its own review.

## Consequences

The first code commit ships with the full toolchain in CI (ruff, mypy + django-stubs, pytest, build), the compose file targets the four-container shape from day one, and the token service and generation-ID revocation from ADR-003 go in before any product code depends on them. The stack decision deliberately spends the founder's fluency budget on the product's hardest promises (archive safety, boring operations) instead of his fastest framework, and the PR that lands this ADR should be judged on whether that trade reads as sound five years from now.
