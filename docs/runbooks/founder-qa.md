# Founder manual QA — criterion 4

This is the gate. Nothing goes to the pod of six until you have walked it yourself and
signed the block at the bottom.

**Budget about 90 minutes**, and do it on a phone for the parts marked 📱. Most of what
went wrong this month was invisible on a laptop.

---

## The demo family on the instance

`scripts/demo_seed.py` puts a small two-sided family on the box so every section below
exercises something real. It exists because QA against the bare instance gave FALSE
NEGATIVES: every elder token belonged to a member whose pods held no photographs, so
"can Nana see a photo?" answered *no* for a data reason rather than a code one — and
both logins sat on the same side of the family, so the isolation boundary could not be
crossed to test it.

**Two things about every command in this file.** First, on the live box every compose
command carries the production overlay — `-f docker-compose.yml -f docker-compose.prod.yml`
— because that overlay is what defines the real `web`, `worker` and `caddy` services
(`docker-compose.prod.yml`). Without it you are talking to a differently-configured stack.
Second, the secret is exported before `manage.py` runs: the entrypoint generates
`DJANGO_SECRET_KEY` at boot and exports it for gunicorn only, so a fresh `exec` gets the
container's *configured* environment, which has never held it, and a bare
`exec web python manage.py …` dies with `DJANGO_SECRET_KEY is empty` before argparse is
reached. Both are folded into every command below; they are long, and they are the form
that works.

    # seed
    docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web sh -c \
      'export DJANGO_SECRET_KEY=$(cat /data/secret_key); python manage.py shell' \
      < scripts/demo_seed.py

    # wipe, before the instance goes to anyone real. READ THE COUNTS FIRST.
    docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web sh -c \
      'export DJANGO_SECRET_KEY=$(cat /data/secret_key); python manage.py wipe_demo_data --dry-run'

    docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web sh -c \
      'export DJANGO_SECRET_KEY=$(cat /data/secret_key); python manage.py wipe_demo_data --yes'

The wipe also refuses while a real person's post or reply sits inside a fixture household —
by design, and it is the refusal that saved a relative's content once already. If that is
what stops you, move the real content or the real person out of the demo pod first rather
than reaching for a shell.

### If the wipe says nothing is marked

That is correct, and it is the case on **this instance**: the live box was seeded before
`seeded_by` existed, so its demo family carries an empty marker — the same value every real
person carries, which is exactly why the wipe will not touch it.

Do not delete those rows by hand. A one-off `.delete()` typed at a shell against production
is how `Pod.objects.all().delete()` came to be written in the first place, and it skips every
refusal this command has: the real-content check, the stranding check, media file purging,
session deletion, and pod-owner succession.

**Mark first, then wipe.** You name YARDS; pods and members are selected by containment — a
pod only if every yard it is in was named, a member only if every pod they are in was marked.
So a bridging household that reaches a real side is left alone, and so is a relative who
joined a demo pod during QA but has their own household.

First list the yards, because two different seed scripts have run against this project and
they use different slugs — `moms-side` / `dads-side` from `scripts/demo_seed.py`, and
`whitfield-side` / `ferreira-nakamura-side` from `docs/design/tools/seed_demo.py`. Read what
is actually on YOUR box rather than trusting either list:

    docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web sh -c \
      'export DJANGO_SECRET_KEY=$(cat /data/secret_key); python manage.py shell -c "
    from core.models import Yard
    for y in Yard.objects.all():
        print(y.slug, y.name, y.pods.count(), \"pod(s)\")"'

The founder's own yard (`home`) is created without a marker on purpose and must not be
named here — it is the household you keep.

    # what would be marked, and what is deliberately spared. Changes nothing.
    docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web sh -c \
      'export DJANGO_SECRET_KEY=$(cat /data/secret_key); python manage.py mark_demo_data --yard <slug> --dry-run'

    docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web sh -c \
      'export DJANGO_SECRET_KEY=$(cat /data/secret_key); python manage.py mark_demo_data --yard <slug> --yes'

**Read the "Deliberately NOT marked" list.** It is printed on every run, and it is where you
find out that the household you meant to remove reaches somebody real. A count would hide
that; the names do not.

> **The trap: an EMPTY spared list is the alarm, not the all-clear.** Selection is by
> containment — a member is marked only if every pod they are in was marked
> (`core/demo_marking._select`). On an instance seeded before the real family existed, the
> founder sits in a demo household and *nothing else*, so marking the demo sides marks the
> founder too and prints no "Deliberately NOT marked" section at all. That is the shape of
> the `BACKYARD_DEMO_WIPE` disaster again, one layer up.
>
> The order that avoids it, and the one actually walked: create the real sides and the real
> households in the product **first**, use **Members → Change household** to move the founder
> onto a real household on each real side, and only then mark. The dry run must name the
> founder under "Deliberately NOT marked" before you type `--yes`. If it does not, stop:
> marking is reversible (`--undo --yes`), and the wipe that follows is not.

### If the wipe names a post written by someone real

Ask its author to delete it from the feed (or take it down yourself). That is enough: a post
or reply that has already been deleted does not block, because its photographs were purged
when it was deleted, no reader can see it, and nothing in the product can bring it back. Its
TEXT does stay in the database until the wipe runs, so take the backup first if anybody might
want those words later. The dry run counts those rows under
`already-deleted posts and replies by real people`. A LIVE post or reply by a real person
always stops the command, and so does a deleted one that somehow still carries a photograph.

### If a removed relative is blocking the wipe: `--include-departed`

Somebody removed from a fixture household keeps their Member row and loses every
membership, so containment cannot reach them while their posts sit in a household you are
marking — and `wipe_demo_data` then refuses forever on "a post written by someone real".
`mark_demo_data --include-departed` also marks anyone who is in no household or group, wrote
at least one post or reply **inside** the households being marked, has nothing at all
anywhere else, and has no supervised child staying behind. It deletes their Member row **and
their sign-in account**.

**`wipe_demo_data --dry-run` prints counts and never names anybody, so the output of
`mark_demo_data` is the only place the names of departed people ever appear.** And
`--include-departed --yes` lists and writes in the same breath, so run it with `--dry-run`
first and read every name under "Already removed, wrote only inside these sides…" against
the roster before you type `--yes`. Marking is reversible with `--undo --yes`; the wipe is
not.

Then run `wipe_demo_data --dry-run` and read the counts, exactly as above. Marking is
reversible until you do:

    docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web sh -c \
      'export DJANGO_SECRET_KEY=$(cat /data/secret_key); python manage.py mark_demo_data --undo --yes'

The wipe is not reversible. Take a backup first — `docs/runbooks/backup-restore.md` — and
read what a restore does to elder links and to members removed since the backup before you
rely on having one.

**The wipe used to be `BACKYARD_DEMO_WIPE=1`, and it was not scoped.** It ran
`Pod.objects.all().delete()` — every pod on the instance, and by cascade every post,
comment, photograph, reaction, invite and membership. Measured against a database holding
one real family beside the fixture one: pods 2→0, members 4→0, posts 2→0, comments 2→0.
The real family did not survive, and neither did the real elder. It also cascaded the
founder's own pod membership, leaving him in zero pods and therefore zero yards — no feed,
no directory, and no way back that did not involve a shell.

Everything the seed creates is now stamped `seeded_by="demo"`, and the command touches
nothing else. It refuses without `--yes`, and it refuses outright if the deletion would
leave any surviving member in no pod at all.

Seeded logins (`priya`, `sam`, `dave`) share one throwaway password. **It is generated on
each run and printed as the last line — `DEMO_PASSWORD=…` — and that is the only copy.**
Keep the seed output in front of you, or re-run the seed to mint a new one. Your own account
keeps the password it already had. `sam` and `dave` sit on OPPOSITE sides, and that pair is
what makes section D real. The elder token prints on the same run.

It used to be a fixed password written into the script, which meant it was also written into
the **public** repository — and it worked, that minute, on the live instance. Anyone reading
the repo could sign in. Fixed, and guarded by
`src/core/tests/test_no_hardcoded_demo_credentials.py` so it cannot come back.

**Wipe before the first invite anyway.** Disposable accounts on a real instance are still
accounts on a real instance.

> If this instance was seeded before the marker existed, its fixture rows carry no marker
> and `wipe_demo_data` will say so and delete nothing. That is the safe direction — take a
> backup and remove them deliberately, or re-run the seed (which now clears only its own
> previous output) so they are marked.

## Before you start: the one thing that will lie to you

**The Resend `email.received` webhook must exist before any inbound mail is worth
believing.** Without it, inbound mail fails *silently*: the mail server accepts the message
with a 250, the sender gets no bounce, and nothing reaches the app. Test it before it is
registered and you will conclude the feature works when it did nothing. There is no way to
tell from the outside — that is the whole problem. (Read section F's note first: the family
email publishes no reply address today, so there is no emailed-reply step to walk. This
still matters, because the route is live and quarantines what it refuses.)

**On this instance it is already registered** (endpoint `/anymail/resend/inbound/`, event
`email.received`, enabled; the sending domain is verified, and a real message measured in a
real inbox passed SPF, DKIM and DMARC). Nothing in this repository can tell you that — the
route exists and is mounted whenever `RESEND_INBOUND_SECRET` is set
(`src/config/urls.py::_inbound_urlpatterns`), and whether the provider is pointing at it is
provider-side state. So before F1, confirm it in the Resend dashboard rather than trusting
this paragraph, which is a record of one measurement on one day.

Two more facts about that route, because they change what "wrong" looks like in section F:
a reply is attributed from the capability Resend reports in `data.received_for` and never
from the sender-written `To:` header, so a multi-recipient delivery is refused rather than
resolved to its first address; and a refused message is not lost — it lands on
**Members → "Replies we couldn't post"** with the reason.

---

## How to read this

Each step says **what to do** and **what wrong looks like**. The "wrong" column is not
hypothetical: every one of them was a real defect in this codebase within the last week, so
these are the places to be suspicious rather than generous.

Write down anything that feels off even if it passes. Your instinct about whether this
feels like a calm family product is the part no test can cover, and it is the actual
question.

---

## A. The elder path — do this first, and do it on a phone 📱

This is the product's central bet and the part that was most broken.

> **Order matters, and nothing in the product enforces it.** An elder's page shows the
> posts visible to her household — so if you set her up on a side of the family where
> nobody has posted yet, she opens her link and reads *"Nothing new right now. Your
> family's posts will appear here."* That is an honest empty state and a terrible first
> impression, and **the person handing over the link cannot preview what she will see**;
> there is no "view as". Verified 2026-07-29 by creating a new side, adding an elder to
> it, and opening her link cold.
>
> So: **post something to the whole side of the family FIRST, then hand out the elder
> links.** One photo is enough. Tell whoever else is setting up grandparents the same
> thing — it is the difference between "look, there's the family" and a blank page.

| # | Do | Wrong looks like |
|---|----|------------------|
| A1 | From the admin roster, use **No-login link** on a test member's row and mint one. Print or open the QR. | No link, or a page that errors |
| A2 | 📱 Open the link on a phone **you are not logged in on**. Use a private window. | Anything asking you to log in |
| A3 | **Can you see a photograph?** Scroll to a post with photos. | Captions with no pictures. *This was broken for weeks while the tracker said it worked.* |
| A4 | Can you read the replies under a post? | Replies missing entirely |
| A5 | Tap "Send love". Does it register and stay? | Nothing happens, or it resets |
| A6 | Tap "Bigger text". Is it genuinely bigger and still readable? | Layout breaks, text overlaps |
| A7 | Hold the phone at arm's length. Can your least-technical relative use this? | You find yourself explaining it |
| A8 | Try to get lost — look for any link off this page. | Any link that leaves the elder surface |

> **A8 is a live decision, not just a check.** The rule that keeps her from getting lost is
> the same rule that stops her following a link you send. The 1am-YouTube-link case —
> the thing that started this project — **does not reach her today**. Decide whether you
> want that rule relaxed. It is yours to call, and it is written down nowhere else.

## B. Posting, and the thing that ate photos

| # | Do | Wrong looks like |
|---|----|------------------|
| B1 | 📱 Post a text-only update to your own pod. | — |
| B2 | 📱 Post **with 3 photos** to your own pod. Do they all appear? | Any missing |
| B3 | 📱 Post **with photos AND a whole-yard audience.** Confirm the widen page. | **Photos missing from the posted result.** *This was the blocker: the confirm page dropped them silently.* |
| B4 | On the confirm page, check it says your photos are coming, and press Cancel once. | No mention of the photos |
| B5 | Try 25 photos at once. | A bare error page instead of a plain message saying how many did not fit |
| B6 | Post a HEIC straight off an iPhone. | Silent disappearance rather than a message |
| B7 | Post a link. Does a preview card appear within a few seconds? | Never appears |
| B8 | Post a short video. Does it show "on its way" then play? | Broken player, or nothing at all |

## C. The feed and the archive

| # | Do | Wrong looks like |
|---|----|------------------|
| C1 | Read the feed. Is it strictly newest-first with no counts or badges? | Any engagement metric |
| C2 | Scroll to the bottom. | "You are all caught up" **when there are older posts** |
| C3 | If there are older posts, use "Show older posts" and walk back. | Dead end, repeats, or missing posts |
| C4 | Go back to the top. Are the new-since-last-visit markers sane? | Everything marked read after browsing history |

## D. Family shape — the privacy core

| # | Do | Wrong looks like |
|---|----|------------------|
| D1 | As an admin, create a second yard and a household in it. | — |
| D2 | Log in as someone in yard A. Can you see anything from yard B? | **Any leakage at all — stop and tell me** |
| D3 | Open a directory profile from the other side. | Anything other than "not found" |
| D4 | Check a bridging household sees both sides, and neither side sees the other. | The two sides fusing |

## E. Profiles and the directory

| # | Do | Wrong looks like |
|---|----|------------------|
| E1 | Edit your own profile. **Change your own name.** | No name field. *That was missing until this week.* |
| E2 | Set a birthday with no year. Is your age shown anywhere? | Any age displayed |
| E3 | Set your phone to "hidden", then view yourself as another member. | The number visible anyway |
| E4 | Edit a supervised child's profile as their parent. | Refused, or it edits YOUR profile instead |

## F. Email — after the webhook is registered

| # | Do | Wrong looks like |
|---|----|------------------|
| F1 | Subscribe a real address to the Family email. Confirm via the email. | No mail, or the link fails |
| F2 | Wait for a due send. Does it arrive, and is it readable on a phone? | Spam folder, broken layout |
| F3 | Click through to the web version **while logged out.** Can you see photographs? | Captions with no pictures |
| F4 | Tap **"Reply in Backyard"** on a post block. Does it land on that thread's reply box? | A mail composer, or the feed top |
| F5 | Turn on reply notifications, have someone reply, check the mail. | No mail |
| F6 | Click the unsubscribe link. Does *all* mail stop, including reply nudges? | Nudges keep coming |

> **F2 has no "send one now" button, and F4 is not an emailed reply.**
>
> `send_digests` sends only what is **due** — the cadence has to have elapsed since
> confirmation or since the last window (`core/digest_send.send_due_digests`), and the worker
> runs it hourly. There is no command that forces one out, so budget the wait or move the
> subscription's anchor deliberately.
>
> And the family email **publishes no reply address**. It did once, and #101 removed it:
> a per-post reply address is a bearer credential, so printing it in every body forwarded the
> ability to comment as you along with the email (T-EMAIL-2). There is no `Reply-To` header
> either, so hitting Reply in a mail client answers the sending address and the message is
> refused. What each post block carries instead is a **"Reply in Backyard"** link to
> `/posts/<id>/#reply`, which carries no capability, lands on the login wall, and opens a
> reply box that takes photographs. The inbound pipeline itself is untouched and still
> live — that is what the registered webhook and "Replies we couldn't post" are for — but
> nothing hands anybody an address to use it with, so **there is no emailed-reply path to
> walk in this section today.**

## G. Removal and safety

| # | Do | Wrong looks like |
|---|----|------------------|
| G1 | Remove a test member. Are you **asked** what happens to their posts? | A bare Remove button with no question |
| G2 | Try "anonymize". Do their posts stay but their name go? | Posts vanish, or the name remains |
| G3 | Try "delete" on another test member. Are the posts and photos gone? | Content still visible |
| G4 | After removal, try their old elder link and any old session. | Either still works |

## H. Operations — do this once, properly

| # | Do | Wrong looks like |
|---|----|------------------|
| H1 | Take a backup. Confirm it refuses without a passphrase. | It writes a plaintext file quietly |
| H2 | **Fill in and print `backup-recovery-sheet.md`.** | Skipping this. There is no key escrow. |
| H3 | Restore that backup onto a throwaway machine. | It fails, or the media does not come back |
| H4 | Confirm the restore tells you it killed all the old links and sessions. | Silence |
| H5 | Install the PWA on your phone. Is the icon green, matching the app? | Navy — the rejected identity |
| H6 | Sign in and open **Settings → Account security**. A second factor is offered, never demanded. | Being forced to enrol, or no way to enrol at all |

> **H3, the two things that bite.** Get the archive *into* the container by streaming it in
> as the app user — `docker compose cp` lands it owned by the host uid with mode 600 and the
> hardened container cannot read it. And **restart `web` and `worker` after the restore**: a
> restore of an archive taken on an older schema leaves migrations pending, because the
> entrypoint is what runs `migrate`. Both commands, and the `migrate --check` that proves it,
> are in [backup-restore.md](backup-restore.md).

---

## The question the checklist cannot ask

Sit with the feed for five minutes as though you were a member, not the author.

**Would you rather your family used this than the group chat?**

If the answer is "not yet", say what is missing while the feeling is fresh. That is more
valuable than any box above, and it is the only judgement the whole project is actually
waiting on.

---

## Sign-off

Nothing is shared with anyone — not even the pod of six — until this is filled in.

    Every section above walked, on a phone where marked:   [ ]

    Blocking problems found: ________________________________

    Non-blocking things to fix later: ________________________

    The honest feeling test (above): _________________________

    I have personally QA'd Backyard v1 and it is ready to
    share with my household.

      Signed: ____________________   Date: ______________

Once signed, record it against criterion 4 in [PATH-TO-100.md](../PATH-TO-100.md) with the
date, and only then send the first invites — **pod first, one household**, not the whole
family at once.
