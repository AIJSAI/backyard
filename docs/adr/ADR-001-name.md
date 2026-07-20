# ADR-001: The name is Backyard

Date: 2026-07-19 · Status: accepted

## Context

Two verification waves over 32 candidates (18 + 14), one research agent per name, checking: GitHub collisions (repos, orgs, users), product collisions via web sweep, domain registration via RDAP/whois, and language sanity in ES/FR/DE/PT. Summary table in [the naming decision record](../research/2026-07-19-naming-decision.md).

Eleven candidates died on FATAL same-space collisions, several on active family products we would have crashed into blind: Hearth Display (40k families), Banyan family trees on banyan.family, Den's family wall hub on den.family, two live Kinship family products, Homeroom classroom albums, two live Murmur social apps. Wave 1 finalists (Kettle, Supper, Quilt, Gable) were rejected on brand direction: the audience median is high-schoolers through sharp 50s adults, and cottagecore reads wrong.

## Decision

**Backyard.** Runner-up Clan was rejected for three compounding hazards: an active, respected self-hosted OSS project already named Clan (clan.lol) in our exact distribution channel; the German "Clan-Kriminalität" organized-crime connotation in a DACH-heavy self-hosting community; and the spoken homophone with "Klan" in a US family context.

## Rationale

- The same-space lane is empty: the only prior backyard-social products are both defunct.
- `backyard.family` and `backyard.social` were both available at decision time (owner registering).
- No notable exact-name repo on GitHub; this repo lives at AIJSAI/backyard.
- The in-product language writes itself: pods are pods, and the shared everyone-layer is the backyard. "Post it to your pod, or throw it in the backyard."
- Brand fit: the backyard BBQ crowd is exactly the user group, both sides of a family, ages 15 to 60.

## Accepted risks

- Backyard AI (active AI character-chat app) shares the word in software. Unrelated job; it weakens future trademark options; coexistence expected at OSS scale.
- Generic-word SEO is permanently uphill. Mitigation is structural: onboarding is invite-link based and OSS discovery flows through directories and "self-hosted family network" queries, not "backyard."
- Bed Bath and Beyond operates a "Backyard" retail outlet brand (different goods class).

## Consequences

- Domain: `backyard.family` registered 2026-07-20 (Cloudflare Registrar). Amended from the original two-domain plan: `.social` ($70/yr) was defensive-only, and this ADR already accepts that a generic word cannot own its namespace. Revisit only if brand sprawl becomes a measured problem at launch.
- Project home: `backyard.family` (docs, demo). The maintainer's private family instance lives on an unadvertised, auth-gated subdomain. Each family that deploys Backyard uses its own domain.
