# S-905 — the arrival card, and what walking the onboarding found

Pulled forward from post-v1 because of what a **delegate walkthrough** turned up. The
founder is about to hand admin controls to two relatives who will onboard everyone else,
and asked the right question: *is it as easy for them as it can be, and can they explain
it to other people?*

So the whole delegate journey was driven end to end on a clean instance — make a
delegate, invite a household, open the link cold on a phone, join, then set up a
grandparent and open **their** link cold. Not "do the tests pass"; the suite already
answered that.

## What already works, and works well

- The invite page states the seat count and the expiry in words a person reads: *"It
  works for up to 8 people and expires Aug 5, 2026."*
- Both hand-over surfaces offer Copy, Share and a printable QR, and say the link appears
  only once.
- The elder hand-over page explains the security trade in plain language rather than
  hiding it: *"Whoever holds the link can read and react as them, so hand it over in
  person or by a private message."*
- The join page is three fields and lands the newcomer directly in the feed.
- A grandparent's page works cold on a phone: posts, photos, replies, Send love, Bigger
  text.

## The gap this story closes

A household is invited, relatives join over a week — and **nothing anywhere says any of
them arrived**. The people already in the pod never learn that a cousin is now reachable.
The joiner is a row in an admin roster nobody visits.

`posting.announce_arrival` posts one quiet line into the pod the member just joined.

**Inside the join transaction, on purpose.** Its only realistic failure is a database
error, which would fail the join anyway — and a card written outside the transaction is a
card that can silently not happen, which is the exact class of defect this project keeps
finding. Either the member exists with an arrival card, or neither exists.

**Without a fanfare**, per the acceptance:

- **Pod-scoped.** `audience_yards` is empty. A yard-wide *"X joined"* for every arrival is
  a broadcast, and this product does not have those.
- **No notification.** It is a post, not a comment; S-305's opt-in only fires on replies
  to your own post.
- **No name in the body.** The byline already says who this is — *"Priya Whitfield joined"*
  under a byline reading *"Priya Whitfield"* reads as a bug. The body is `Just joined.`

## Tests, and proof they bite

`src/core/tests/test_arrival_card.py`, five tests, asserted on the **acceptance text**
rather than the implementation. The two negatives are the ones that matter, because a
card that quietly went yard-wide would look identical on the joiner's own feed:

| probe | result |
|---|---|
| force the card yard-wide | `test_the_card_is_pod_scoped_and_never_a_yard_wide_broadcast` **fails** |
| remove the `announce_arrival` call | **three** tests fail |
| restored | 5 passed |

Visibility is asserted through `scoping.visible_posts` — the app's one audience query —
not by reading the model, and includes a household **on the same side of the family but
not in the pod**, which must not see the card.

## Live repro — a real browser against a real server

Tests pass; this project's rule is that a live run of the actual path beats them when
they disagree. Driven through Chromium against `runserver` with the demo family seeded:

| | |
|---|---|
| invite a household as the admin, join cold on a 390px phone | lands on `/feed/` |
| the joiner sees their own card | **yes** |
| a SECOND person joins the same household and sees the first one's arrival | **yes** |
| the other side of the family (`dave`) sees it | **no** — which is the point |

Screenshot: `11-second-joiner-sees-first.png` — *"Second Reed · Just joined."* above
*"Cousin Reed · Just joined."* above the family's photos.

**Two things the live render surfaced that the tests did not, both left as they are:**

- The card carries **Edit** for its author, because it is a normal post. Within the
  15-minute `EDIT_WINDOW` a newcomer can turn *"Just joined."* into *"Just joined — I'm
  Priya's cousin from Denver."* That is the "profile card" half of the story arriving for
  free, so it stays.
- Arrival cards **do** appear in the weekly digest, since the digest renders post bodies.
  *"Cousin Reed — Just joined."* in a family's weekly email is information, not noise. A
  week with ten arrivals will read repetitively; that is a real consequence, recorded
  here rather than discovered later.

## Found on the walkthrough, fixed here as documentation

**An elder's first impression depends on posting order, and nothing enforces it.** Her
page shows the posts her household can see. Set her up on a side where nobody has posted
and she opens her link to *"Nothing new right now. Your family's posts will appear
here."* — an honest empty state and a terrible first moment. **The person handing over
the link cannot preview it**; there is no "view as". Verified by creating a new side,
adding an elder to it, and opening her link cold.

Fixed where it will actually be read: a warning at the top of section A of
`founder-qa.md`, and the lead rule in the new delegate hand-out.

**`docs/runbooks/setting-up-your-side.md`** is that hand-out — one page for whoever is
bringing people in, covering the household-vs-grandparent split, what to send, the exact
words to say, and what breaks. Every factual claim in it was checked against the code
(8 seats and the 7-day TTL in `invites.py`, `mint`'s `update_or_create` really replacing
a prior elder token, `notify_on_reply` defaulting to `False`), not written from memory.

## Recorded, not built

Two gaps the walkthrough found are proposed as stories rather than implemented, per
CONTRIBUTING's "if your change has no story, propose the story first":

- **S-906** — a newcomer lands on `/feed/` with a composer and other people's posts and
  no orientation at all. Distinct from this story: S-905 tells the *family* someone
  arrived; S-906 is about what the *arriving person* sees.
- **S-907** — the roster offers "Pod owner / Yard admin / Instance admin" with no prose
  anywhere saying what any of them can do. A delegate has to be told out of band.

## S-706 is superseded, by founder decision

*"No to the passed away thing... it can just be a deactivation from admin controls. That
is not sensitive at all."* The shipped S-702 removal already does the mechanical half —
choosing "keep their posts, still attributed to them" runs the full revocation inventory,
stops the digest, and preserves content and attribution. What S-706 added beyond that was
remembrance framing and a birthday freeze, and that ceremony is ruled out.

`check_stories.py` gained a `superseded` status to record this rather than delete the
story, carrying the **same evidence burden as `passing`** — a claim that something need
not be built has to say why. The guard's own bad-fixture self-test was widened to cover
the new status, because widening `VALID_STATUS` without widening the fixture is how a gate
quietly stops enforcing.

## Gate

ruff + format + mypy(152) clean · **pytest 662 passed / 2 skipped** ·
`check_stories` PASS · `check_digest_confinement` OK · live repro below.
