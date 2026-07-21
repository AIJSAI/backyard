# ADR-005: the wave-boundary policy defaults, ratified

Status: accepted (2026-07-21)
Date: 2026-07-21
Owner: the founder (solo maintainer)
Informs: waves 3 and 4 ([wave plan](../wave-plan.md)), [PATH-TO-100](../PATH-TO-100.md) "What is left" bullet 3, S-402, S-501, S-502, S-705, S-901/S-902; the [threat model](../security/threat-model.md) tokens/email sections (T-EMAIL-2, T-EMAIL-G2, TM-1, TM-4)

## Context

Waves 4 and 5 were built while several policy knobs sat on proposed defaults, each with a value living in the code and a comment marking it "recorded for founder ratification at the wave boundary." The project's rule is that these are batched, not decided mid-build: the founder ratifies them once, on the record, at the boundary rather than one settings-change at a time ([PATH-TO-100](../PATH-TO-100.md) "What is left", bullet 3). This ADR is that ratification.

Nothing here changes behavior. Every value below is already the code's behavior and was exercised by the isolation and digest test suites as the waves landed; this ADR records the decision and its reasoning so the value is a ruling, not an unexamined default that quietly hardens into permanence. Where a number is a security clock, its rationale is checked against the mechanism it feeds.

## Decision

Ratify the proposed defaults as the v1 values, unchanged. One item — the S-705 family disclosure *wording* — is drafted and judge-reviewed but stays open pending the founder's own voice; it is the only item this ADR does not close.

### 1. Build overlap of waves 3 and 4 — ratified

Wave 4 (digest in/out) was built and closed-to-`built` ahead of wave 3's last story (S-402 video), because wave 3's remaining gate is a hardware measurement (ffmpeg transcode latency on the target box) and wave 4's code carried no dependency on it. The overlap is sound: the two waves share no code path that the out-of-order build could corrupt, and the tracker keeps each wave's `tested` flip gated on its own receipt. Ratified.

### 2. Digest-link TTL: 21 days — ratified

`digest_links.py` `DIGEST_LINK_TTL = timedelta(days=21)`. A capability link in a digest email opens for three weeks. Long enough that an elder opening a two-week-old email still lands on live content; short enough to cap the exposure of a link forwarded out of the family. The security backstop is revocation and the per-issue token generation, not the TTL — the TTL is the calm-path convenience bound, and 21 days sizes it to how late a low-frequency reader actually opens email. Ratified.

### 3. Reply-address grace: 30 days past supersession — ratified

`reply_addresses.py` `REPLY_GRACE = timedelta(days=30)`. A digest's per-post reply address (`reply-<raw>@<domain>`, ≥128-bit CSPRNG, SHA-256 at rest) is superseded the moment the member's next issue mints, and then keeps working for 30 more days before it dies (T-EMAIL-2). This is the "elder answers a month-old digest" window. It is deliberately time-based, not issue-count-based, so a burst of issues never shortens it. The other two kill clocks are unaffected and remain immediate: voiding on any membership change (TM-1) kills the address at once regardless of grace, and a token-generation bump (ADR-003) kills every address at once. Thirty days is the right calm-path grace precisely because the two hard-revocation clocks sit underneath it. Ratified.

### 4. Date-visibility defaults: YARD for adults, POD for supervised; contact fields HIDDEN — ratified

`models.py`: `birthday_visibility` and `anniversary_visibility` default `YARD`; `phone_visibility` and `contact_email_visibility` default `HIDDEN`; supervised members are narrowed to `POD` at creation and by migration 0013 (T-MINOR-6). So an adult's birthday and anniversary are visible to their side of the family by default (the calm surfaces — the digest banner and feed — never a push), a supervised member's dates are visible only within a shared pod, and phone and email are shown to no one until the member opts in. This is the correct default posture: the celebratory dates that make the directory worth having default open to the yard for adults, the more sensitive contact fields default closed, and minors default to the narrower pod scope. Per-field, per-member control overrides all of it. Ratified.

### 5. Bridge household's pod-only posts appear in both sides' digests: yes — ratified

`digest_send.py` sends one digest per `(member, yard)` across `scoping.visible_yards(member)`. A member who bridges two yards (a household spanning both sides of the family) receives a separate, yard-scoped digest for each yard; a pod-only post reaches every pod member through the pod, on whichever side's digest carries them. The pod spans the two yards; the yards themselves never fuse — each digest is assembled inside one yard's audience scope, so no cross-yard content leaks through the bridge. This is the intended topology (the pod is the bridge; the yard is the isolation boundary), and sending per-yard rather than per-member is what keeps a bridging member from becoming a fusion point. Ratified.

### 6. Top-quoting mail clients: quarantine, never recover — ratified

`inbound.py`: a reply whose text sits *below* the quoted digest (a top-quoting client, or any reply with no recoverable text above the deterministic digest separator) is quarantined for the instance admin, never posted (T-EMAIL-G2). The fail-closed choice is the security-correct one: attempting to recover text from below the quote risks republishing the quoted digest — which, for a bridging member, could carry the other yard's content — so the system never guesses. The admin sees the quarantined message and can follow up out of band. Recovering below-quote text is explicitly out of scope for v1; if it is ever built, it is a new feature with its own review, not a loosened default. Ratified.

### 7. Digest enrollment and send timing — ratified

Two sub-decisions, both already embodied in the code:

- **Opt-in with double-confirm, not silent default-on.** `digesting.py`: a subscription is created, then a confirm link must be clicked before *any* family content flows. Even an admin-initiated enrollment cannot leak a single post to an unconfirmed address. This is the privacy-correct default and needs no "default-on vs opt-in" debate — the confirm gate makes the distinction moot for content exposure. Ratified.
- **Rolling per-member weekly cadence, not a global send-time.** `models.py` cadence defaults `WEEKLY`; `digesting.py` `due_recipients` marks a member due when `anchor + period ≤ now`, where the anchor is their newest issue's `window_end` (or their confirmation time, for the first issue), checked hourly by the worker. There is deliberately no global "everyone Sunday at 9am" send: each member's digest arrives roughly weekly from when they joined, which spreads send load and avoids a thundering-herd fan-out. A fixed weekday/hour send is a defensible post-v1 option but is not the v1 default. Ratified.

### 8. S-705 family disclosure — value ratified, wording pending founder voice

The privacy *posture* is ratified and already enforced in code: the only per-person datum Backyard keeps is a weekly yes/no presence flag (`models.py` S-705 aggregates); there is no time-on-site, no session count, and no per-person activity feed anywhere, and the per-person flag is only ever surfaced as pod- and yard-level totals. S-705's acceptance also requires that the family be *told* this in plain language. That disclosure is family-facing prose in the founder's own voice, so its wording is drafted and judge-reviewed (see [the family privacy note](../family-privacy-note.md)) but is not finalized here — it is the one item awaiting the founder's sign-off before it is presented to the family. Everything the disclosure describes is already true in the code; only the words are pending.

## Consequences

Bullet 3 of PATH-TO-100's "What is left" (the batched policy defaults) is closed by this ADR, save the S-705 wording. The remaining two founder-gated blockers are unchanged and independent of this decision: wave 4's `tested` flip still waits on a live email provider and its measured delivery/bounce matrix, and wave 3's still waits on the target hardware and a measured transcode latency. None of the values here is load-bearing for those measurements; they were ratified now so that when the provider and the box arrive, the wave closes turn only on the measurements, not on re-opening settled policy. Each value remains a single constant, changeable later by a one-line edit with its own commit — ratification records the v1 decision, it does not freeze the knob.
