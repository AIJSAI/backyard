# Setting Up Your Side

For the Admin who brings people in. The short version is a page in the product:
**`Members` → `Admin Guide`**. Read that on your phone. Read this when you want the detail.

**The one rule that matters:** post something to your whole side of the family before you
hand anyone a no-login link. "Add A Grandparent" below says why.

---

## Before You Start

1. Open Backyard in a browser, at the address you were given.
2. Sign in with the account you were given.
3. Look at the top of the page for **`Members`**. Everything below happens there.

**If `Members` is not there, stop.** That link appears only for an Admin or a Family
Admin, and without it every step below leads to a page that refuses you. Ask the Family
Admin to make you an Admin, then sign out and sign in again.

You do not need a terminal, a server login, or anything installed.

## What You Are Setting Up

Two kinds of person, and they are set up differently.

| | Household | Grandparent |
|---|---|---|
| Who | Anyone with a phone who can manage a password | Someone who does not use apps |
| They get | A join link. They choose a name and a password | A link that opens the page. No password, ever |
| Where they land | Your Backyard, with everyone else | A large-text page: read the posts, send love with one tap |
| Reusable | Yes. Up to 8 people, for 7 days | No. One link, one person |

Both links are shown once and never again. Copy the link before you leave the page. If you
lose one, make another.

## Invite A Household

1. **`Members` → `Invite A Household`**.
2. Name the household the way everyone says it, "The Reeds" or "Aunt Jo's", and choose the
   side it joins.
3. The page shows the link, a **Copy Link** button, a **Share** button and a QR code. It
   also says how many people the link works for and the date it stops working.
4. Send it however you normally reach them. One link covers the whole household, so you can
   send it to one person and let them pass it on.

They choose a name, a username and a password, and an email address if they want one. Then
they are in. There is no setup to walk them through.

An email address is optional and worth asking for: it is the only way to reset a forgotten
password without an admin.

When someone joins, a card appears in that household's feed so the people already there know
they arrived. Nobody is notified.

## Add A Grandparent

**Post something to their side first.** Their page shows the posts their household can see,
so with nothing posted they open the link to an empty page. You cannot preview it for them.

1. **`Members` → `Add A Grandparent`**.
2. Enter their name, what everyone calls them (optional), the name of their household, and
   the side of the family.
3. The page shows their link and a QR code.

**Hand this link over in person or in a private message.** Anyone holding it can read the
posts and send love as that person. That is the trade for no password, ever. Do not put it in
a group chat.

What they see: the recent posts their household can see, the replies underneath, a **Send
Love** button on each post, and a **Bigger Text** button. Nothing to install, nothing to sign
in to, and no link that leads off the page.

You can print the page. The QR code is on it, which some people find easier than a text
message.

## Questions People Ask

**Do I need the app?** There is no app. Backyard is a web page. On a phone you can add it to
the home screen.

**Who can see what I post?** Posts are shared with your household. To reach more people,
choose a side of the family or a group when posting. A grandparent sees what their household
sees.

**Can somebody outside my side of the family see my posts?** No. A side of the family is
private to itself. A household that belongs to more than one side sees each of them, and
nothing crosses between sides through that household.

**Will it email me?** Only what a member turns on. Under **`Settings` → `Notifications`** they
can ask for an email when someone replies to their post.
Under **`Settings` → `Email Updates`** they can choose Weekly or Monthly. A week with nothing
posted sends nothing.

## If Something Goes Wrong

**A link stopped working.** Household links expire after 7 days and run out after 8 people.
**`Members` → `Invites`** shows which links are still live, makes another, and revokes one
you no longer want.

**Someone joined with the wrong name.** They can change it themselves under **`Settings`**. To
do it for them, open **`Members`**, tap **Manage** on their row, then **Edit Profile**. That
works for the members you manage. Where the control is not there, the row on **`Members`**
says so and names who can.

That page shows their name, their nickname and their two dates, and nothing else. Their phone
number, email address and home address are not shown to you and you cannot change them. Each
of those has its own visibility setting, and it belongs to the person it is about.

**A grandparent's link went to the wrong person.** Make a new one immediately: open
**`Members`**, tap **Manage** on their row, then **No-Login Link**. The old link stops working
at once.

**No-Login Link** appears only for someone whose households you are in yourself. The link is a
working credential for everything that person can see, so making one for a household you are
not in would hand you its contents. If the control is not there for someone, ask the Family
Admin.

**Somebody forgot their password and has no email address.** Open **`Members`**, tap
**Manage** on their row, then **Sign-In Link**. It makes a one-time link you can text to them
or read out over the phone, and they set a new password with it.

Make sure you are really talking to them first. Call, or text the number you already have.
Whoever holds the link can set that password. It works once, it stops working after two days,
and making a new one cancels any earlier one. When they use it, they are signed out
everywhere else.

You see this control for the members you manage who have a password. It is not there for a
grandparent on a No-Login Link, because there is no password to reset. Anyone else is the
Family Admin's to recover, and the row on **`Members`** says so. An admin's own recovery
needs the server, by design.

Worth doing before it happens: ask everyone on your side to add an email address under
**`Settings` → `Your Sign-In Email`**, so they can reset their own password.

**Anything else.** Ask the Family Admin.

---

<sub>Every navigation instruction in this document names a control that exists in the product.
That was not true until 2026-08-06: `Members` was not in the nav at all, so a delegate reading
this had nothing to click and no URL to fall back on. `test_member_settings_are_reachable.py`
walks the product by following links and fails the build if a page becomes unreachable, which
is what keeps this document honest.</sub>
