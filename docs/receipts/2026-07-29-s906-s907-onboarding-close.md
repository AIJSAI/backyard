# S-906 + S-907 — what the arriving person sees, and what the roles mean

Both were **found by walking a delegate's onboarding end to end**, proposed as stories on
#98 rather than built inline, and built here. Between them they close the two remaining
"a relative will have to explain this by phone" gaps in the rollout the founder is about
to run.

## S-906 — the newcomer's first screen

Someone completed the join and landed on `/feed/` with a composer, other people's posts,
and **no orientation whatsoever**. At the founder's scale — two delegates onboarding
roughly ten people — that is explained by voice ten times.

Three facts, in a quiet block above the composer, shown until dismissed and then never
again. Not a notification, not a tour, no steps:

> **You're in Dad's side.**
> Your feed shows what the households there share.
> What you post goes to **your household only**, unless you tick a whole side of the
> family when you write it.
> Nothing is ever sent to you unless you turn it on in Settings.
> **[Got it]**

**Why a stored column rather than a first-render check.** `feed_last_seen_at` already
exists and advances on the first feed render — so an orientation keyed to it would
vanish the moment a newcomer tapped Pods and came back, before they had read it.
`Member.orientation_dismissed_at` persists until they say so.

**Why the migration backfills.** A nullable column means every member alive at deploy
time reads as never-having-dismissed, so the whole family would open their feed the next
morning to a "you're in" block — correct for a newcomer, noise for someone who has been
posting for a month. `0022` stamps everyone who already exists.

**POST-only dismissal.** A GET that cleared it would let a link preview or a prefetch
destroy the one thing a newcomer has not read yet — the same class of mistake the
compose-cancel route already guards against. Idempotent, and it does not re-stamp, so
the column stays a truthful record of when they said they were oriented.

## S-907 — what the roles mean

The roster rendered `Pod owner / Yard admin / Instance admin` and **no sentence anywhere
on the page described a capability** (measured, not assumed). Whoever is handed the admin
controls had to be told out of band what picking one would do.

A closed `<details>` beside the control — it matters the first few times someone re-roles
a relative and never again — reading from `Member.ROLE_DESCRIPTIONS`, one sentence each,
in the member's own words ("side of the family", not "yard").

**Prose that describes authorization is a liability the moment the authorization moves**,
so the descriptions are bound to reality in **both** directions:

- **Behaviourally, against `permissions.py`.** Every claim is *exercised*, not asserted
  about. "Cannot remove or re-role anyone" calls `can_manage_member` with a pod owner.
  The yard admin's three-part promise is checked on all three: manages their own side,
  cannot touch an admin, cannot reach a bridging member. A source-text assertion alone
  would be defeated by the comment beside the code, which this project has already been
  bitten by.
- **Textually, against `docs/security/permission-matrix.md`**, so the human reference and
  the UI copy cannot drift apart silently. Anchored on the *rule* each sentence
  paraphrases, with whitespace collapsed first — the matrix hard-wraps at ~80 columns, so
  a raw substring search would fail on a reflow and pass on a rewrite, which is exactly
  backwards.

## Proof the guards bite

| probe | result |
|---|---|
| make a role description lie ("Can re-role anyone in their household") | `test_the_pod_owner_description_is_true…` **fails** |
| make the migration backfill match nothing | `test_the_migration_really_stamps_existing_members` **fails** |
| stop rendering the orientation | 2 tests **fail** |
| put the stray comma back | `test_the_heading_reads_as_a_sentence…` **fails** |
| all restored | 16 passed |

## Two things found by looking, that the tests did not catch

**The heading read "You're in, Dad's side."** — a stray comma before a list that is
usually one item. Caught by rendering the page and reading it, then pinned at **both**
arities, because separator logic is the kind that is right for one case and wrong for the
other.

**The mobile header stranded "Settings" on its own line, under the brand, on every
page.** Four links plus the wordmark cannot fit one 390px line, so the nav wrapped by
accident. It now wraps *on purpose*: brand on row one, four links spread evenly across
row two. Measured — one row at 390px and one at 1440, header 95px and 63px. This is the
viewport the QA script is written for, so it was worth fixing here rather than filing.

## Verification

- ruff + format + mypy(156) clean · **pytest 680 passed / 2 skipped** ·
  `check_stories` PASS · `check_digest_confinement` OK.
- **axe on the two new states, 12 renders, 0 violations** — desktop and mobile, light and
  dark, resting and with the dismiss button hovered. These states are unreachable by the
  standard sweep: it signs in as an existing member (stamped by the migration) so it
  never renders the orientation, and the role key is a closed `<details>` whose content
  is not in the accessibility tree until opened. Measuring them needed saying so.
- Live: a real join through a browser shows the orientation, dismissing it makes it stay
  gone across navigation, and an existing member never sees it.

## A note on the demo seed

Members created by `scripts/demo_seed.py` **after** a migrate are not stamped, so they
will see the orientation. That is correct — they are new members — but it means a
re-seeded QA instance shows the block to `priya`, `sam` and `dave`. On production the
demo family predates migration `0022` and is stamped.
