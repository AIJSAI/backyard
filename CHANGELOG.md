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

Day one for the two relatives about to be made yard admins: nobody gets locked out, and the
one control that destroys something asks first. Alongside it, the instance starts backing
itself up and telling somebody when it cannot.

### Added

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

## [0.1.2] — 2026-08-07

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
