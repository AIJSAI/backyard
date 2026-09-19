# Backyard voice guide

Every word a person can read in this product follows this guide: page titles, headings,
buttons, links, labels, legends, hints, errors, flash messages, empty states, confirmation
pages, aria-labels, alt text, placeholders, and the subject and body of every e-mail.

It is not a style preference. The owner read the shipped copy on 2026-09-19, screen by
screen, and rejected it: "quick junk filler", "AI fluff", "really far from polished". What
follows is his critique turned into rules, with his words quoted wherever they decide
something. Three of the rules are enforced by tests, named at the bottom.

## The reader

An adult relative who has used phones, e-mail and social apps for fifteen years. "People
understand how to use computers and do this stuff."

Do not explain passwords, e-mail confirmation, or what a button does. Do not reassure. Do
not charm.

## The five rules

1. **Direct and concise. No filler.** Say the thing once, in the fewest plain words, and
   stop. "Concise no fluff." Cut any sentence that only sets a mood, reassures, or
   restates the obvious.
2. **Industry-standard phrasing.** Write what a well-made mainstream product would write.
   "An email has been sent to \<address\>." not "We have sent one email to that address.
   Tap the link in it and you are done."
3. **The product is not a person.** Never "we", "us", "our". "Who is us? That doesn't make
   sense." Not "Tell us the name your family will see" but "Enter your name." E-mails
   included.
4. **Much less "family".** "Yes it's family but let's not make it all family branded."
   The brand is **Backyard**; the feed is **Your Backyard**. Replace "your family" with
   "everyone", "members", "people here", or drop it. Allowed: the phrase "side of the
   family" where a side has to be DEFINED (at most once on a page), and a side's own name.
5. **Never the word "digest"** — and not "the Family email" either ("pick something
   better"). The feature is **Email Updates**.

## Capitalisation

**Capitalise Every Word** — his example: "Skip To Content", not "Skip to content" — in
page titles (`<title>`), headings, buttons, nav items, links that act as commands, form
labels, fieldset legends, table headers, e-mail subjects and badge text. Every word,
including "To", "A", "The", "Of". Names, e-mail addresses, URLs and code keep their own
casing.

**Sentence case**, with a full stop, in body text, hints, errors, flash and confirmation
messages, e-mail bodies and empty states.

Write the capitals in the source text. Never CSS `text-transform`: it mangles names and
e-mail addresses, and both the tests and a screen reader read the source. Text a person
typed — a household, group or side name, a post — is never re-cased.

A string used both as a heading and inside a sentence is two strings.

## Errors, hints, confirmations

- **Error** = what is wrong plus the fix, one short sentence. "Enter your name." "Choose a
  username." "That username is taken." "Name must be 100 characters or fewer."
- **Hint** = only when it prevents a real mistake. The whole password hint is "Choose a
  memorable password."
- **Confirmation** = past tense, short. "Posted." "Saved." "Post deleted." "Link created."
  "Signed out."
- Replace the framework's stock sentences wherever they leak through — password rules,
  the two-factor and passkey pages, "Note: you are already logged in as …", "Account
  Inactive". Same voice, same layout as the rest.

## Keep, tightened, never removed

Anything that prevents an irreversible or a security mistake stays, in one or two plain
sentences:

- deleting a post or a person's content is permanent and erases photos;
- taking a post down is permanent and the author is not told;
- a no-login link lets anyone holding it read and react as that person;
- a hand-over link makes its FIRST joiner the side admin;
- a link is shown once and expires;
- who can see a post before it is shared more widely.

## The rest of the rules

- **Perspective.** Address the reader as "you". An admin is named by first name or by
  role, never "us". Check every sentence for whose voice it is in.
- **No idioms or metaphors.** Not "a way back in", "chase you", "look after", "pointed at
  this address", "standing in", "tap and you are done". Say the literal thing: "reset your
  password", "manage members", "sent to this address".
- **No hedging or reassurance.** Not "if you ever", "whenever you like", "don't worry",
  "no pressure", "it's fine to", "you can always".
- **One idea per sentence, action first.** A helper is at most two short sentences. If it
  needs three, the screen is wrong.
- **Buttons are verb plus object**: "Create Link", "Save Changes", "Send Email", "Delete
  Post". The way out is always "Cancel".
- **Labels are nouns**: "Name", "Email Address", "Password", "How Often". No questions as
  labels. Placeholders only for format examples.
- **Options are short and parallel**: "Weekly", "Monthly", "Off". "Household",
  "\<Side name\>", "\<Group name\>".
- **Confirmation pages**: the heading is the question ("Delete This Post?"), the body is
  the consequence in one or two sentences, the buttons are "Delete Post" and "Cancel".
- **Empty states**: one line saying what is empty, plus the one action. Never two lines
  that contradict each other.
- **E-mails**: the subject, in Title Case, says what is inside; the body opens with the
  point; one action link; the last line says why it arrived and how to stop it. No
  greeting filler, no sign-off from a "team".
- **Punctuation**: no exclamation marks, no em dashes, no ellipses, no emoji, no "&" for
  "and". Headings, buttons and labels carry no full stop; sentences do. Straight quotes.
  "email", one word, no hyphen, everywhere a person reads it.
- **Same object, same word, every screen.** A new synonym is a defect.
- **Accessibility text** — `aria-label`, `alt`, `title` — follows every rule above.

## Calibration: the owner's own before and after

| Before (shipped) | After |
|---|---|
| Tell us the name your family will see | Enter your name. |
| This is a private place for our family. No ads, no strangers, and nothing that will chase you. | A private, ad-free network to stay connected with everyone. |
| Post when you feel like it. What you write goes to your household, unless you choose a wider group as you write it. | Posts are shared with your household. To reach more people, choose a side of the family or a group when posting. |
| Choose how often you would like it, or choose No thanks. | Select a frequency. |
| You can change this later under Settings, and every email we send has a link at the bottom that stops them. | Change this anytime in Settings. |
| Only if you feel like it. Your household will see this. | Optional. Visible to your household. |
| You look after a side of the family. | You are a Side Admin. You can add and remove members on your side. |
| Confirming means we can send you a way back in if you ever forget your password, and it starts the Family email if one has been pointed at this address. | Confirm this address to enable password reset and email updates. |
| We have sent one email to that address. Tap the link in it and you are done. Check your spam folder if it is not in your inbox. | A confirmation email has been sent to \<address\>. Check your spam folder if it does not arrive. |
| (password hint, several sentences) | Choose a memorable password. |
| Welcome to your family's Backyard … members are taken straight to … | Welcome To Backyard / A private, invite-only family network. Open your invite link to join. |
| Skip to content | Skip To Content |

## Glossary

Use exactly these words.

| Concept | Word | Notes |
|---|---|---|
| the product | Backyard | never "the family's Backyard" |
| the feed page | Your Backyard | |
| one home | Household | a household's own name stays exactly as a person typed it |
| one branch (a named side) | Side | say the side's own name where possible; define once as "a side of the family" in How It Works |
| a group a member made | Group | |
| the periodic e-mail | **Email Updates** | sentence form: "email updates". Frequency: **Weekly**, **Monthly**, **Off** |
| its settings link | Email Updates | page title "Email Updates"; label "How Often" |
| its e-mail subject | "New In \<Side\>: \<Mon D\> To \<Mon D\>" | built in `core/digest.py`; the side's own name is never re-cased. The body opens with the date range, no greeting |
| the why-you-got-this line | "You are receiving this because Email Updates is on. Turn it off: \<link\>" | |
| roles | Member, Side Admin, Family Admin | plainly: "Side Admin: adds and removes members on one side." "Family Admin: manages everyone and both sides." Never "look after" |
| the elder link | No-Login Link | |
| the recovery link | Sign-In Link (admin-issued) | the admin's page is "Create Sign-In Link" |
| the password-reset control | "Forgot Your Password?" | on the sign-in page and on Change Your Password, and quoted by that name wherever a page or an error names it |
| a WebAuthn credential | **Passkey** | never "security key". The badge beside one says what it DOES: "Signs You In On Its Own", "Second Step Only", "Not Known". The name prefilled in the Add box is "Passkey 1", not the library's "Master key" |
| a TOTP app | **Authenticator App** | what it gives you is a "six-digit code", never a "verification code" or an "OTP" |
| the one-time fallback list | **Recovery Codes** | "Each code works once." |
| proving who you are again | "Confirm It Is You" | the heading on all three re-authentication screens AND on the two-factor sign-in step: one job, one set of words |
| the second box on a password form | Confirm Password | all four password screens: change, set, the emailed reset, the no-login recovery |
| help line, signed in or holding a live link | "Need help? Contact \<first name\>." | |
| help line, public | "Need help? Contact the person who invited you." | |
| the landing page | heading "Welcome To Backyard"; body "A private, invite-only family network. Open your invite link to join."; button "Sign In" | the owner's own sentence, and the ONE place the landing says "family" |
| welcome, screen one | "A private, ad-free network to stay connected with everyone." then one sentence on who sees a post | |
| the audience sentence | "Posts are shared with your household. To reach more people, choose a side of the family or a group when posting." | household = the people you live with; a side = one branch, shown by its own name; a group = people you pick. This sentence is where "family" earns its place |

## Two subject lines that are not free to change

Both are copy with a mechanism behind it, and both are currently recorded only in a
template comment and a test docstring.

- **The two confirmation subjects must stay DIFFERENT.** The account address confirmation
  is "Confirm Your Email Address"; the Email Updates address confirmation is "Confirm This
  Address For Email Updates". They confirm different things, and one identical subject
  arriving twice from one sender is what the 2026-09-19 walk found.
- **The two password-reset subjects must stay BYTE-IDENTICAL.** allauth sends
  `unknown_account_subject.txt` to an address with no account and
  `password_reset_key_subject.txt` to one with an account. A different subject for the
  unknown address leaks whether an address has an account here, which is the whole point of
  `ACCOUNT_PREVENT_ENUMERATION`. Armed by
  `src/core/tests/test_one_address_one_confirmation.py`.

## The furniture

**The footer** is one component, `core/templates/core/_footer.html`, used by every layout.
The help line is first and is always TEXT — there is no help route in this app, and a link
to a page that does not exist is worse than no link (WCAG 2.2 SC 3.2.6). The account
action (Sign Out) or the two public pages (How It Works, About) sit at the other end of the
row, and the row stacks at phone width. A layout that extends `core/base.html` gets it
automatically; a standalone page includes it as
`{% include "core/_footer.html" with standalone=True %}`, which renders the sentence alone,
with no links.

**Helper text** is `class="hint"`, one class, one size, one colour, one rhythm, under the
control it explains. `.media-hint` is the same size and colour and differs only in its
margin, because it sits under a button rather than under a field. There is no third helper
class, and the transitional `field-help` alias is gone.

**A settings row** is `<p class="settings-link">` wrapping nothing but its link. The row IS
the link: no dash, no sentence after it. The page it opens says the rest.

**Errors** are `class="errors"` — a block whose `<p>` children are the sentences. Django
and django-allauth emit `<ul class="errorlist">`, which is styled to look identical, so a
form error looks the same wherever it is raised.

## What enforces what

Three guards, all parametrised by template, so a screen's owner can run them on their own
files: `pytest -k "welcome_email.html"`.

| Rule | Test |
|---|---|
| The glossary, and every struck word and phrase, in templates | `src/core/tests/test_one_word_per_concept.py::test_no_template_shows_a_banned_word_to_a_person` |
| The same, in model choice labels and the role descriptions | `test_no_model_choice_label_shows_a_banned_word_to_a_person`, `test_no_role_description_shows_a_banned_word_to_a_person` |
| The same, in every e-mail this product sends | the three `@pytest.mark.django_db` tests at the foot of the same file |
| No "we", "us", "our", "let's"; no exclamation marks, em dashes, ellipses or curly quotes | `src/core/tests/test_the_product_voice.py` |
| Capitalise Every Word in titles, h1–h4, buttons, legends, labels, `<th>`, `<summary>`, nav links, links styled as buttons, and e-mail subjects | `src/core/tests/test_title_case.py` |

All three read a template through `src/core/tests/copy_scan.py`, which strips comments,
`<style>`, `<script>`, template tags and template variables, and lifts `placeholder`,
`aria-label`, `title` and `alt` back in, because those are read aloud or shown. Code
identifiers, CSS class names, route names, comments, operator documentation and test names
are deliberately outside all of it: `Pod`, `Yard` and `DigestSubscription` are what the
code calls these things, and renaming them is a migration, not a copy pass.

What no test can hold: whether a sentence needed to exist. Read each finished screen
through the owner's three lenses.

1. **A designer.** Tight, consistent, nothing orphaned, the next step obvious, Title Case
   applied without exception.
2. **A first-time relative.** Could they act without reading twice? Does anything explain
   what they already know?
3. **An AI-fluff detector.** Would a careful human product writer have written this
   sentence? If it sounds like a model being friendly, cut it.
