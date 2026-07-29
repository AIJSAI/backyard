# The digest's reply action opens the app — and stops printing a bearer credential

**Founder decision, 2026-07-29:** *"I wouldn't put too much energy into the reply by email
thing... it would be better if it just opened the app to where they reply when they click
reply by email."*

That turned out to be a security improvement as well as a simpler product, and it retired
one story rather than adding one.

## What the email did before

Every post block printed the per-post reply **address**:

> Reply to this post by email: `reply-<capability>@mail.backyard.family`

Two things were true about that:

1. **The address is a bearer credential.** Threat model **T-EMAIL-2**: *"A forwarded digest
   leaks reply capabilities, so a stranger or excluded relative posts as the elder."* Its
   recorded residual risk: *"Within the validity window a forwarded-digest recipient can
   forge comments on that digest's posts."* Printing it in every digest body is precisely
   how it travelled — into every forward, every quote, every reply-all.
2. **The natural gesture never worked anyway.** There is **no `Reply-To` header** on the
   digest, so hitting "Reply" in a mail client replies to the from-address, not to the
   post. The only route in was clicking the `mailto:`. Adding a `Reply-To` was considered
   and **rejected**: it would spread the same bearer credential further, not less.

## What it does now

> **Reply in Backyard** — your reply goes to everyone who can see this post, and you can
> add photos.

A link to `{BASE_URL}/posts/<id>/#reply`. It **carries no capability**: it lands on the
login wall and you reply as yourself. A forwarded digest now leaks nothing.

It also lands somewhere better than an email composer. `#reply` anchors the reply box
directly, and since S-404 that box takes photographs — so the wedding case ("everyone put
your photos under this") is reachable in one tap from the inbox, which an emailed reply
could never do without attachment ingest.

## What this changed about a shipped story

This retires the **user-facing half of S-502**: no member can now reach reply-by-email,
because nothing publishes an address. Recorded rather than slipped in:

- The **inbound pipeline is untouched** and still proven end to end. The twelve tests in
  `test_inbound.py` mint an address directly and drive the full pipeline; none of them ever
  scraped the email body, so the machinery's proof never depended on the printed
  affordance.
- `test_sent_digest_carries_working_reply_addresses` **did** depend on it — it scraped the
  address out of the sent body. Renamed to
  `test_sent_digest_offers_the_app_and_publishes_no_bearer_address` and retargeted to the
  new contract, asserting **both** halves: the app link is present, and no address on the
  sending domain appears in the body. Dropping the address without adding the link would
  leave the digest with no way to reply; adding the link without dropping the address would
  leave the credential in every forward.

**S-503 (email-photo-to-pod) is superseded** by the same decision. It is email-attachment
ingest — the same untrusted-input path — and the need it served is met by S-404 photos on a
reply, reached through the app link.

## Two vacuity problems found and fixed on the way

**The photo-count guard was too blunt.** `test_digest_photo_count_excludes_a_rehosted_link_preview_image`
asserted `"photo" not in built.text`. The new reply copy legitimately says *"you can add
photos"*, which tripped a security-review (MEDIUM-1) guard on unrelated prose while saying
nothing sharper about the count it exists to check. Tightened to the count phrasing
(`(N photo`), and given a **non-vacuity half** that builds a digest for a post which really
does carry a photo and asserts the count appears.

**My own new guard was vacuous.** I added `reply_url` to `_family_urls_of` so the
on-origin link check would cover it — and removing it again **failed no test at all**. A
reply link is the single thing in a digest a member is most likely to click, so it is the
most valuable place in the email to inject an off-origin URL.
`test_the_gate_trips_on_an_off_origin_REPLY_url` now proves the check bites, with the
on-origin case asserted too so it is not simply rejecting every `PostBlock` it is handed.

| probe | result |
|---|---|
| put the bearer address back in the body | the new digest-send test **fails** |
| take `reply_url` out of the on-origin list | the new off-origin test **fails** (it did not, before) |

## The framing this corrected

`docs/story-map.md` justified the `v1: false` flag on five stories with *"None is required
to pass the alpha KPI."* **The founder superseded that KPI on 2026-07-22** — adoption
informs iteration and is explicitly not a gate. So "post-v1" was an inference from a retired
metric that kept being read as a decision. Struck through and re-decided per story; S-905
was built, S-706 and S-503 are superseded by founder decision, and S-904 / S-804 / S-603
carry forward as real pre-share work.

## Gate

ruff + format + mypy(158) clean · **pytest 701 passed / 2 skipped** · `check_stories` PASS ·
`check_digest_confinement` OK.
