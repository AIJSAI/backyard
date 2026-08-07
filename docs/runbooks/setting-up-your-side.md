# Setting up your side of the family

For whoever is bringing people in. It is short on purpose. If a step is not here, you do not
have to do it.

**The one rule that matters:** post something to your whole side of the family *before* you
hand anyone a grandparent link. See "A grandparent" below for why.

---

## Before anything else: getting in

1. **Open the instance** in a browser: `https://backyard.family`
   *(If you are reading a copy of this for a different family's instance, use theirs.)*
2. **Sign in** with the account you were given. If you are already signed in you will land
   on the feed.
3. **Look at the top of the page for a link called `Members`.** Everything below happens
   there.

**If you cannot see `Members`, stop — you are not set up yet.** That link only appears for
people who have been made a **yard admin** (or an instance admin), and without it every
step below leads to a page that refuses you. Ask whoever runs the server to make you an
admin for your side of the family, then sign out and back in.

That is the whole prerequisite. You do not need a terminal, a server login, or anything
installed.

---

## What you are actually doing

There are two kinds of person to set up, and they are genuinely different:

| | **Household** | **Grandparent** |
|---|---|---|
| Who | Anyone with a phone who can manage a password | Someone who does not use apps |
| They get | A join link — they pick a name and password | A link that just *opens*. No login, ever. |
| Where they land | The family feed | A large-text page: read, and one tap to send love |
| Reusable | Yes, up to 8 people from one link, for 7 days | No — one link, one person |

Both links are **one-time-view**: the page shows the link once and never again. Copy it
before you leave the page. If you lose one, mint a new one — that is normal and costs
nothing.

---

## A household (a couple, a family, a sibling and their kids)

1. **`Members` → `Invite a household`.**
2. Name it the way the family would say it — "The Reeds", "Aunt Jo's" — and pick which side
   of the family it belongs to.
3. You get a link, a **Copy** button, a **Share** button, and a QR code. The page tells you
   how many people it works for and the date it stops working.
4. Send it however you normally reach them. Text is fine. **One link covers the whole
   household** — send it to one person and let them pass it around, or send it to each of
   them; either works.

**What they see:** a page saying they were invited, a few boxes (their name, a username, a
password, and an email address if they want one), and then they are in the feed. Nothing
else. No setup wizard.

> The email box is optional but worth encouraging: it is the only way to reset a forgotten
> password without asking an admin.

**What to tell them:** *"Tap the link, pick the name you want the family to see, make a
password. That's it — you'll be looking at the family's photos."*

When someone joins, a quiet line appears in that household's feed so the family knows they
arrived. Nobody gets notified; it is just there.

---

## A grandparent

1. **`Members` → `Add a grandparent`.**
2. Their name, what the family calls them (Nana, Papa — optional), name their household,
   pick the side of the family.
3. You get their link and a QR code.

**Hand this one over in person or by a private message.** Anyone holding that link can read
and react as them — that is the trade that buys "no password, ever". Do not put it in a
group chat.

**What they see:** *"Hello, Nana"*, the family's recent posts with the photos, the replies
underneath, one big **Send love** button, and a **Bigger text** button. Nothing to install.
Nothing to log into. Nothing that can take them somewhere else — that is deliberate: there
is no way for them to get lost, and no way for a stray link to lead them off the page.

**Do this first, though.** Their page shows the posts their household can see. If nobody has
posted to that side of the family yet, they will open the link and read *"Nothing new right
now."* You cannot preview it for them, so **post a photo to the whole side of the family
before you send the link.**

Practical option: print the page. The QR is on it. Some people find "point your camera at
this" easier than a text message, and the paper is a backup when the message scrolls away.

---

## Things people ask

**"Do I need the app?"** There is no app. It is a web page. On a phone you can add it to the
home screen if you want it to feel like one.

**"Who can see what I post?"** Your household, unless you tick a whole side of the family
when you post. Grandparents see what their household sees.

**"Can I see the other side of the family?"** No. The two sides never see each other. A
household that belongs to both sides sees both, and neither side sees the other through
them.

**"Is it going to send me things?"** No. Nothing is pushed at anyone by default. The only
thing anyone can turn on is a nudge when someone replies to their own post — under
`Settings` → `Notifications`. There is also a weekly email digest, off until you switch it
on, under `Settings`.

---

## If something goes wrong

- **A link stopped working.** They expire after 7 days, and household links run out after 8
  people. Mint a new one — **`Members` → `Outstanding invites`** shows what is still live
  and lets you revoke anything you would rather kill.
- **Someone joined with the wrong name.** They can fix it themselves: **`Settings`** in the
  top nav, then change the name field and save. If they cannot, an admin can fix it from
  **`Members` → `Edit profile`** on their row.
- **You handed a grandparent link to the wrong person.** Mint a new one for that grandparent
  immediately — **`Members` → their row → `Elder link`**. Minting a new one kills the old
  one straight away.
- **Somebody forgot their password and gave no email address.** Ask whoever runs the server;
  there is a recovery path, but it needs them.
- **Anything else.** Ask whoever runs the server. That is a relative, not a support desk,
  and they can fix it.

---

<sub>Every navigation instruction in this document names a link that exists in the product.
That was not true until 2026-08-06: `Members` was not in the nav at all, so a delegate
reading this had nothing to click and no URL to fall back on. `test_member_settings_are_reachable.py`
now walks the product by following links and fails the build if any page becomes
unreachable, which is what keeps this document honest.</sub>
