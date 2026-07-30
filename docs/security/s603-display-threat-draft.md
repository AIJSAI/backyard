# S-603 ambient display — threat-model draft

NOT yet part of the threat model. This is the pre-code analysis the threat model requires
before a new capability type ships ("New capability types cannot ship without registering
here"). It moves into `threat-model.md` section 3.9 in the same PR as the display code, or is
deleted if the founder drops S-603.

## New section 3.9 — The ambient display

Prose intro:

The photo frame is the only surface where the *audience is a room, not a person*. Every other
credential in the system is held by someone: a link in Nana's texts, a session on her phone, a
reply address in her mail client. A display credential lives on a powered-on tablet on a
kitchen counter, and what it shows is visible to whoever is standing there — a neighbour, a
contractor, a houseguest, a carer. It is also the only credential nobody ever touches again
after setup, which means it is the only one that will not be rotated, noticed, or revoked by
its holder.

| ID | Threat | Likelihood | v1 answer | Residual |
|---|---|---|---|---|
| T-DISPLAY-1 | The audience is the room. A frame rotating recent family media shows children's photographs to everyone who walks past — a contractor, a carer, a houseguest, a visiting neighbour — with no act of sharing and nobody present who decided to show them. | High | The display's scope is chosen at provisioning and is **narrower by default than the member's own reach**: it names the pods/yards it may rotate, defaults to the narrowest (the household pod), and the admin sees a preview of the exact assets it will show before the credential is minted (the S-104 provisioning-preview shape). It never reaches yard-wide media unless that is chosen explicitly, and never a pod the assigning member is not in. | A frame in a shared room shows family photos to whoever is in that room; that is what a photo frame is. The control is that the family chose the scope knowingly, not that the software can police a kitchen. |
| T-DISPLAY-2 | Nobody ever touches it again. A frame set up once is never re-authenticated, so the credential outlives the tablet's usefulness: it is sold, donated, handed to a grandchild, repaired, or stolen, and it keeps pulling the family's photographs from wherever it now is. | High | Registered in the TM-1 registry with its own revocation step and its own completeness assertion, generation-anchored like every other class. It is listed in the admin's credential surface with **last-seen**, so a display that has moved or gone dark is visible; and because it is a stateful row, one-tap revoke kills it as a row, not only as a check. | A tablet sold between the last poll and the revoke keeps working until the next poll. The window is the poll interval, not forever. |
| T-DISPLAY-3 | The URL is in a browser on a device other people pick up: address bar, history, autocomplete, a screenshot, a screen-share. Anyone who reads it off the tablet can then read the family's photographs from anywhere, indefinitely, with no trace. | Medium | The URL-to-cookie exchange TM-5 already mandates for `/t/`: the tokenized URL is exchanged for an httpOnly cookie on first open and redirected to a clean path, so what sits in the address bar afterwards is not a credential. `no-referrer` on the display surface; `X-Robots-Tag: noindex`; the raw value is 256-bit CSPRNG and stored only as a hash. | A cookie on the device is still a credential on the device, which is the point of a frame. Reading it off the screen is now bounded by physical access at the moment of setup rather than forever after. |
| T-DISPLAY-4 | A standing, always-on media grant becomes a second audience path: the rotation endpoint re-derives "recent photos" instead of consuming the one audience query, and drifts from it. | Medium | The display resolves through `scoping.visible_media` for its assigned member, narrowed by the credential's own pod/yard ceiling — the `Reader` ceiling pattern `viewers.py` already uses for a digest token, not a new query. Media bytes keep going through the single access-checked serving path (TM-9). Acceptance: a deleted asset, a narrowed audience and a removed member each disappear from the rotation on the next poll. | The frame holds whatever is on screen until the next poll; a photo deleted this second is visible for that interval. Same shape as the digest's residual, bounded by seconds rather than weeks. |
| T-DISPLAY-5 | **A device becomes a person.** S-603's second acceptance criterion counts a display heartbeat as an elder touch. A heartbeat is a powered-on tablet, not a deliberate act, so the family's one signal that an elder is still connected — and the KPI it feeds — reads "active" for as long as the frame has electricity. The signal that would tell the family Nana has gone quiet is exactly the one this silences. | High | **A display heartbeat is recorded as a display signal and does NOT enter `touched`.** `docs/metrics.md` defines active as *"any deliberate touch"*, and the same document's elder-touch row lists the frame heartbeat — the contradiction is inside one file. The heartbeat is worth keeping under its own name (*"the frame in the kitchen has been dark for nine days"* is a real signal, and arguably a better one), but it is never laundered into human presence. Acceptance: a member whose only activity is display heartbeats is `present=False` for that week. | The family may read a lit frame as "she's fine" anyway. Software cannot fix that, but it must not assert it. |

**Binds:** TM-1, TM-5, TM-9, T-MEDIA-1, T-YARD-7, S-603, S-104, S-702.

## TM-1 amendment

Add the display credential to TM-1's enumerated registry list and to
`_REVOCATION_STEPS` + the completeness test, in the same commit as the code.

## The founder decision to surface

metrics.md:9 vs metrics.md:21. Recommendation: keep the heartbeat, rename what it measures,
and keep it out of `touched`. This is the T-DISPLAY-5 answer above and is the safe default —
wiring a signal into the KPI later is one line; un-corrupting a metric's history is not.
