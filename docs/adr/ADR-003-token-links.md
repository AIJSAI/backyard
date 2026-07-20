# ADR-003: Token links that can be forwarded

Status: proposed (Phase 1; goes to accepted with the founder's batched Phase 1 sign-off)
Date: 2026-07-20
Owner: the founder (solo maintainer)
Informs: [threat model](../security/threat-model.md) (T-TOKEN-1 through T-TOKEN-8), stories S-102, S-104, S-202, S-403, S-501, S-502, S-601, S-602, S-701, S-702

## Context

The README makes a promise and names its cost in the same breath: an elder path that is just a link, and "a link that just works is a link that can be forwarded." This is the decision record that promise pointed to.

The constraint that shapes everything: research requirement R3 says never assume a smartphone at the oldest generation, and the elder path exists so that Nana taps one bookmark for months of daily use with no password, no account, no app store. Every classic mitigation for a leaked credential (short expiry, re-login, device challenges, PINs) is a direct violation of that requirement. The threat model's adversarial pass put it bluntly: any security fix that adds a challenge to the elder surface has failed the product by definition.

So the token cannot be made hard to copy. The design instead makes the token cheap to kill, small in what it grants, and loud about who is using it.

## Decision

The elder token is a **long-lived bearer credential, accepted as forwardable**, governed by six binding rules. These rules are design commitments that become acceptance tests; none of them is built yet.

**1. The master token never rides the digest pipeline.** Email is the most realistic leak channel (forwarded digests, compromised elder mailboxes), so the long-lived master token is never in one. It is handed over once, by text or a printed QR (rule 6), and that hand-over message is a copy, named as a risk below. Digest deep links use separate per-member, per-digest tokens: read-only, scoped to the digest's content, and dead within weeks rather than days, because elders read digests late and a link that is dead on first tap fails R3. Inline digest images use signed media URLs on the same clock. So a years-old mailbox holds only stale links, and apart from the one hand-over message the bookmark on Nana's home screen is the only long-lived copy. An expired digest link degrades to a plain page that says the link expired and offers the bearer nothing.

**2. Capability ceiling.** The token grants read, one-tap react, and comment-by-email-reply. It grants nothing else: no directory contact fields, no member list, no export, no invites, no profile edits. A forwarded link leaks the feed. It never leaks the family's phone numbers, addresses, or structure. This costs real elder utility (the directory is exactly what elders want) and we accept that cost for v1. We will revisit it.

**3. One revocation invariant kills everything.** Every derived credential (session cookie, digest link, signed media URL, reply address) carries the member's token-generation ID and is checked against it server-side on every request. Regenerate or removal bumps the generation: the token, all sessions, all digest links, and all media URLs die on their next request, at once. The acceptance test gets written before the code: after regenerate and after member removal, each of those four credential classes returns 404. Media URL lifetimes are tiered by surface (short for the app, digest-length for email) but the TTL is never the revocation mechanism; the generation check is.

**4. Every bearer credential meets the same bar.** At least 128 bits from a CSPRNG, stored server-side only as a hash, and an invalid token returns the same 404 as an unknown route, extending the S-202 discipline. Token, digest, and media routes carry X-Robots-Tag noindex and robots.txt disallow. Those directives are advisory: well-behaved search crawlers honor them, but scrapers and archive.org can ignore them, so they lower the odds a public paste gets indexed and regeneration remains the real control once a link is known to be loose. First open exchanges the URL for an httpOnly session cookie and redirects to a clean URL; token-surface pages set Referrer-Policy no-referrer; logs record only a hash prefix, never the raw token.

**5. One authorization path, not two.** The token surface runs through the same membership and per-post audience filters as session auth. The S-202 isolation tests enumerate the token surface, digest rendering, and signed media URLs as request classes: cross-yard access 404s through every one of them, and a cousins-pod post never reaches the elder's digest or token feed. If an implementation ever adds token-specific authorization code, that code is the bug this ADR predicts.

**6. Killing a link must not cost the family a visit.** Nearly every residual risk below ends with "until someone regenerates" (the exception is content already copied, which nothing can recall), so regeneration has to be socially cheap, not just one admin click. The regenerate flow ends with the re-hand-over in hand: the new link ready to text and a fresh printable QR page. The tech-helper's runbook is one message, not a project. Token links are never issued to supervised kids (server-enforced in the S-701 permission matrix); the lowest-friction path must not become the default child credential.

## Alternatives rejected

- **Short expiry or periodic re-auth.** Fails R3 outright. A token that stops working is a phone call to the tech-helper and an elder who quietly stops checking.
- **PIN or challenge on the elder surface.** Same failure, smaller font.
- **Device binding and new-device alerts.** Surveillance-shaped machinery for a 25-60 person family, in tension with the no-monitoring rule (S-705), and it does little that named attribution does not already do. Cut from v1 by the adversarial review; may return later as a coarse admin-only signal.
- **No token path at all (accounts for everyone).** Fails the reason the product exists. Roughly 22% of US adults 65+ own no smartphone (Pew Research, 2025; see R3), and consume-only or login-walled elder surfaces failed in deployment research (R2, R3).

## What we accept, in plain words

- A forwarded master link works until someone notices and regenerates. Detection is social, not technical: every reaction renders as the named member, and in a family this size, active misuse looks wrong fast. The honest gap: a holder who only reads renders as no one and generates no signal at all, and with device alerts cut from v1 nothing in the design notices a silent reader. We accept that. The remedy is periodic regeneration on a schedule the family sets, not detection.
- A freshly forwarded digest is readable by its recipient for the digest-token lifetime (weeks). The win we bank is that mailbox archaeology goes stale; the win we do not claim is that forwarding is impossible.
- On a shared device, the session cookie is the access, and the hand-over text or QR still holds the original link. Household device custody is a household matter; the software's remedy is regenerate.
- Revocation controls future requests only. Screenshots, downloads, and cached pages are beyond revocation forever. No family should believe regenerate un-shares a photo, and our docs will say so.
- A stranger who has both a leaked reply address and the ability to spoof the elder's sending address can post comments in the threads whose addresses leaked, each visibly marked "via email" and killed by regenerate. Reply addresses are per-post, so the blast radius is the posts in the digest that leaked, not the whole feed. The sender-plus-token match stops the accidental and the lazy cases, which the threat model ranks as the realistic ones (T-TOKEN-8).

Two lifecycle risks named by the threat model bind here but are decided there. First, a deceased member's credentials: a memorial state must bump the generation without reading as deletion. Second, instance shutdown or domain lapse: every token's trust anchor lives exactly as long as the domain, and the shutdown runbook revokes every token first.

## Consequences

The session layer and the generation-ID check exist from the first code commit; retrofitting revocation onto stateless bearer URLs later would be far more expensive than carrying the state now. The digest pipeline mints its own token class from day one. The elder surface stays free of every security ceremony, which means the security work lives entirely in credential design, scope enforcement, and tests, where elders never see it.
