# Changelog

Notable changes, newest first. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [semantic versioning](https://semver.org/), and `0.x` means no stability
promise yet — the schema and the URLs may still move.

**Install a tag, not `main`.** `main` is where the work happens and it changes daily; a tag is
a point somebody deliberately stopped at, with a full green gate behind it.

## [Unreleased]

<!-- Bracketed, because `_release_in_flight` in test_documented_version_resolves.py reads a
     BRACKETED heading as a live entry and an unbracketed one as withdrawn. It carries no
     link at the foot of the file: there is no tag to compare against yet. -->

### Changed

- **Every word the product shows a person has been rewritten.** The owner read the shipped
  copy end to end and rejected it. No route and no permission changed. Two stored values
  did, both for things saved after this release: the name prefilled into the Add A Passkey
  box is "Passkey 1" rather than django-allauth's "Master key" and is saved with the
  credential, and the vCard grouping category is `Backyard` rather than `Backyard family`.
  Existing passkeys keep their names; contacts imported earlier keep the old category and
  will not group with new ones. The few behaviours that changed were defects found while
  judging the new words at phone width, and they are listed under Fixed.
  - **A plainer voice.** The product no longer calls itself "we", "us" or "our", and no
    longer reassures, charms or explains what an adult already knows. Sentences that only
    set a mood are gone. Warnings that stop an irreversible or a security mistake all
    stayed, shorter: what a no-login link lets its holder do, who becomes a side admin when
    a hand-over link is first opened, that a link is shown once, and that deleting erases
    photographs from the server for good.
  - **Titles, headings, buttons and labels Capitalise Every Word**, written into the source
    rather than applied with CSS, so screen readers and tests read what the page shows.
    Names, addresses and anything a person typed are never re-cased.
  - **"Email Updates" replaces "the Family email" and "digest"** on every screen, in the
    settings page, in the mail itself and in its subject line. Route names, model names and
    URLs are untouched, so links already sitting in inboxes still work.
  - **One footer, on every layout**, including the sign-in pages and the grandparent page:
    the help line at one end and two links at the other, stacked cleanly on a phone. The
    links are How It Works and Sign Out for a signed-in member, How It Works and About for
    everybody else, so the page that answers "who can see what I post" is one tap from
    every screen. The help sentence is "Need help? Contact <name>."
  - **A real 403 page.** A member who tapped something they may not do used to get Django's
    unstyled built-in "403 Forbidden" with no header, no footer and no way back. There is a
    page now, in the product's own chrome. It deliberately does not print the internal
    refusal message.
  - **The passkey, two-factor and password-management pages are the product's own.**
    Thirty-six screens and flash messages that still spoke django-allauth's developer
    English ("Please reauthenticate to safeguard your account", "Master key") now read like
    the rest of the app, and Django's four bulleted password rules are one plain sentence.
  - **Three guards keep it that way**: one for the vocabulary, one for the voice (no first
    person, no exclamation marks, em dashes, ellipses or curly quotes) and one for
    capitalisation. They read every template and every e-mail this product sends, they are
    parametrised per file, and a failure prints the pasteable fix. The rules they enforce
    are written down in [docs/design/voice.md](docs/design/voice.md).

### Fixed

- **Found by reading every screen and e-mail at phone width after the rewrite**, as a
  designer, as a first-time relative and as an editor:
  - The weekly Email Updates mail was a fixed 600px table and clipped sentences mid-word on
    a phone. It is fluid up to 600px now, with an Outlook-only fallback that keeps it at
    600px where `max-width` is ignored.
  - On the share-more-widely confirmation, "Cancel" threw away the post that had just been
    written. The button says what it does: Discard Post.
  - The delete-a-person page kept its only Cancel a screen and a half above the delete
    button. It sits beside it.
  - The join form showed the browser's own grey validation bubble over the Join button,
    and the two Email Updates address boxes did the same. The server's plain errors are
    the only ones now. (The contact email box in Settings keeps the browser's check until
    it has a server-side one.)
  - The no-login page stopped saying whose link it was, so on a shared tablet Send Love
    could be tapped under the wrong person's name. It says "For <first name>".
  - An author who opened Edit Post after the fifteen-minute window was told "You Do Not
    Have Access", which is false. They are returned to the post and told the rule. The
    edit is still refused, on GET and on POST.
  - The widest contact-visibility choice read "Everyone", which a first-time relative can
    take to mean the public web. It reads "All Members" (a label only; migration `0032`
    emits no SQL).
  - The reply-notification mail named the wrong switch in its last line, so turning it off
    also stopped Email Updates without saying so. Each mail now names its own switch.
  - Three CSS rules upper-cased text the source writes in Title Case, including every
    table label at phone width. Removed.
  - The authenticator-app page said "Scan this QR code" above a line of fallback text where
    the code should be: django-allauth draws the code as a `data:` image, which this
    product's own Content-Security-Policy refuses on purpose. It is drawn inline now, the
    way the hand-over pages draw theirs, and the setup key beside it can be selected and
    copied (it was a disabled field).
  - A generated passkey name could repeat after one was removed, leaving two rows called
    "Passkey 2" with identical Remove pages. New names take the lowest unused number.
  - "Backyard is invite-only. Open your invite link to join." printed on every signed-out
    page in the sign-in layout, including the second sign-in step and the emailed address
    confirmation, whose readers are already members. It is on the sign-in page only.
  - The address-confirmation mail and page said confirming enables password reset and email
    updates. Email updates start only for a primary address that has them turned on at that
    address, and they say so now. They no longer promise password reset, which
    django-allauth already sends to an unconfirmed address.
  - The Email Updates settings page accepted any text with an "@" in it and cut a long
    address at 254 characters. It uses the same validator as joining: a malformed address
    is refused and nothing is stored or mailed.
  - Saving Notifications said nothing. It says "Saved.", like every other save.
  - A downloaded video is named `video.mp4` rather than `clip.mp4`.
  - Your Sign-In Email rendered a radio on its own line above an address run together with
    its two statuses, and three filled buttons of equal weight. It uses the product's own
    row, pills and quiet and danger buttons; allauth's field names are unchanged.

- **The outside monitor's alarm reached nobody's inbox.** It raised the alarm by opening an
  issue that mentions the repository owner, on the assumption that the mention e-mails them.
  Rehearsed on the live setup: the issue opened, the monitor closed it on recovery, GitHub
  recorded a `mention` notification, and no mail arrived — whether a notification becomes
  e-mail is a setting on the account, and the instance's own weekly health email cannot
  cover the case, because a box that is down sends nothing. The monitor now sends the mail
  itself, through Resend, from GitHub's runner rather than from the instance, on the two
  state changes only: once when a new alarm issue is opened, and once when it closes on
  recovery. The daily reminder comment still mails nothing, and the issue remains the
  durable record and the throttle. Three repository secrets arm it
  (`MONITOR_RESEND_API_KEY`, `MONITOR_ALERT_TO`, `MONITOR_ALERT_FROM`); with any of them
  unset the workflow behaves exactly as before and says so in one line. See
  [the outside monitor](docs/runbooks/self-host.md#the-monitor-that-runs-outside-the-box)
  for how to set and rehearse them.

## [0.1.4] — 2026-09-19

One fix, found by running the demo wipe's dry run on a live instance.

### Fixed

- **The demo wipe's own advice could never satisfy it.** It refused on a post a real person
  had written inside a fixture household and said to delete it first ("its author can, from
  the feed"). The author did, and it refused again on the same post: every delete here is a
  soft delete, and the guard read the unfiltered table. A post or reply that was ALREADY
  deleted through the product (by its author, by a take-down, or when its author was
  removed) no longer blocks, and the dry run counts those rows under
  `already-deleted posts and replies by real people` and says in words what that line is.
  A deleted row that still carries a photograph blocks exactly as a live one does, and a
  real person's live post or reply still stops the command. Found by running the wipe's dry
  run on a live instance.

## [0.1.3] — 2026-09-19

What a second walk of the live instance found the same day `0.1.2` went out, plus the one thing the owner of an instance needs in order to hand a side of the family to somebody else: a household link whose first joiner becomes the side admin.

### Added

- **A household invite can make its first joiner the side admin.** Handing somebody a side
  of the family took two steps that nothing connected: invite them, then notice and promote
  them. An invite carried no role, so the relative landed as an ordinary member who cannot
  invite anybody. The family admin — and only the family admin — can now tick one box when
  making a household link; the first person through it becomes the side admin for that
  household's side (or both sides, if it bridges) and everyone after them joins as a member.
  Capped at the side-admin role in three places, including a database constraint: no link
  can ever grant the family-admin role. Decided inside the same locked transaction as the
  one-use check, so two phones racing cannot both become admin. Seven-day expiry, revocable
  and voided on its creator's removal like any other invite, never re-armed by "Make another
  link", and the mint page, the invite ledger and the day-one guide all say what it does.
  Threat model row T-INVITE-2.
- **`mark_demo_data --include-departed`.** A member removed from a fixture household keeps
  their Member row and loses every membership, so selection by containment can never reach
  them — while their posts stay inside a household being marked, because "keep their posts"
  and "remove their name" both keep the author. `wipe_demo_data` then refused forever on
  "a post written by someone real", and the only cure was a shell. With the flag such a
  member is marked too, on three conditions: they are in no household or group anywhere;
  at least one **post or reply** of theirs is **inside** the households being marked (a
  reaction is never an entry ticket, only evidence against); and nothing of theirs sits
  anywhere else and no supervised child of theirs is staying behind. Anybody who never
  wrote anything is therefore never selected, which matters because the wipe deletes a
  selected person's Member row and their sign-in account. The dry run names each of them
  under a heading that says so; without the flag they are listed as deliberately not
  marked, with the reason and the flag. `--undo` clears them like any other marked row,
  and the wipe's own refusals — real writing, stranding — are unchanged.

### Changed

- **Starting a group and leaving one say so**, through the same calm flash the composer
  uses: "&lt;Group&gt; is ready." and "You left &lt;Group&gt;." A leave removes the row and
  said nothing at all, which on a phone is indistinguishable from a tap that did nothing.
- **A post widened to two sides names them in a sentence**: "Share with Mom's side and
  Dad's side?", not a comma list, in the heading, the sentence and the button. Three or
  more get commas and a final "and".
- **The second-factor offer on the roster tells a side admin the truth, and is one line.**
  It claimed "your sign-in opens every side of the family" to whoever opened the page; that
  is true of the family admin and of nobody else. It was also a screen-tall card between an
  admin and the list of people they came to read, and it now gets the same slim treatment
  the feed's e-mail line got.
- **The day-one guide names the route, not just the destination**: "tap Manage on their
  row, then …", now that the roster's row actions live behind a Manage disclosure. Page and
  repo copy both.
- **The help line a logged-out reader gets** is "Stuck? Ask the person who invited you."
  rather than "Ask whoever in the family set this up" — a role no family uses, and nobody a
  relative could ring.

## [0.1.2] — 2026-09-19

The first release a family is actually handed. `0.1.2` was written up on 2026-08-07 and never tagged; the state it described had known security holes, so it was never published and nobody could have installed it. This tag is that work plus everything found since by walking a live instance as every kind of user at phone width, by one outside-in security pass, and by moving the instance to a new server and restoring it there. The notes from the August cut follow the new ones, unchanged.

Day one for the two relatives about to be made yard admins: nobody gets locked out, and the
one control that destroys something asks first. Alongside it, the instance starts backing
itself up and telling somebody when it cannot.

### Added

- **A welcome, once, when somebody joins.** Three short screens instead of a green card on
  the feed: what this place is (private, just our family, no ads, no strangers), whether
  they want a family email (weekly, monthly, or no thanks, with the address they just
  typed already filled in), and a composer with a first line already written. Skippable at
  every step, and skipping leaves a finished member standing in their feed. The family who
  are already here never see it.
- **"How this works", one plain page.** Who sees what you post, who can join and how, what
  the Family email is and how to stop it, what happens to your photos and how to delete
  them, who to ask for help, and what to do if you forget your password. It is also the
  family's privacy note: the one per-person thing this software keeps is whether you
  stopped by in a given week, a yes or a no, and the page says so in those words. Reachable
  from Settings, from the sign-in page and from the welcome.
- **"About this Backyard"**, a quiet page carrying the licence and the source offer, one
  tap from Settings and from the sign-in page.
- **A day-one guide for the two new admins, in the product.** One screen, reachable from
  the roster: invite a household, give a grandparent a no-login link (and post something to
  their side of the family first, so the page they open is not empty), get somebody back in
  who is locked out, remove somebody and what happens to their posts, and who to ask. It
  existed only as a file in this repository, which is nowhere for the people it is written
  for.
- **There is a person behind every name.** A calm coloured circle with someone's initials
  now sits beside their name wherever it leads something — a post, a reply, a row in the
  directory, their own page. The colour is picked from the person, so the same relative
  looks the same everywhere. No photo to upload and nothing to keep up to date.
- **The directory says where people sit in the family.** Each row carries their side of
  the family and their household under their name, and only the ones you are already in.
- **A profile shows what that person actually wrote.** It used to be a name, one line
  saying they had shared nothing, and a link that would have downloaded an empty contact
  card. That link is now offered only when there is something on it to save.
- **One control for photos and video: "Add photos or a video".** It replaces two stacked
  "Choose Files" boxes, so a phone offers its own Photo Library / Take Photo sheet once
  instead of asking which kind of thing you meant first. What you picked appears as
  thumbnails before you post, each with its own Remove. Without JavaScript it is still a
  plain working picker with the browser's own count, and the limits are written beside it.
- **Photos taken on an iPhone now upload from any browser.** A HEIC picture was accepted
  only from Safari, which can convert it before sending; from Chrome, Firefox or an
  Android phone the same photograph was refused outright. It is converted on arrival now.
  `.mov` clips were already accepted and still are.
- **The product says when something worked.** Posting and replying now say so on the page
  you land on. A new post sits well below the fold on a phone, so tapping Post used to
  change nothing you could see — while the app cheerfully announced that you had signed in.
- **An unfinished post waits for you.** Leaving the "share with a whole side of the
  family?" question any way other than answering it used to throw the whole post away.
  Your words are kept, with the photos you picked, until you post it or discard it.
- **An admin can change somebody's household.** Until now a person entered a household one
  way only — by redeeming an invite — and redeeming makes a *new* member, so anybody who
  already had an account was stuck where they were. Nobody could be moved when they joined
  the wrong household, when an adult child moved out, or when two households merged, and the
  person running the instance could not put an existing member on a side of the family they
  had just created without a shell. From a member's row on the members page, an admin can now
  add them to a household that already exists, make a new household (name plus one or more
  sides of the family) and put them in it, or take them out of one. Because a household
  carries a side of the family with it, there is a second page that says in plain words which
  sides' posts and photographs the person will start — or stop — seeing, naming them, before
  anything happens. Taking somebody out signs them out everywhere, kills the links in the
  weekly emails they have already had, and cancels unused invitations into the side they are
  leaving — but not their weekly email itself, which keeps coming and simply narrows, because
  somebody who is still here should never be cut off by an act that was only meant to move
  them; their last household cannot be taken away, because somebody in no household can
  neither see anyone nor be seen. A yard admin can do all of this only for an ordinary
  member of their own side, only with households that belong entirely to sides they look
  after, and never for themselves. The person who runs the instance can do it for
  themselves — standing up the second side of the family and moving into a household on it
  is the whole reason this exists — and the page still says out loud what they are about
  to start seeing, and records that they did it.
- **An admin can get somebody back in.** A member who joined without an email address had no
  password recovery at all — `Forgot your password?` resolves against an address that does not
  exist, and the page correctly says "sent" either way, so they found out they were locked out
  at the worst possible moment. The only real cure was `manage.py changepassword` at a server
  shell, which is not something a relative has. An admin now mints a one-time "get back in"
  link on the member's roster row and hands it over by text or reads it out, the same way the
  household invite and the grandparent link already work. It is single use, dies after two
  days, is revoked by issuing another, and ends every other session when it is redeemed. A
  yard admin can issue one only for an ordinary member of their own side of the family.
- **Members can reach their own account pages.** The sign-in email, the password change and
  the passkey/one-time-code pages were routed, styled by this project's own layouts, and
  linked from nowhere any member could stand — for months, while the join page promised "You
  can add a passkey once you are in". They are now in Settings.
- **A member with no email address on file is told so, once,** with a link to add one and a
  "Not now" that means it. Members who joined before the join form had an email box are
  exactly the people this reaches.
- **A plain member is told who can add people.** Inviting is an admin's job in this version
  and no page they could reach said so, so the obvious next thing to do read as broken. The
  feed now names the person who invited them. It sits outside the first-visit orientation
  card on purpose: that card is already dismissed for everybody who was here before it
  shipped, so inside it the sentence would have reached nobody it was written for.
- **The instance backs itself up.** `backup_instance` shipped with nothing running it, so
  an instance holding a family's photographs had a documented backup command and no
  backups. The worker now takes an encrypted archive nightly at 03:30 UTC, keeps the last
  14 days plus the newest archive of each of the last 8 ISO weeks (the two windows overlap,
  so about eight weeks of history in total), and deletes only archives it wrote itself.
  With no passphrase configured it writes nothing at all rather than falling back to
  plaintext. The passphrase can come from `BACKYARD_BACKUP_PASSPHRASE_FILE`, a keyfile
  mounted read-only, which is what the self-host guide recommends over the environment
  variable. The run refuses a night that would fill the data volume rather than writing
  until the disk is full, and a `pg_dump` that hangs is killed after six hours instead of
  holding the worker's one job slot forever.
- **A failing backup is now distinguishable from an old one.** The weekly health email and
  the health surface carry the reason the last scheduled run failed, instead of a
  "last backup" date that reads the same whether the backup ran or refused to. Each
  recorded backup says whether the scheduler or a person took it, and only the
  scheduler's own runs can report the nightly job as working — so taking one backup by
  hand, which is the first thing the alarm makes you want to do, does not silence it.
- **The host can now tell the instance how the off-box copy went.** Copying an archive off
  the server stays on the host deliberately — a copy step inside the container would need
  the destination's credential, which would then sit beside the ciphertext on the same
  volume — so the instance could never say whether a copy happened, and a host job that
  quietly stopped was nobody's alarm. If the job writes one small JSON file
  (`.offbox-status.json`, beside the archives), the health email and `/healthz` report it:
  a success inside 48 hours reads healthy, an older one or a reported failure raises the
  line and degrades the instance, and the reason goes to the instance admin and never to
  the public endpoint. **Writing no file changes nothing** — the line still reads NOT
  MEASURED and the instance stays `ok`, because most self-hosters have no off-box job and
  an instance that cried wolf about one they never set up would teach them to ignore the
  word `degraded` everywhere else. The file is operator-written on a volume the app also
  writes to, so it is read as hostile input: size-capped, symlinks not followed, and
  anything malformed becomes an `UNREADABLE` line rather than a traceback in the weekly
  email. The health field is now called "Off-box copy" rather than "Off-box backup age".
- **Days until the TLS certificate expires**, in the health email. Renewal is automatic and
  silent, and so is its failure; an expired certificate is a full-page browser warning for
  every relative at once. A check that has never succeeded reports why, which is the
  difference between a broken certificate and one this box cannot reach from the inside.
- **Container healthchecks for web, worker and caddy.** Only the database had one.
- **A monitor that does not live on the monitored box** (`.github/workflows/monitor.yml`):
  every 30 minutes it checks the health endpoint AND the certificate — neither result
  skips the other — and records what it found on a single GitHub issue labelled
  `monitor-alarm`, which e-mails the owner once because it mentions them. Every other
  watcher the instance has is a worker periodic, so a dead worker silenced its own alarm.
  While a problem lasts the monitor comments on that one issue at most once a day rather
  than opening another; when the instance recovers it comments and closes it, so no open
  alarm issue is the all-clear. The run itself goes red only if the alarm mechanism
  failed: a persistent outage should be one issue, not 48 failed runs a day until the
  owner mutes the repository and loses the outage alarm with it.

### Changed

- **The family reads their own clock.** Every date and time in the product was stated in
  UTC, with no hedge, because nothing had ever offered to change it — a post written at
  4:28 in the morning read "9:28 a.m." on the family's own feed. The instance now has a
  time zone (`BACKYARD_TIME_ZONE`, an IANA name, validated at boot so a typo refuses to
  start rather than printing wrong times on every screen), and on top of that each page
  carries the instant in its markup so a relative in another zone sees their own wall
  clock. E-mail uses the instance's zone, because an e-mail has no browser to correct it.
  The grandparent's page still shows dates only.
- **Taking somebody's post down asks first.** It was one tap: gone at once, the
  photographs purged for good, no message and no undo, while the day-one guide two taps
  away promised that nothing here is a one-tap disaster. Both a post and a reply now go
  through a confirm page shaped like the author's own delete page — whose it is, what it
  erases, and that the person is not told — and it is never offered on your own post,
  where Delete already is. Deleting a post, changing a role, removing a member, creating
  a child account and saving a profile all say so afterwards.
- **The roster is a list of people again.** Every control for every relative used to be
  open at once — a role select, a remove form and an add-a-child form for each person, so
  a six-person family filled about five phone screens, four-fifths of it destruction. One
  line per person now, with the actions behind a single "Manage". A row you cannot act on
  says which rule put it out of reach and who to ask.
- **"Side admin" and "Family admin"**, on the roster badge, in the role picker and in what
  the roles mean. They were "Yard admin" and "Instance admin" — this project's own nouns
  wearing a capital letter, on the one screen where a relative is handed the controls.
  Nothing stored changed; the guard that keeps one word per concept now reads these too.
- **A stranger is told nobody's name.** "Stuck? Ask <first name>." sat in the footer of
  every page this product serves, including the sign-in screen, both password-reset pages,
  About and every 404. Signed-in members and anyone holding a link a relative sent them
  still get the name; a stranger who typed the domain gets the same help in other words.
- **The Family email stops implying you can reply to it.** Replying by e-mail was
  retired for relatives when the per-post reply address came out of the message: nothing
  hands anybody an address, so a plain reply cannot be routed to a post and lands in the
  admin-only "Replies we couldn't post" instead, where the sender never learns their words
  went nowhere. The message no longer carries the "reply above this line" marker, and the
  metrics page says plainly that "Replied by email" is a retired route rather than leaving
  an admin to read a permanent zero as a family that stopped answering. The way to reply
  is the link on each post, which opens the thread. The inbound parser itself is untouched,
  because messages sent before this are still in inboxes.
- **Mail has a name on it.** Messages arrived as a bare address — or as just "digests" in
  the clients that shorten it — which is how a family's own photographs come to look like
  spam. Every message now carries a display name (`BACKYARD_MAIL_FROM_NAME`), including
  allauth's own, and the Family email says why it arrived.
- **One address needs one proof.** A relative who gave an e-mail at join and then chose
  "weekly" got two messages a minute apart with the identical subject, threaded together
  into what looked like one message sent twice. When the Family email address is the
  member's own sign-in address, one mail is sent and one tap confirms both.
- **Getting back in ends somewhere.** The get-back-in link saved the password and dropped
  the person on a blank sign-in form with an empty username box — and this link exists for
  the relatives who have no e-mail on file, half of whom do not know what username an
  admin typed for them. It now lands saying "Your new password is saved. Sign in as
  <username>.", once, with the box already filled.
- **The join page and the emailed reset page ask the same way the get-back-in page does**:
  which household you are joining, what a username is for, the same advice about three or
  four unrelated words, and a way to see what you typed.
- **Smaller things the walk caught.** Five nav items fit one line on the narrowest phone
  (Sign out moved to Settings and the footer); the "add an email address" card became one
  quiet line under the composer; the photo picker adds to your selection instead of
  replacing it, and a photo the browser cannot draw gets words instead of a broken icon;
  the "Who can see my ..." controls all stack at one width; adding a grandparent shows the
  link instead of the empty form that made a second one by accident; inviting a household
  into the only side there is states it rather than offering a checkbox with no choice in
  it; the "you are all set" page has a way on; and a removed relative gets our own words
  rather than the framework's "Account Inactive".

- **One word per concept, everywhere a relative reads.** The product used three words for a
  household (pod, household, house), two for a side of the family (yard, side of the
  family) and three for the weekly email (digest, weekly email, Digest delivery), and put
  "elder path", "token" and "instance" in front of people. It is now household, side of the
  family, the Family email, no-login link and this Backyard — in every template, in the
  control that decides who sees your phone number, and in the subject and body of every
  email the product sends. A test fails the build if one of the old words comes back.
- **The footer says who to ask, by name.** "Stuck? Ask whoever in the family set this up"
  became "Stuck? Ask <name>", read from whoever runs the instance at the moment the page is
  drawn. The grandparents' page carries it too. The licence and source-code line left that
  footer for the About page; it was the second-loudest sentence on every screen in the
  product, a page of family photographs included.
- **The sign-out, password-reset and email-address pages are in this product's voice.**
  They were the library's, in Title Case, with a field labelled "Email:" and a
  password-reset flow that ended on "Please contact us if you have any trouble" — with no
  "us", no link, and no other way out for somebody who cannot sign in. So were the emails:
  the address confirmation went out as "Hello from backyard.family! You're receiving this
  email because user james has given your email address to register an account".
- **The Family email is weekly or monthly.** Daily is no longer offered; anyone who already
  chose it keeps it.
- **A returning member opens the feed and sees the family.** Signing in used to stack four
  things above the composer: "Successfully signed in as priya.", the orientation card, a
  loose paragraph about whose job inviting is, and the add-an-email card. The flash greets
  the person by the name the family gave them, the card is now the welcome, and the
  inviting sentence moved to the directory and to How this works — the two places somebody
  goes looking for it.
- **A post keeps the shape it was typed in.** Line breaks were collapsed, so a recipe off
  a card, an address or a packing list arrived as one run-on sentence. Fixed everywhere a
  post or a reply is shown: the feed, a thread, the grandparents' page, the family email
  and the web page that email links to. A web address in a post is tappable on the feed,
  in a thread and on that web page. It is deliberately left as plain text in two places:
  the grandparents' page, because nothing on it leads off it, and the family email
  itself, where a mail client linkifies an address for you and every link we emit stays
  on this instance.
- **Delete is no longer sitting next to Open thread.** Three identical green links a
  thumb's width apart meant an accidental tap could destroy a photograph. Destructive
  actions now sit at the far end of the row, in their own colour and weight.
- **"Send love" lands on the confirmation.** Tapping it on the grandparents' page jumped to
  the top of the post, about sixteen hundred pixels above the heart that had just appeared,
  so it looked as though nothing had happened.
- **The grandparents' page uses the same typeface as the rest of the app** — the one chosen
  for low-vision readers, which was the only place not using it — and says dates the same
  way every other screen does.
- **Opening a post now enlarges its photographs.** The thread page was serving the same
  small thumbnail the feed does, so tapping a photo to see it better did nothing.
- **The composer opens small** and grows when you start writing, instead of standing
  between you and the first photograph in your family's feed.
- **A wrong password looks like the app telling you something**, rather than a black bullet
  indented off the edge of the card. The same fix reaches every form in the product.
- **Paging back into the archive is its own page.** It kept the current feed's title and
  composer and ended on "You are all caught up", which was the opposite of true.
- **Bigger tap targets** on the "who can see this" checkboxes and the top navigation, and
  one consistent, solid empty state instead of a dashed box inside a solid one.
- **The front door says welcome.** It said "Backyard is running".
- **Deleting a member's posts and photos takes a second step.** It erases photographs from
  the server with no undo, and it sat behind one radio button and one button on a page listing
  five other people's Remove controls. It now shows what will be destroyed — including the
  photos other people put on replies to their posts, which go too — says that it cannot be
  undone, and asks for the person's name to be typed. It also counts the pictures that come
  with links they shared: we keep a copy of each one so the card in the feed does not phone
  out to somebody else's server, and those files are erased too. Keeping or anonymising
  their posts is unchanged; neither erases a file.
- **A yard admin can fix a profile on their own side.** They could remove a member outright
  and could not correct that member's birthday, so a name typed wrong at invite time, or a
  grandparent's details filled in for her, went back to whoever runs the server. The name,
  the nickname and the two dates only: a phone number, an email address and a home address
  stay between their owner and the people that owner chose, so an admin standing in for
  somebody else does not see those boxes and cannot change what is in them.
- **The "get back in" link asks for the new password twice.** It works once, and the people
  it is for have no email address on file, so a typo they could not reproduce would lock
  them out again and cost another phone call.
- **Break-glass admin recovery works for the second admin.** It keyed on the Django superuser
  flag, which only the very first admin has — so the relative promoted to instance admin, the
  person the succession path exists to create, was the one admin who could not be recovered.
- `/healthz` answers `ok` or `degraded` (always HTTP 200) instead of always `ok`. The
  fields behind that word are visible to a signed-in instance admin and to nobody else: at
  a public URL, disk headroom and backup age are an operations map for whoever asks first.

### Fixed

- **The licence stopped being the second-loudest line on a grandmother's photo album.** It
  had been kept on the no-login page on the reasoning that the page can link nowhere; the
  offer is on `/about/`, which is public and reachable without signing in, and printing it
  under her grandchildren's photographs was never what the licence asked for.
- **A real person's reaction no longer blocks the demo wipe.** One relative tapping a heart
  on a fixture post refused the whole wipe, with no screen left on which they could undo it
  once that post was down. A heart is not somebody's writing: it goes with the post it sits
  on and is counted in the dry run. A real person's post or reply still refuses, unchanged.

- **A quiet week sends no email.** A confirmed subscription produced a Family email every
  period whether or not anyone had posted — a greeting, a date line and a footer with no
  family in it. A window with nothing in it now sends nothing, records nothing as
  delivered, and stays open, so anything written during that quiet stretch arrives in the
  next one. The window is looked at twice, the second time at the built email itself, so
  a post deleted while the run is working cannot produce that empty mail either.
- **A side of the family is called what it was named.** Every screen that listed one
  appended the word "side" to it, so a side named "Mom's side" read "Mom's side side".
- **The roster's role control showed the wrong role, on every row.** It rendered the roles
  an admin could grant, with nothing marked as selected, so it always displayed the first
  option and every ordinary relative's row read as though they were already an admin — next
  to a pill saying "Member". It now opens on the member's current role and says that
  choosing it changes nothing.
- **A member's row no longer breaks at phone width.** Below 40rem the row is a stack rather
  than a flex line that centred "No-login link" against the two-control form beside it.
- **The invite result no longer shows a second, empty invite form** under the link it just
  made, with an identical button.
- **The outstanding-invites list is a card per household** instead of one run-on line of
  five unrelated pieces wrapping around a button.
- **"Connection health" stopped printing a repository file path** at a non-technical
  relative, along with "aggregates", "per yard" and "datum". It is "How the family is using
  it" now, and says what it counts in a sentence.

- **A removed member is no longer offered a "get back in" link.** Their row stays on the
  instance admin's list, so the control rendered — and the link worked right up to the
  sign-in page, which can never let a removed account in. It is not offered and not minted.
- **"Edit profile" no longer dead-ends for whoever runs the instance.** The list of family
  members offers it on every row, and for the person who runs the whole instance that is
  everybody on both sides — but the page itself refused anyone outside your own side, so the
  link led to "page not found". The page now answers the same question the link does. For a
  side's own admin nothing widens: the other side of the family is still not there at all.
- **The reachability gate now covers the account pages it was blind to.** It skipped every
  route belonging to an included URLconf, on the grounds that the library owns its own
  reachability. Mounting those routes puts them in this product, and three of them had no
  entrance for months. Each one is now either reachable by clicking or listed with the reason
  it has none.
- **Regenerating a grandparent's link revoked every outstanding household invite on their
  side of the family.** Inviting a household and handing out a no-login elder link are the
  two things a new admin does in the same sitting, and doing them in that order silently
  killed the first: the invite showed as revoked, its Revoke button disappeared, and the
  family who had already been texted the link got "There's nothing at this address." Nobody
  was told. Revoking those invites is right when a member is being REMOVED — it is how a
  removed ex is kept from walking back in through somebody else's invite — and wrong when
  the person is still here and only their own link is being replaced. Removal is unchanged;
  regeneration now leaves alone the invites OTHER admins issued, and still kills everything
  the member actually holds: the old link, their sessions, their digest links, their
  reply-by-email addresses, and any invite they minted themselves — because a new link is
  also what you make after a lost phone, and an invite created while somebody else held it
  would otherwise outlive the rotation. The page that shows the new link now points at the
  list of open invites for exactly that case.
- **Every link the app hands out is built from one setting, and a wrong value was
  invisible.** `BACKYARD_BASE_URL` is what every invite, elder link and digest link is built
  from. Left unset or stale, all of them still look perfectly normal on the screen that
  mints them — and every single one is dead for whoever receives it, with nothing in the app
  saying so. Two changes: an instance configured to serve a real domain now refuses to start
  when the variable is unset, points at localhost, is not an absolute http(s) address, or
  names a host this instance does not serve — the stale case, after a domain move — naming
  the variable in the error (a purely local instance and the production overlay, which
  derives the value from `BACKYARD_DOMAIN`, are unaffected). **Upgrading:** if you set
  `DJANGO_ALLOWED_HOSTS` by hand, set `BACKYARD_BASE_URL` before you upgrade, or the app
  will refuse to start and say why in `docker compose logs web`. And
  every page that mints a link now says, under it, "This link opens at &lt;host&gt;." — so a
  wrong address is caught by the person handing the link over, not by the grandmother who
  was texted it.

### Security

- **Updates now arrive on their own.** A self-hoster who forks or watches this repository was
  relying on somebody remembering to look: security fixes for Python packages did open pull
  requests, but nothing ever proposed a newer Postgres or Caddy image, a newer base image, or
  a newer build action. `.github/dependabot.yml` now opens one batched pull request a week per
  ecosystem — Python, the Dockerfile, the compose image pins, and the build actions — and
  security fixes for Python arrive together in a single pull request rather than one per
  advisory, because the dependency scanner that guards this repository reads the whole locked
  set and a fix for one of two open advisories can never go green on its own. That happened:
  a bump of `sqlparse` alone sat unmergeable until `django` was bumped beside it by hand.
- **The build pins exactly what it runs.** Every third-party GitHub action is now pinned to a
  full commit hash rather than a version tag, with the version written beside it. A tag is a
  pointer its owner can move, and moving one is how other projects have had their build
  pipelines taken over. Nothing about a running instance changes; what changes is that the
  code which builds the image you install can no longer be swapped out from under it.
- **The edge's security rules are tested, not just commented.** `caddy/Caddyfile.prod` carries
  properties a self-hoster's instance depends on — no request logging (your family's links
  carry sign-in tokens in them), no admin API, no header that silently breaks every form — and
  each was enforced by a note asking the next person not to change it. A test now reads the
  file and fails the build if one is dropped.
- **Every page is checked for accessibility on every pull request.** The browser sweep that
  measures colour contrast, labels and keyboard reachability across all 33 screens, in light
  and dark, on a phone and a desktop, used to be run by hand. It runs in CI now and fails the
  build on a serious finding, which matters most on the pages an older relative uses.
- **A family link that is opened hundreds of times in a few minutes pauses for a moment.**
  Every link somebody is handed — an invitation, a grandparent's no-login link, the web
  copy of the weekly email with its confirm and unsubscribe pages, a "get back in" link,
  and the console-minted admin reset — could be asked for as fast as anything cared to ask.
  Each one is generous enough that a whole household opening the same invitation from one
  home connection, or a grandmother refreshing a page she is not sure worked, is never
  turned away; when it does pause, the page says so in plain words and tells you to try
  again in a minute.
- **Control characters are stripped from what people type.** A name, a post and a reply
  are stored clean now, so an invisible character cannot reverse a line of the weekly
  email, which is plain text and does not escape anything. Replies that arrive by email
  were already treated this way; the browser now matches them, from one shared rule.
- **Leaving a group revokes what leaving takes away.** Until now, walking out of a group
  dropped the membership and left everything else alive — including, for somebody whose
  only tie to a side of the family was that group, links that still reached it. A leave
  now does exactly what an admin taking you out of a household does: it signs you out
  everywhere, kills the links already sitting in your emails, cancels unused invitations
  into the side you are leaving, and keeps your weekly email. Leaving the only group you
  are in is refused, with a sentence saying why, because somebody in no household can see
  nobody and be seen by nobody.
- **A grandparent's photographs stop being served the moment her link is revoked.** Two
  parts of the product read the same no-login session and disagreed about when it was
  still valid: her page refused her correctly while every picture on it was still being
  handed out. They ask the same questions now.
- **The first-run setup secret is no longer written into the container log.** It is kept
  in a private file on the data volume that only the app can read, and it is deleted the
  moment the first admin exists. `make setup-secret` reads it; the README and the
  self-host guide say so.
- **A restore refuses, loudly, before it touches anything.** Both halves of the archive are measured before either is written and before the database is replaced, so a refusal that says nothing has happened is telling the truth.
- **A backup that fails part-way leaves nothing readable behind.** The pre-flight dump the instance takes on every boot is written in the clear before it is encrypted; if it died mid-way the partial file stayed on the disk. It is removed on that path now.
- **A restore refuses, loudly, before it fills the disk.** Restoring a backup deletes the
  existing photographs before it writes the new ones, so a media archive bigger than the
  free space left a box with neither. It is now checked against the volume's free space, a
  per-file ceiling and an absolute ceiling, and refuses before a byte is written.
- **The registry lookup that watches the domain's expiry cannot be redirected inside the
  box.** It follows a redirect from a third party, and it had no check on where that
  redirect pointed. It now shares the same address gate the link-preview fetcher has
  always used: a private, loopback or link-local destination is refused before the connect.
- **A failed video no longer writes a live media link into the log.** The tail of the
  converter's error output names the file it could not read, and that filename is the
  credential the photo path accepts.
- **Reply-by-email is stricter about who a reply is from, and cannot hold a worker.** The
  address a reply was delivered to is the only thing that decides whose reply it is; a
  message addressed to somebody else's reply address is refused rather than posted as
  them. The fetch that collects the message now has a time limit and a size limit, so a
  slow or enormous one cannot occupy the app. The endpoint is not published at all unless
  inbound email is configured.
- **Leaving a group no longer signs you out of your own family.** Walking out of a group
  that was your only tie to one side of the family ends every session you had, which is
  the point — but it was ending the one you were sitting in front of too, so the next tap
  landed on the sign-in page with nothing to explain it. The browser you pressed the
  button in stays signed in; your other devices, and any links into the side you left,
  still stop working.
- **The sentence you get if you cannot leave a group is true.** It used to say "it is the
  only one you are in" to somebody looking at a second one on the same page. It now says
  what is actually missing — a household — and who to ask for one.
- **Admin second factor: offered, never required — and the security record now says so.**
  The threat model claimed a second factor was enforced for admins and nothing enforced
  it. Requiring one would mean lockouts for relatives who are not technical, and a
  locked-out admin is recovered only from a server shell. So an admin with none sees one
  calm prompt on the members page, in plain words, with a link to set one up and a "not
  now" beside it. It never blocks anything. Whether the one instance admin should be the
  exception is filed as issue 182.
- **Django 5.2.17 and sqlparse 0.6.0.** Ten advisories across the two, and the `deps` gate —
  the required check that scans the resolved lock on every pull request — had been failing on
  all ten. Neither is reachable in this app (the Django one is GeoDjango, which is not
  installed; sqlparse is only called by the SQLite and MySQL backends and by the test
  runner's `--debug-sql`, and Postgres overrides the one shared call site), so the reason to
  take them is that a scanner does not do reachability analysis and a red required check
  blocks every other fix behind it.
- **The Postgres image moves from 18.4 to 18.6**, which closes 28 upstream CVEs, 14 of them
  scored 8.8. The container publishes no port and shares no network with the edge, so the
  only things that can speak SQL to it are the app and the worker — this is the layer
  beneath a compromised app rather than a door onto it. The bump also refreshes the `psql`
  the self-host guide has you run by hand against the box, which is where the 8.8 `psql`
  entry (CVE-2026-18408, `\unrestrict`) lives, so this bump closes that one. What it does NOT
  close is the 8.8 entry that fires through `pg_dump` (CVE-2026-19385): every dump and
  restore this product takes — the entrypoint's pre-flight backup on every boot,
  `backup_instance`, `restore_instance` — runs the `postgresql-client-18` installed in the
  APP image, not the client in this container, so that one closes only on the `build --pull`
  below, which refreshes the app image's `psql` as well. A minor Postgres upgrade needs no
  dump and restore; the new digest is pulled on the next `up -d`.
- **The Caddy image is refreshed** to a current Alpine base. Same Caddy v2.11.4 binary.
- **Every documented redeploy now builds with `--pull`, chained to the `up`.** The app image
  installs `pg_dump` and `ffmpeg` in a layer built BEFORE the application code is copied
  in, so an upgrade that only changes the code never invalidates it: both binaries stayed at their first-build versions for the
  life of an instance, on the process that decodes uploaded video and the one that takes
  your pre-flight backup. `--pull` re-resolves the base tag and rebuilds that layer whenever
  upstream has published a new `python:3.13-slim`; when it has not and you are acting on an
  advisory anyway, `build --pull --no-cache` is the only command that forces it, and the
  self-host guide now says so. The `&&` matters as much as the `--pull`: as two separate
  lines, a failed build was followed by an `up -d` that quietly started the previous image.
  Fixed in the self-host guide's Upgrades section, the handover runbook, and the overlay's
  own header; a new test pins every documented deploy as a first install or a redeploy, so
  the next one cannot be missed.

### Documentation

- **The documents now say what the code does.** Every claim in this pass was re-derived by
  opening the code or running the command, never by reading a neighbouring document, and
  where two documents disagreed both were fixed rather than one being quietly deleted. The
  corrections that change what an operator would do: the handoff note told them in one half
  that production's backups were encrypted and in the other half that the whole family
  database was sitting in plaintext three copies deep (it is encrypted, and always was since
  August); it told them a demo password published in a public repository still opened the
  instance (it does not — one outside-in attempt was rejected); and it told them to take the
  first backup production had ever had (it takes one nightly, and an archive of it has now
  been restored onto other hardware). The founder QA script drove every command at a
  differently-configured stack, because it was the one document that never carried the
  production compose overlay.
- **A runbook for moving an instance to a new server**, written from having done it:
  carry the environment file across, take the final backup, restore, restart, prove
  `migrate --check` is clean, copy the TLS volume so the certificate never lapses, verify the
  new machine before DNS moves, and keep the old machine's volumes until a real walk passes.
- **The threat model is true of the code again.** Its backup row named a command this project
  has never run; its revocation requirement described four lifecycle transitions and a
  supervised-account custody step as though they were built, when two of the transitions and
  the custody step have no implementation at all; and its deceased-member requirement
  described a feature the founder cancelled a month after it was written. Each is corrected
  and the corrections are recorded in a new section rather than edited in silently, because a
  row that overstates is read as an answer and stops anybody looking.
- **The weekly family email is one-way, and the documents now say so everywhere.** The
  per-post reply address was removed from the mail some time ago — it is a bearer credential,
  so printing it forwarded the ability to post as you — but the README, the install guide and
  the QA script all still described replying by email as a working feature. The inbound
  pipeline is live and configured; nothing hands anybody an address to use it with.
- **The printed recovery sheet's restore actually works now.** Its steps had you write the
  passphrase to a file on the host and then pass that host path to a command running inside
  the container, where it does not exist — so the one document read when the instance is
  already gone failed on a tired person's first attempt. The passphrase goes in the box's
  environment file before the stack comes up (which the new box needs anyway, so its own
  nightly backups keep encrypting under the same passphrase), the archive is streamed in as
  the app user, and the restore takes no passphrase flag at all because the command reads the
  environment. A new guard asserts that any `--passphrase-file` path a runbook documents is
  introduced by a mount in the same document; it was proven to fail on the sheet's old text.
- **`docs/RESUME-HERE.md` is short and current**; the five-hundred-line version it replaces
  is kept unedited under `docs/archive/` with a banner saying it is history. Open work lives
  in GitHub issues, and the two remaining documents say plainly which of them is a record and
  which is a list of criteria.

**What follows was written for the 2026-08-07 cut of this version, which was never tagged. It ships in this tag too.**

`v0.1.1` could not be installed from its own README, and several things it shipped were
reachable by URL but not by a person. Install this one.

This release is mostly about a single pattern: **checks that could not fail.** Nearly every
defect below was found sitting behind a passing gate, so the gates were rewritten alongside
the fixes, and each new one was proven by breaking the thing it guards.

### Fixed

- **The documented install failed on its third command.** `.env.example` named three
  variables; the production overlay refuses to start without five. A stranger who ran the
  README verbatim got `set BACKYARD_DOMAIN in .env` and no instance.
- **The printed emergency recovery card could not be pasted.** Its restore command opened
  `sh -c '` and never closed it — on the one page someone reads when the instance is
  already gone.
- **Seven documented container commands died before they started.** `docker compose exec`
  gets the container's configured environment, which has never held `DJANGO_SECRET_KEY`.
- **The whole admin cluster had no way in.** The nav rendered four links under a comment
  saying "Five links". `members`, `member_digests`, `member_metrics`, `create_supervised`
  and eleven other routes were reachable only by typing a URL — 15 in total. There was no
  sign-out link anywhere in the product.
- **Notification settings could be switched on and never off** from the web. The only route
  was the unsubscribe link inside a digest you had already received, so an unconfirmed
  subscriber could not turn it off at all.
- **Three forms threw away what you had just typed.** The join form cleared all four fields
  on any error — the first thing a relative ever does, on a phone. The composer kept your
  photos, dropped your words, and said the photos were safe, which reads as "everything
  survived".
- **A grandparent's page died on day 14** and blamed her link. Nothing extended the elder
  session, and the shared 404 is byte-identical for expired, revoked and unknown by design
  (S-202), so it could not say which. The session is now scoped to the elder surface and
  refreshed when she reads.
- **Tapping the heart threw her to the top of the feed** instead of back to the post, and
  reactions rendered legal names on the one surface built for the person least likely to
  recognise them.
- **A parent could not create their own child's account.** `can_create_supervised` has
  always permitted it; the only control lived on an admin-only page. The permission said
  yes, the page said 403.
- **A child could be placed in a household their parent is not in**, where the parent
  cannot see them — the form offered every pod the *admin* could see.
- **An ad-hoc pod froze permanently when its owner left or was deleted.** `Pod.owner` was
  set at creation and nowhere else, so a nulled owner left the house rule and member list
  unreachable to everybody. A departed owner also kept control of a group they had walked
  out of. Ownership follows membership now.
- **The demo family could not be removed from an instance seeded before the marker
  existed.** `wipe_demo_data` only touches rows stamped `seeded_by`, which is what makes it
  safe — and means it correctly finds nothing on a box seeded earlier, where the fixture
  family carries the same empty marker every real person carries. That left one option:
  deleting those rows by hand at a shell, which is how the unscoped wipe came to be written.
  `manage.py mark_demo_data` stamps them first. You name yards; pods and members are selected
  by CONTAINMENT — a pod only if every yard it belongs to was named, a member only if every
  pod they belong to was — so a household bridging into a real side is left alone, and so is
  a relative who joined a fixture pod during QA. It prints what it deliberately spared and
  why, refuses to re-stamp anything carrying a different generator's marker, and is
  reversible with `--undo`. The wipe is not.
- **The wipe's receipt undercounted photographs by half and lost their rows.** It reported
  the number of media ASSETS under the label `files`, and an asset carries up to four; and
  `MediaAsset` never appeared at all, because the purge deletes those rows before the cascade
  could count them. Found by rehearsing the launch against a real database, where the receipt
  said 4 files and 8 left the disk.
- **The bridging household could not be created in the product** — the flagship diagram in
  this README needed a Django shell. And `pod_owner`, a role the UI described as granting
  two capabilities, granted none; it is no longer offered.

### Security

- **The demo wipe deleted every pod on the instance**, not the demo ones. It was documented
  in four places as the last step before the first real invite. `Pod.objects.all().delete()`
  cascades through every post, comment, photograph, reaction and invite; the line meant to
  spare the founder was keyed to the literal username `"james"`, and another deleted auth
  accounts by first name — `sam` and `dave` are ordinary given names. Replaced with a
  marked, previewable `manage.py wipe_demo_data` that refuses rather than guesses.
- **The seed created an instance admin on anyone else's box.** With no user named `james`
  it made one, gave it `INSTANCE_ADMIN`, left it unmarked so no wipe removes it, and printed
  its password. The operator is now whoever holds `is_superuser`.
- Seven things the live edge handed an unauthenticated stranger: a fallback response that
  skipped every security header while advertising the server, the static build manifest,
  `Via: 1.1 Caddy` re-announcing what `-Server` had just removed, and no compression on any
  response — worst on the elder page, the surface most likely to be read over a slow phone.
- `WHITENOISE_ALLOW_ALL_ORIGINS` off; slowloris timeouts and a hard request-body ceiling at
  the edge; an RFC 9116 `security.txt` served from Caddy so it stays reachable when the app
  is down.
- SPF, DMARC and CAA records, whose absence is only visible once abused.
- A cloud project id and a DNS zone id were on public `main`.
- The secret-scanning config had three allowlists whose descriptions named a scope they did
  not have. A top-level allowlist without `targetRules` is global in gitleaks 8 — including
  over the provider-key rules.

### Changed

- **Gates that could not fail were rewritten to fail.** The runbook command check used a
  substring where it meant "this command parses". The documented-version check exempted
  every reference it was meant to compare. The reachability check was a hand-maintained
  list of three route names, checked one hop, so links inside the orphaned cluster
  satisfied it. Nothing in the repository read `ci.yml`, so deleting a scan step left the
  job green — and the guard added for that was itself satisfiable by a comment mentioning
  the tool.
- **A reachability crawl that follows links and reads what they answer.** It walks the nav
  graph from the feed, follows each offered link once, and fails on any that refuses — a
  403 behind a rendered control is a link that lies.
- **The isolation registry proves coverage instead of describing it.** Every model it calls
  covered now has a probe that runs against a real two-yard topology, each carrying its own
  denominator so a probe that sees nothing cannot report perfect isolation.
- `make check` runs the gates and secret-scan jobs it claimed to mirror; `make e2e` is
  separate, because the browser lane is deselected by default and a local green had been
  reporting a subset as the whole.
- The delegate runbook opens with the instance URL, the sign-in step, and the precondition
  that you must be made an admin first — it previously contained no URL at all.
- **The DCO rule is enforced rather than asserted.** `CONTRIBUTING.md` said every commit
  must be signed off; 85 of the first 154 were not. History cannot be fixed without rewriting
  every SHA, so the check covers what a pull request adds, and CONTRIBUTING now says which is
  which instead of leaving a reader to find out from `git log`. A clean merge commit is
  exempt — the platform's update-branch creates one nobody can sign — but only when it
  introduces nothing of its own, so an evil merge cannot carry unsigned work through.
- `docs/OUTSTANDING.md` records what is still open, including what this release does not
  fix.

## [0.1.1] — 2026-08-05

Everything here is a correction, not a feature. `v0.1.0` is **withdrawn**: install this one.

### Security

- **A bridging post leaked the other side of the family, photographs included.** The audience
  query filtered comments and reactions by *post* visibility alone, so on a post addressed to
  both sides a single-yard member received the other side's replies and the images attached to
  them. Fixed inside the one audience query. This is the defect that makes `v0.1.0` withdrawn
  rather than merely superseded.
- **A yard admin could mint a credential wider than their own reach** — an elder link for a
  member of a pod they were not in.
- **`DEBUG` could boot on a public host**, and setting it disabled the guard meant to prevent
  exactly that.
- **Pre-flight database dumps are encrypted** when a backup passphrase is set. They were
  written in plaintext on every container start, three deep.
- **`cryptography` is a declared dependency and pinned past `PYSEC-2026-3552`.** The backup
  guarantee previously rested on a transitive dependency of an MFA extra.
- Log redaction now covers the password-reset key; Pillow's format allowlist runs *before* the
  decode; ffmpeg no longer inherits the environment; a malformed multipart message is rejected
  instead of becoming a 500 and a provider retry loop.

### Fixed

- **The digest could not be switched on by anybody.** `/settings/digest/` was routed and
  linked from nowhere, so the only notification channel the product has was unreachable — and
  the weekly health email, which needs a confirmed subscription, was reaching nobody.
- **An invite-joined member had no way back in.** The join form collected no address, so
  password reset had nothing to send to and said "check your inbox" regardless.
- **The decommission runbook destroyed data.** It documented a flag the command does not
  accept, one step before `docker compose down -v`.
- The restore drill could not run — it untarred an archive that is encrypted by default.

### Changed

- Backup and restore are exercised end to end in CI against a real Postgres, not stubs.
- The demo family is fully invented; no real relative's name appears.
- Fonts ship with their licence text (SIL OFL 1.1).

[0.1.4]: https://github.com/AIJSAI/backyard/tree/v0.1.4
[0.1.3]: https://github.com/AIJSAI/backyard/tree/v0.1.3
[0.1.2]: https://github.com/AIJSAI/backyard/tree/v0.1.2
[0.1.1]: https://github.com/AIJSAI/backyard/tree/v0.1.1

## 0.1.0 — 2026-07-29 (withdrawn)

The first fixed point. **Pre-release: it runs, and it has not been handed to a family yet.**
The author's own QA walk ([`docs/runbooks/founder-qa.md`](docs/runbooks/founder-qa.md)) is the
gate, and it has not happened. Treat this as "reproducible enough to read and try", not
"trusted with your family's photographs".

### What works

- **Pods and yards.** Every household is a pod; each side of the family is a yard with its own
  shared feed. A household can belong to both sides without fusing them, and cross-yard access
  answers a byte-identical 404 — no existence signal.
- **A feed that ends.** Chronological, no algorithm, no engagement mechanics. Links, photos,
  video, short updates, comments, one reaction.
- **The elder path.** One link, no account, no app store. Large single-column type with a
  bigger-text toggle. Photos and video are reachable through it.
- **Photos and video.** Client-side resize, server-side re-encode, metadata stripped at ingest,
  every byte served through one access-checked path. Photos and clips work on replies too, so a
  wedding is one thread rather than a scatter of posts.
- **Email digest, out and in.** A weekly per-yard digest built through the same audience query
  as the web feed. Replying to a digest opens the app at the thread.
- **Installable PWA** on iOS and Android, no store.
- **The family directory.** Profiles with per-field visibility (nobody / my pods / my yards),
  birthdays as month-and-day with no year and no age ever, and vCard download so the numbers in
  your phone stop being stale.
- **Admin that a non-technical person can hold.** Five documented roles with the permissions
  written beside the control, household invites, member removal that asks what happens to their
  posts, single-item takedown, break-glass recovery.
- **Export.** Every member can download everything they authored, always, ungated.
- **Encrypted backups** with a restore that ends in a forced security replay, so a restore
  never resurrects a removed member's credentials.
- **A weekly health email** reporting last-backup age, disk headroom and domain days-remaining
  — and reporting `NOT MEASURED` for the two it genuinely cannot see, rather than omitting them.
- **Handover and shutdown runbooks**, with a `decommission_instance` command that exports for at
  least two named people *before* it revokes anything.
- **Accessibility.** WCAG 2.1 AA and 2.2 AA across 34 surfaces, verified with axe in a real
  browser at desktop and mobile, light and dark, including a deliberate hover pass. Forced-colors
  and `prefers-contrast` supported.

### What does not work yet

- **Reply-by-email needs one manual step.** Until the inbound webhook is registered with the
  mail provider, a reply is accepted with a `250` and silently goes nowhere. See
  [`self-host.md`](docs/runbooks/self-host.md).
- **The ambient photo-frame display (S-603) is not built.** It is the one unbuilt story.
- **Push notifications are out of scope** for 0.x, by decision — the digest is the notification.
- **No published container images.** You build from source with `docker compose`.
- **One instance has ever been deployed**, by the author. Hardware beyond a 2-vCPU Ubicloud VM
  is untested, and no NAS platform has been tried.
- **No independent security review.** The threat model is thorough and entirely self-authored.

### Security

- Credential literals removed from the seed and capture tooling. `scripts/demo_seed.py` carried
  a fixed password that **worked on the live instance**, in a public repository; it is now
  generated per run and printed once. Two more copies of the same mistake, hidden in
  `os.environ.get(KEY, "literal")` fallbacks, went with it. gitleaks had reported the history
  clean and was right by its own rules — it matches provider-shaped keys, not the password a
  person picks — so the enforcing check is now an `ast` guard,
  `src/core/tests/test_no_hardcoded_demo_credentials.py`.
- Baseline Content-Security-Policy with a nonce for the few inline scripts; `script-src` is not
  `unsafe-inline`.
- Every bearer credential is at least 128-bit CSPRNG, stored only as a hash, and anchored to a
  per-member generation so one revocation kills every derived credential on its next use.
- Dependency CVE scanning, SAST and secret scanning run on every push.

<!-- Points at the tag's tree rather than a Releases page: a bare annotated tag always renders
     here, whereas /releases/tag/ depends on a Release object existing, and publishing GHCR
     images and formal releases is still Phase 5 work. -->
<!-- 0.1.0 deliberately has NO link. The tag was deleted when the release was withdrawn, so
     /tree/v0.1.0 404s -- and repointing it at the commit the tag named would hand a reader a
     working path to the tree the withdrawal exists to take away, burned credential and
     cross-yard disclosure included. The notes below stay as history; the way in does not. -->
