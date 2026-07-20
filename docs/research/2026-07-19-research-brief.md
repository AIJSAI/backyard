# Private Family Social Network — Research Brief & Verdict
**2026-07-19 · for James Shehan · builder-first serious OSS portfolio project**

---

## Verdict

**Yes — this project makes sense, and the research strengthens rather than weakens the case.** Three independent evidence streams converge:

1. **The whitespace is real, specific, and verified twice.** No active, polished, family-focused OSS social network exists — confirmed independently by a live GitHub API sweep and by the canonical awesome-selfhosted catalog. The exact shape of the gap matches your two use cases verbatim: an async family **feed** (links + photos + short updates) with **nested privacy pods** and **grandparent-grade onboarding**.
2. **The design brief is validated by peer-reviewed deployment science.** Multi-month in-home field studies show async, ambient family sharing measurably enriches cross-generation contact — *when* built with reciprocity, non-invasive defaults, and a low-tech elder endpoint. The literature hands you the requirements list.
3. **The failure modes are known, and they're PM-shaped.** Every dead attempt died of adoption, scope, mobile, or distribution — not engineering. In 2026, with feature-building commoditized, the defensible work is exactly the product-management work. That's an unusually good fit for a *portfolio* project.

**What the research does NOT support:** this as a *business*. The one dedicated commercial attempt (Togethera) died despite loved product and funding; survivors (FamilyAlbum, Tinybeans) live on corporate subsidy. Good news: you're not building a business. But note honestly — OSS traction in this niche is also unproven (the most feature-complete OSS family network has 2 stars), so the OSS bet is on *your* distribution and staying power, not on the category carrying you.

---

## Method

- **Stream A — GitHub landscape:** ~15 live GitHub API queries (phrase, topic, direct-repo), README pulls on the 8 closest candidates. All stats fetched 2026-07-19/20 UTC.
- **Stream B — Deep-research workflow:** 103 agents; 5 search angles → source fetch → falsifiable-claim extraction → 3-vote adversarial verification per claim (2/3 refutes kills a claim). 9 findings survived; votes shown per finding.
- Confidence tiers: **high** = primary source verified verbatim, 3-0; **medium** = verified but secondary/time-sensitive/single-study.

---

## 1. The whitespace (verified twice)

**GitHub (Stream A):** "family social network" matches **25 repos on all of GitHub**. Best genuine entrant: [zusam](https://github.com/zusam/zusam) (222★, PHP/Preact, groups + link sharing + demo — but web-only, pre-1.0 after 9 years, one maintainer). Most feature-complete: [cousins-matter](https://github.com/leolivier/cousins-matter) (Django/MIT, elder-managed profiles, galleries, events, docs, demo — **2★, 0 forks**). The GitHub topic `private-social-network` contains **zero repositories**.

**Catalog (Stream B, medium confidence):** awesome-selfhosted's "Social Networks and Forums" category = exactly 40 projects; only HumHub is even *positioned* for private networks; ~75% is federated public microblogging (Mastodon et al.) and forum engines. A grep of the entire 2,349-line catalog for "famil" returns only genealogy and chore/gift tools. Precise framing: **no purpose-built small-family-pod product** (generic private-community kits do exist: HumHub, Elgg, OSSN, BuddyPress, Hubzilla). [awesome-selfhosted.net](https://awesome-selfhosted.net/)

**Zusam as sole direct incumbent (high, 3-0):** free, AGPL, explicitly friends-and-family — and small, slow-cadence (14-month release gap; no master commits since March 2026), no backwards-compatibility guarantee. **Stability/maturity is itself the open differentiator.**

**Adjacent shelves are crowded — which sharpens the gap:**
- Photos: **solved at world scale** ([Immich](https://github.com/immich-app/immich) 108k★, Ente 27.9k★, PhotoPrism 40k★). Integrate; never rebuild.
- 2026 self-hosted family *organizers* (calendar/chores/meals): saturated, high polish ([yuvomi](https://github.com/ulsklyc/yuvomi): 1,006★ within 4 months of creation, 23 languages, NAS-store listings, MCP endpoint).
- Someone else spotted the same feed-gap in 2026: [Orbital](https://github.com/Pure-Karma-Labs/Orbital-Mobile) ("private family social network," E2EE, React Native, anti-group-chat pitch) — 0★ and its backend is not public. Validation, not yet competition.

**The empty square:** async family feed + nested pods (household → each side's family → whole clan) + grandparent-grade onboarding + Immich-grade execution quality. **That combination does not exist anywhere.**

## 2. Why past attempts died

**The OSS graveyard** (simplifeed, Teapotnet, FamilyFoto, knot, gravity-protocol, ~20 zero-star hulks) shares four causes: (1) single maintainer, zero bus factor; (2) generic-platform or protocol overreach instead of the family job; (3) no mobile story, in exactly the era users moved to phones; (4) no distribution — never reached the awesome-selfhosted/NAS-store flywheel.

**The commercial data point (medium confidence; OSS-fit inference passed only 2-1):** [Togethera](https://medium.com/@Togethera_app/togethera-is-shutting-down-9011dc519728) — premium private family sharing, ~65,000 users, £250K seed — shut down in 2016: *"not generating enough revenue to cover our costs"*, *"user base isn't growing fast enough"*, *"the space proved to be too difficult to crack"* ([TechCrunch](https://techcrunch.com/2016/07/04/family-photo-sharing-platform-togethera-shutters-after-low-growth-numbers/)). Verifier-imposed bound: FamilyAlbum (MIXI, 5M→10M users 2019–21) and Tinybeans survive commercially, so this is one paid-model failure, not category-wide proof. Read: **organic adoption of dedicated family apps is structurally slow — plan for it; don't monetize against it.**

**The 2026 twist:** dozens of AI-built family apps have launched since March and sit at 0–1 stars. Building is commoditized. **The moat is grandparent UX, pod modeling, distribution, and staying alive** — everything the graveyard lacked.

## 3. What the deployment science says (→ design requirements)

The strongest part of the evidence set — real in-home, multi-month field studies, all claims verified against primary sources:

| # | Requirement | Evidence | Conf. |
|---|---|---|---|
| R1 | **Async-first, ambient, non-invasive** | Tlatoque: two 21-week in-home deployments (n=30 family members) — older adult became more aware of relatives' activities; sharing **enriched and complemented** phone/in-person contact rather than displacing it ([Springer](https://link.springer.com/article/10.1007/s10606-012-9166-2), [IJHCS](https://www.sciencedirect.com/science/article/abs/pii/S1071581913000414)) | high (3-0) |
| R2 | **Reciprocity is a hard requirement** | Tlatoque v1 *failed*: relatives expected the elder to respond and the system gave her no channel. The bidirectional redesign succeeded in a second 21-week deployment. **Consume-only elder endpoints break the social contract.** | high (3-0, 3-0) |
| R3 | **Never assume a smartphone at the oldest generation** | Dutch field study (ages 73–87): nearly all non-users of computers/smartphones; Pew 2025: 22% of US 65+ own no smartphone. CHI 2025 positions ambient/tangible endpoints as the promising elder surface ([CHI 2025](https://dl.acm.org/doi/10.1145/3706598.3714302)) | high (3-0 ×3) |
| R4 | **Async isn't a compromise — it can be *better*** | Memento-storytelling study: async use produced *more complete, deeply reflective* stories from older adults; sync produced fragments ([PUC 2020](https://link.springer.com/article/10.1007/s00779-020-01364-9)) | medium (single study, n=8) |
| R5 | **Default OFF for always-on presence** | Family Window (6 families, 5 weeks–8 months in-home): only 6/16 would use always-on video with distant family — and even the receptive grandparent/young-parent dyad was split; two grandparents feared invading their kids' space ([CHI 2010](https://dl.acm.org/doi/10.1145/1753326.1753682)) | high (3-0) |
| R6 | **The problem itself is documented** | CHI 2024: older adults' challenge maintaining quality communication with distant younger family, corroborated by 2025–26 systematic reviews ([CHI 2024](https://dl.acm.org/doi/10.1145/3613904.3642318)) | high (3-0) |

Your original instinct — *"not invasive or disturbing, they look whenever they want"* — is literally what two decades of HCI deployment evidence prescribes. R1/R4/R5 are your late-night-YouTube-text use case; R2/R3 are the price of admission for the extended-family layer.

**Design translations (my analysis, labeled as such):**
- Elder path: **tokenized no-login links** (pattern exists in a 2-star app, [memories](https://github.com/sweetmeats83/memories): time-limited token link → tap → participate, no account, no app store) + **ambient display client** ([ImmichFrame](https://github.com/immichFrame/ImmichFrame) pattern) + optional email digest in/out. Email-reply-to-post gives R2 reciprocity with zero new habits.
- Presence features (who's-online, read receipts): off by default or absent (R5).
- No engagement mechanics. The product's promise *is* calm.

## 4. The everyone-day-one question (pressure-tested)

You chose "everyone (~30–80) from day one." The evidence says: **build the pod model for everyone; *onboard* pod-by-pod.**
- Reciprocity dynamics (R2) need a critical mass of *posters*, or new arrivals see a dead feed — the classic cold-start death in this category (Togethera: growth structurally slow even with a loved product).
- The receptive beachhead per Family Window's composition data: grandparents + parents of young children. Your seed pod is the household of 6 (your original job-to-be-done) — it already has a proven poster: you.
- Practical rollout (analysis): seed pod of 6 → prove the habit → recruit one high-energy pod per side → open the shared clan layer once ≥3 pods post weekly → time the full-clan invite to a natural gathering (the next wedding/holiday — your wedding moment was the insight; make it the distribution event).

## 5. Build vs fork (honest)

| Option | Gets you | Costs you | Fit |
|---|---|---|---|
| **Greenfield (recommended)** | The actual gap (pods + elder UX + mobile) is in no fork anyway; full stack choice; max portfolio value | Everything from scratch | ✅ builder-first goal |
| Fork zusam | Running this month; right shape (groups, links, demo) | PHP/Symfony; you'd add PWA/push/pods and co-maintain someone else's pre-1.0 | Only if speed-to-family beat craft |
| Fork cousins-matter | 80% of features, Django, MIT | 0 community; you'd *be* the project, on someone else's architecture | Weak for portfolio |
| Build on HumHub | Mature Spaces≈pods today | Enterprise UX tax; module-dev not product-dev | Wrong showcase |
| **Integrate Immich** | World-class photo backend + grandparent frame client | An integration surface | ✅ do this *within* greenfield |

## 6. Portfolio table stakes (2026 bar, observed from winners)

One-command deploy (docker-compose + GHCR) → NAS-store listings (TrueNAS/Umbrel/Unraid); public demo instance (even 2★ projects have one); installable PWA with web-push minimum; docs site with a **non-technical member onboarding page** separate from admin install; i18n early; deliberate license (AGPL-3.0 is the niche default — Immich/zusam/Orbital — vs MIT for adoption); visible release cadence; API + MCP endpoint as the 2026 wildcard (cheap, disproportionately portfolio-worthy).

## 7. Recommended path

1. **Product spec first** (PM-shaped moat, remember): pods model, elder path, v1 feed cut. v1 = feed (links with previews + photos + short updates) + pods + token-link/email onboarding. **Not in v1:** chat, events, always-on anything, federation, native apps.
2. **Name + repo + license decision** (AGPL vs MIT is a real fork in the road: copyleft protection vs adoption-maximizing).
3. **Architecture session** with live docs (Context7) — stack chosen against requirements R1–R5 + the table-stakes list, not by default. Security review per your workflow rules before anything touches family photos.
4. **Seed pod live by the next family gathering**; measure the only KPI that matters early: *do ≥4 of 6 check it weekly without being texted a link?*
5. OSS-launch machinery (demo, docs, listings) only after the family habit is proven — the graveyard is full of launches without users.

## Key sources

Zusam · cousins-matter · Orbital · Immich · ImmichFrame · memories · yuvomi (GitHub, fetched live 2026-07-19/20) · awesome-selfhosted · Togethera shutdown post + TechCrunch · Tlatoque (CSCW/IJHCS) · Family Window (CHI 2010 + tech report) · memento-storytelling (PUC 2020) · CHI 2024 intergenerational-communication study · CHI 2025 ambient/tangible co-design · Pew 2025 smartphone ownership (verifier corroboration).
