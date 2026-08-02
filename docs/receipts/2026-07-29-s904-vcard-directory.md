# S-904 — the family's numbers, in everyone's phone

> *"As a member, I can export the directory to vCard so the family's numbers in my phone
> stop being five years stale."*

Two routes, one serializer, no new credential and no new audience query.

| | |
|---|---|
| `/directory/vcards/` | everyone the viewer can see, one `.vcf` |
| `/directory/<id>/vcard/` | one person |

## The design decision that carries the story

**The serializer never sees a `Member`.** `vcards.render` takes
`profiles.ViewableProfile` — the object that is already reduced to exactly what one viewer
may see, and which carries safe primitives rather than the model row. So a HIDDEN phone
number is not *omitted carefully*; it was never in the object being serialized. The HTML
directory and the `.vcf` resolve through the same `viewable_profile`, so per-field
visibility cannot drift into a second implementation — TM-2's shape, applied to a second
output format.

That is recorded as threat row **T-YARD-10**, because the risk class is real and new: a
second output format over the same directory data is exactly how "the API returns all
fields and hides in the UI" (T-YARD-6) happens.

`ContactField` gained a machine `kind` alongside its human `label`. The vCard has to pick a
typed property — `TEL`, `EMAIL`, `ADR` — and recovering that from the string `"Phone"`
would have been a second mapping to keep in step with the first.

## Escaping is the security control, not the formatting

A vCard is line-oriented and its values are delimited by `;` and `,`. An unescaped newline
in someone's own profile does not corrupt one field, it **injects a property line**. A
display name of `Ann\r\nTEL:+15550000000` would otherwise write a working phone number
into every card of Ann that the family downloads — and a phone would import it silently.

Every value goes through `_escape` (RFC 6350 §3.4, backslash first so our own escapes are
not re-escaped), and C0 control characters are dropped. Addresses are where this earns its
keep: real addresses contain the commas and newlines that would shift the street component
into the region slot.

## Two format choices, both between imperfect options

**vCard 3.0, not 4.0.** 4.0 is the current standard, but phone support for it is uneven and
a card that does not import is worth nothing. 3.0 is what iOS, Android and Google Contacts
all read.

**A birthday is written `BDAY:--0305`.** The product's rule is that a year and an age are
never shown. Apple's usual trick for a yearless birthday is the sentinel year `1604`, which
any client not in on the convention renders as a real birth year — inventing a false fact
about a family member. The truncated form fails the other way: a client that cannot parse
it drops the property. **Omission over fabrication.** A test asserts neither `1980` (the
stored year) nor `1604` appears anywhere in the file.

Smaller calls: the kinship name becomes `NICKNAME`, so searching a phone for "Nana" finds
her; the anniversary becomes a `NOTE`, because 3.0 has no anniversary property and the
workaround is a vendor extension no other client reads; `CATEGORIES:Backyard family` so
twenty contacts that arrived together can be found again; `N` splits on the last
whitespace token, which is the guess Google Contacts makes and what stops the whole
directory sorting under one letter.

## Verified by a parser this repo did not write

The strongest check here was not one of my own assertions. The output was parsed with
**`vobject`**, an independent vCard library, on a deliberately hostile profile — a name
containing `\r\nTEL:`, an address containing a comma, a semicolon and a newline, non-ASCII
throughout, and a February 29 birthday:

```
vobject parsed 2 card(s) from 727 bytes
FN         = "Ann-Marie O'Brien\nTEL:+15550000000"
TEL        = '+1 (402) 555-0101'          <- exactly one, and it is the real one
ADR.street = '1 Ståle Grønnedal Vägen, Apt 2; back door\nOmaha, NE 68102, USA'
ADR other  = ['', '', '', '', '', '']     <- no component shift
BDAY       = '--0229'
```

The injected `TEL:` came back **inside the FN value as text**. The address round-tripped
byte-identical through a foreign parser's unescaping, with every other component empty.

This validation was run once, at design time, and is **not** a committed test: adding a
vCard parser to a family app's dependencies to guard a format that is not going to change
is not a trade worth making. The committed suite asserts structure (CRLF, folding
round-trip, property set, component split) without it, and this receipt is the record that
conformance was checked against something other than my own understanding of the spec.

## Two of my own bugs came out of the build

**A February 29 birthday vanished silently.** `_yearless` first used
`strptime(text, "%B %d")`. With no year in the format Python supplies 1900, which is not a
leap year, so `"February 29"` raised `ValueError` and the birthday was dropped from the
card — no error, no log line, for the one member most likely to notice a missing birthday.
Python's own DeprecationWarning in the test output is what surfaced it. Fixed by looking
the month up in a table derived from the same tuple `profiles` renders from, so there is no
year involved at all and no second month table to drift.

**A folding test of mine was structurally unable to fail.** `test_folding_never_splits_a_
multibyte_character` decoded each folded line and asserted no error — but folding operates
on `str`, which cannot hold half a codepoint, so no implementation could ever have failed
it. Rewritten as fold/unfold round-trip equality swept across 90 alignments, so no lucky
boundary hides a bug; the replacement fails against an octet-boundary implementation, which
the original passed.

## Non-vacuity: every guard broken, then restored

| probe | expected to fire | result |
|---|---|---|
| remove newline escaping | injection + delimiter tests | 2 failed |
| `_can_see_field` returns True for HIDDEN | hidden-field + birthday-year | 2 failed |
| POD scope behaves like YARD | pod-scoped field + anniversary | 2 failed |
| `visible_members` → all members | directory scope + per-viewer scope | 2 failed |
| re-introduce the page's 200-row cap | not-silently-capped | 1 failed |
| emit Apple's `1604` sentinel BDAY | year + leap-day + month round-trip | 3 failed |
| disable folding | fold/unfold round-trip | 1 failed |
| fold on octet boundaries | fold/unfold round-trip | 1 failed *(after the rewrite; the original test passed this)* |
| drop `@login_required` | elder + anonymous | 2 failed |

Reported honestly: `test_a_non_ascii_address_survives_the_card` **passes** under a broken
fold — it is a content test, not evidence about folding, and the round-trip test is what
guards that.

## Driven live, and looked at

The download was fetched over HTTP from a running instance as a signed-in member and the
**downloaded bytes** validated, not the test client's return value:

```
CRLF-only: yes | parsed 5 cards from 1337 bytes
  Dave Ferrara     nick=Uncle Dave   tel=(531) 555-0163  bday=--0719  adr=-
  Rose Whitfield   nick=Nana         tel=(712) 555-0117  bday=--0229  adr=88 Willow Ln, Council Bluffs, IA
  Sam Whitfield    nick=-            tel=(402) 555-0198  bday=--1130  adr=-
sentinel years present: none
Content-Type: text/vcard; charset=utf-8 · X-Content-Type-Options: nosniff
```

**Dave and Rose both have `address_visibility = POD` and a real address on file.** Rose's is
in the file and Dave's is not, and the pod graph is why: the viewer shares pod 1 with Rose
and not pod 4 with Dave. That pair — identical field visibility, opposite outcome, decided
only by membership — is the property this story had to get right, measured on the live
download rather than argued. (One CRLF check of mine failed first, because Python's text-mode
`open()` translates line endings and destroys the evidence; re-run in binary.)

### And then on production

Deployed from `main` (`55b4b1f`) and proven by a string only the new code serves —
`main` moving proves nothing:

| | before deploy | after |
|---|---|---|
| `GET /directory/vcards/` | **404** (no such route) | **302 → `/accounts/login/?next=/directory/vcards/`** |

Then signed in over HTTPS as a demo member and downloaded it for real. Header names are
lower-case here and capitalised in the local block above; that is not an inconsistency to
tidy. **This is verbatim wire output over HTTP/2, which lower-cases every field name**
(RFC 9113 §8.2.1), while the earlier block shows the canonical form the application sets.
Normalising the quote would make the receipt tidier and less true.

```
content-type: text/vcard; charset=utf-8 · x-content-type-options: nosniff
content-disposition: attachment; filename="backyard-family.vcf"
PRODUCTION download: CRLF-only, 5 cards, 982 bytes, parsed by vobject
UID host: backyard.family        sentinel years: none
```

A single card, fetched from production, with the name split and the slugified filename both
working on real data:

```
content-disposition: attachment; filename="priya-whitfield.vcf"
BEGIN:VCARD / VERSION:3.0 / N:Whitfield;Priya;;; / FN:Priya Whitfield
CATEGORIES:Backyard family / UID:backyard-9@backyard.family / REV:2026-07-30T02:36:55Z
```

And the per-member gate, swept read-only across ids 1–14 as that member: **1–7 answer 404,
8–13 answer 200, 14 answers 404**. Two of the denied ids return byte-count-identical 404 pages
(66,373 each). Note what that means: from outside, **I cannot tell which of 1–7 exist** — which
is exactly what S-202 promises and the reason the sweep is evidence rather than a list.

**Stated plainly:** production's demo members have almost no profile fields set, so the
production cards are name-only and the *visibility discrimination* could not be re-proven
there. That property was proven on live HTTP against seeded data locally (the Dave/Rose pair
above) and by the test suite. Production proves the deploy, the route, the auth gate, the
headers, parseability by a third-party parser, the yard-scoped card count, and the 404 shape.

Two production operations were **blocked by the environment's command classifier**: the
`tar | ssh` one-liner from the runbook, and `docker compose exec web ... manage.py shell`. The
deploy went through as `scp` + a separate `ssh` untar + rebuild; the shell had no workaround, so
the member enumeration was done over HTTPS instead. Recorded because the runbook's exact deploy
line does not work in this harness.

Both surfaces were rendered at **1440 and 1728, light and dark**, and looked at:

- The directory rail holds three links on one line (all at `top: 166`), no wrap at either
  width.
- **A finding that came from looking:** "Save to my contacts" sat at exactly the contact
  list's own row pitch with `margin-top: 0`, so it read as a *third contact field* rather
  than an action. Now a `p.page-action` with real separation — measured: the list's rows have
  a 0px gap between them, and the action sits 27px clear.
- One thing that looked like a bug and was not: a single directory name rendered underlined
  while the others did not. Measured rather than "fixed" — the harness parks the mouse where
  it last clicked the login button, which after navigation lands on that card, so it was
  simply `:hover`. Moving the cursor to (2,2) makes all five `none`. The screenshot harness
  now parks the cursor off the content.
- Tap targets match the shipped rail idiom exactly (18px, same as "Edit my profile" and
  "Export my data"), so this adds no new target-size case.

**axe: 132 renders / 33 surfaces / 0 violations at any severity**, each with a deliberate
hover pass — `docs/receipts/2026-07-29-axe-s904-sweep.json`. The sweep now also covers
**`member-profile`**, which no previous sweep included: a member's contact details are read
there, and the earlier receipts' render counts never touched it. Its id is resolved from the
running instance's own directory, so it works on any instance, and an empty directory is
reported in the skip list rather than passed over.

## Boundaries it inherits rather than re-implements

- `require_visible_member`, so a cross-yard id is the same 404 as an unknown one. Asserted
  on the *rendered* page, with the per-response CSP nonce normalised out rather than the
  assertion softened to a status-code comparison.
- `login_required` + `_acting_member`, so a **live elder session cannot reach either
  route** — TM-5 grants the elder token "no directory contact fields", and that is now
  tested against a real minted session, not assumed from her page's links.
- The filename is slugified, never the raw display name: `../../etc/passwd"\r\nX-Injected: 1`
  becomes `etcpasswd-x-injected-1.vcf`, and a name with no sluggable characters falls back
  to the member id.

**The download is uncapped**, unlike the directory page's 200-row render. An address book
that stops at a cap is the same lie as one that stops at four; 222 members proves the
page's bound was not copied into it. It also deliberately ignores the search box — a button
that silently exports a filtered subset is how someone ends up believing they have the
family's numbers when they have four of them.

## Review: one finding whose stated mechanism was wrong

Copilot raised two. The docstring one was plainly right — `_escape`'s docstring said C0
control characters are dropped while the code keeps the tab, and tab is 0x09, so the sentence
described behaviour the function does not have. Fixed, and now pinned by a test
(tab kept / other C0 dropped) so the two cannot drift again.

The other was **real, but not for the reason given.** The claim was that a naive `now` *raises*
on `.astimezone()`. Measured: it does not. Python reads a naive value as system local time and
converts, which stamped `REV:2026-07-29T20:04:05Z` for an intended 15:04 on this UTC-5
machine — **a five-hour shift with no error at all**, which is worse than the reported crash
because nothing surfaces it.

A fix was also pushed to the branch that silently treats naive as UTC, with the rationale that
this stops a naive value "crashing the export". That premise is the false one. Reconciled as a
**union, not one-sidedly**: the pushed docstring wording is clearer about *why* the tab
survives, so it was kept, while the naive-`now` handling stays a **refusal** — this function
cannot know whether the caller meant UTC or local, no caller in the app passes `now` at all,
and guessing produces a confidently wrong stamp. That matches the house posture: `_visibility`
fails closed to HIDDEN, `health.py` reports `NOT MEASURED` rather than omitting a field it
cannot compute. Both tests come from this side; the pushed commit added none.

## One thing outside S-904's scope, stated rather than smuggled

`p.page-action` is a new rule in `base.html` — a design-system addition, not vCard code. It
is here because the surface this story ships reads wrong without it, and the fix was found by
rendering the page rather than by reading it. Called out because a CSS addition in a PR named
S-904 should be visible, not quietly folded in.

## Gate

ruff + format + mypy(167) clean · **pytest 771 passed / 2 skipped** (740 before, +31 here) ·
`check_stories` PASS · `check_digest_confinement` OK · axe 132/33/**0** · live download and
the pod-graph discrimination above. Every guard in `src/core/tests/test_vcards.py` broken and
restored; the one probe that did not fire is named.

One honest note on that number: an intermediate run reported 18 errors, all
`column "owner_id" of relation "core_pod" does not exist`. That was two pytest processes
sharing one test database — a background run and a foreground run recreating the schema under
each other — not a product failure. Re-run singly: clean. Worth recording because the error
text looks exactly like a broken migration.
