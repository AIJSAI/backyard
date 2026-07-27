# Founder manual QA — criterion 4

This is the gate. Nothing goes to the pod of six until you have walked it yourself and
signed the block at the bottom.

**Budget about 90 minutes**, and do it on a phone for the parts marked 📱. Most of what
went wrong this month was invisible on a laptop.

---

## Before you start: the one thing that will lie to you

**Register the Resend `email.received` webhook first**, pointing at
`https://backyard.family/anymail/resend/inbound/` with the production
`RESEND_INBOUND_SECRET`.

Without it, reply-by-email fails *silently*: SES accepts the message with a 250, the sender
gets no bounce, and nothing reaches the app. If you test replies before registering it, you
will conclude the feature works when it did nothing. There is no way to tell from the
outside — that is the whole problem.

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

| # | Do | Wrong looks like |
|---|----|------------------|
| A1 | From the admin roster, mint an elder link for a test member. Print or open the QR. | No link, or a page that errors |
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
| F1 | Subscribe a real address to the digest. Confirm via the email. | No mail, or the link fails |
| F2 | Send yourself a digest. Does it arrive, and is it readable on a phone? | Spam folder, broken layout |
| F3 | Click through to the web version **while logged out.** Can you see photographs? | Captions with no pictures |
| F4 | **Reply to the digest by email.** Does it land as a comment? | Nothing arrives — and no bounce |
| F5 | Turn on reply notifications, have someone reply, check the mail. | No mail |
| F6 | Click the unsubscribe link. Does *all* mail stop, including reply nudges? | Nudges keep coming |

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
