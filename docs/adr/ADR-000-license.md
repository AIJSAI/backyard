# ADR-000: AGPL-3.0 for the application, DCO for contributions

Date: 2026-07-19 · Status: accepted

## Context

Backyard is an end-user application (deployed, not imported), so the classic "MIT maximizes adoption" argument, which is about libraries and corporate dependency policies, mostly does not apply. Category evidence agrees: license did not decide traction for either Immich (AGPL-3.0, ~108k stars) or yuvomi (MIT, ~1k stars within 4 months). The product's identity is "your family's data cannot be enclosed by a platform." The failure mode that actually matters is a closed commercial fork hosting families' data against the project's privacy thesis.

## Decision

- **AGPL-3.0** for the application.
- **MIT or Apache-2.0** for any spun-out reusable libraries (client SDK, MCP server) so they travel maximally.
- **DCO sign-off** (`git commit -s`), no CLA. While the maintainer is sole copyright holder he retains the ability to relicense; merging outside contributions under DCO progressively locks AGPL in place. That is accepted: there is no commercial plan, and CLA friction plus its optics cost more than the optionality is worth.

## Consequences

- Anyone hosting a modified Backyard as a service must offer users the source. Families self-hosting unmodified builds have zero obligations.
- Both licenses in play are OSI-approved, so awesome-selfhosted and NAS catalogs stay open.
- The license does not protect the name; trademark is a separate, optional, later step.
- This mirrors Immich's structure, the category's execution benchmark.
