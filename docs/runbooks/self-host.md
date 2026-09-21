# Self-hosting Backyard

A private family network on a machine you control. This is the whole install: DNS, TLS,
first admin, email, backups, upgrades — and an honest list of what does not work yet.

Nothing here is aspirational. Every command is one this repo's own deploy runbook and CI
exercise. Where something is unfinished, it says so rather than being left out.

---

## What you need

- **A Linux box with a public IP.** Two vCPU and 2 GB RAM is comfortable for a family of
  40. Video transcoding is the only hungry part, and it runs one job at a time on purpose.
- **A domain name** you can point at that box. Backyard serves one domain.

  **Treat the domain as a family asset, not a subscription** (threat row T-OP-G4). Every
  printed QR code, every bookmarked no-login link and every link in an old email update points at
  this hostname, and a bearer URL cannot tell your host from the next one — so if the
  registration lapses, whoever re-registers it inherits *working* credentials and can stand
  up a convincing phishing surface plus your family's mail. That is the single worst
  outcome available to a self-hoster here, and it happens by forgetting rather than by
  attack. So, at registration time and not later:

  | | |
  |---|---|
  | Auto-renew | **on**, with a payment method that outlives one person's expiring card |
  | Term | **multi-year**, not annual |
  | Registrar lock | **on**, so no transfer happens unasked |
  | Account access | **two people**, not one |

  The instance watches it for you: the weekly health email reports **domain days-remaining**
  and flags it inside 45 days. Write the registrar, the login and the renewal date on the
  [succession sheet](backup-recovery-sheet.md).
- **Docker** with the Compose plugin.
- **~4× your media in disk.** The instance holds your photos, a backup holds them again,
  and a restore stages a third copy briefly.

You do **not** need: an app store account, a Google or Apple developer account, a CDN, or
an email provider (see [Email](#email) — the honest part).

---

## 1. DNS

Point an `A` record at the box before you start; Caddy fetches a certificate on first boot
and needs the name to already resolve.

```
backyard.example.com.   A   203.0.113.10
```

### Three more records, and why they matter here specifically

Skip them and nothing breaks — which is the problem. These are records whose absence stays
invisible until someone abuses it.

```
; This domain sends no mail (your provider's subdomain does). Say so.
backyard.example.com.          TXT   "v=spf1 -all"

; Tell receivers what to do with mail that forges your domain.
_dmarc.backyard.example.com.   TXT   "v=DMARC1; p=reject; sp=quarantine; adkim=r; aspf=r"

; Only these CAs may issue certificates for you.
backyard.example.com.          CAA   0 issue "letsencrypt.org"
backyard.example.com.          CAA   0 issue "sectigo.com"
```

**DMARC is the one that matters most for this product**, and not for the usual deliverability
reasons. The elder path is *a link in an email*: Nana taps what arrives and she is in, with no
password to get wrong. That design is the whole point — and it means a convincing forged email
from your family's domain is the single most effective attack against it. Without a DMARC
policy, a receiving mail server has nothing telling it to reject that forgery.

`p=reject` on the apex is free if, like the default setup here, the apex sends nothing.

**`sp=` covers every subdomain**, not just the one that sends — any subdomain without its own
`_dmarc` record inherits it. That is why it is `quarantine` and not `reject` here: if
alignment turns out imperfect anywhere, a real digest lands in spam rather than being
destroyed, and your family's only notification channel is a poor thing to bet on an untested
assumption. A subdomain can override with its own `_dmarc.<subdomain>` record if you want
different policies for different senders.

Tighten to `reject` once you have seen a real message pass — add `rua=mailto:...` to collect
reports first, on an address you are willing to publish, because that record is public.

**Both CAA lines, not just Let's Encrypt.** Caddy tries Let's Encrypt and falls back to
ZeroSSL, whose CA is Sectigo. Authorising only Let's Encrypt works fine until the day it
fails over — and then issuance is blocked by your own CAA record and the site loses TLS,
weeks after you wrote the record and with no obvious connection to it.

If your DNS is on Cloudflare with Universal SSL, expect `dig CAA` to return more issuers than
you added; Cloudflare injects its own so its certificates keep working. That is still a
restricted set rather than "any CA on earth", which is what you have with no CAA at all.

## 2. Configure

```bash
git clone --branch v0.2.0 https://github.com/AIJSAI/backyard.git
cd backyard
cp .env.example .env
```

**Clone the tag, not `main`**, exactly as the README says. `main` changes daily and may be
mid-refactor when you arrive. This step used to clone `main` while every other document
insisted on a tag; the two disagreed, and the one an operator actually runs was the wrong one.

Edit `.env`. The three database passwords have **no defaults** — compose refuses to start
until you set them, deliberately, so an instance can never come up on a shipped credential:

```bash
POSTGRES_PASSWORD=$(openssl rand -base64 30)
POSTGRES_MIGRATOR_PASSWORD=$(openssl rand -base64 30)
POSTGRES_APP_PASSWORD=$(openssl rand -base64 30)

BACKYARD_DOMAIN=backyard.example.com
ACME_EMAIL=you@example.com          # Let's Encrypt expiry notices
BACKYARD_BACKUP_PASSPHRASE=...      # see Backups; there is no key escrow
```

You never set `DJANGO_SECRET_KEY`. The container generates one on first boot and persists
it on the data volume.

### Your time zone

```bash
BACKYARD_TIME_ZONE=America/Chicago   # an IANA name; the default is UTC
```

**Set this.** It is the clock your family reads. Left unset, every date and time in the
product — the feed, a thread, an invite's last day, Email Updates — is stated in UTC,
which for most families is several hours wrong and says so with no hedge. A post written
at 4:28 in the morning read "9:28 a.m." on a real instance before this setting existed.

Use an IANA name (`America/Chicago`, `Europe/London`, `Australia/Sydney`) - a country or
a city on its own is not one, so `America/Seattle` and `CST` are both typos.

**A bad value is a boot failure, by design.** The app refuses to start, with a message
naming this variable, rather than booting and printing wrong times: a wrong zone is a
wrong fact on every screen, and a container that will not come up is the cheaper failure.
So check it before `docker compose up`, not after:

```bash
python3 -c 'import zoneinfo; zoneinfo.ZoneInfo("America/Chicago")'
```

Silence means the zone is good; a `ZoneInfoNotFoundError` means fix `.env` first. The full
list your machine knows:

```bash
python3 -c 'import zoneinfo; print(sorted(zoneinfo.available_timezones()))'
```

Signed-in relatives in a *different* zone do not need anything: each page also carries the
instant in the markup, and their own browser re-renders it into their own zone. This
setting is what an e-mail uses, because an e-mail is written here and read hours later
with no browser to correct it — so it should be the zone the household lives in.

Changing it later is safe: nothing is stored in local time (every timestamp is stored in
UTC), so this only changes how they are shown. Restart the containers to pick it up.

## 3. Start it

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Four containers come up: Caddy (TLS), Postgres, the web app, and a worker. On first boot
the entrypoint generates the secret key, runs migrations as a DDL-only role, collects
static files, and writes a **one-time setup secret** to a file on the data volume that
only the container's own user can read. Read it with:

```bash
make setup-secret
# or, without make:
docker compose exec web cat /data/first-run-secret
```

Open `https://your.domain/setup/`, paste it, and create the first Family Admin. The
secret is single-use, it is replaced on every boot until it is used, and both it and the
file are deleted the moment the first admin exists — there is no default login to forget
about.

It is deliberately **not** printed to the container log. Compose uses the json-file
logging driver, so anything printed at boot is written to disk, replayed by
`docker compose logs`, and kept through rotation; a one-time instance-takeover credential
does not belong there. Set `SETUP_HANDOVER_FILE` if you want it somewhere other than
`/data/first-run-secret`.

## 4. Make it a family

As the Family Admin, from the **Members** link in the header (or `/members/`):

1. **Create a side of the family** ("The Whitfields", "The Ferraras") — **Sides**.
2. **Create a household and invite it in one step** — **Invite A Household**. Creating the
   pod and minting its invite is the same action; there is no separate "create a pod" step,
   which is why step 2 used to have no referent.

   Tick **both** sides for a household that bridges them. Its members see both, and the two
   sides still never see each other through it. (Until 2026-08-06 the form offered one side
   only, so the bridging household — the case this whole model is built around — could be
   created only from a Django shell.)
3. **Send the link.** One invite covers a whole household: up to 8 joins, for 7 days.
   It is **not** single-use; this document said it was, and
   `docs/runbooks/setting-up-your-side.md` said the opposite. The code is `invites.py`:
   `max_uses = 8`, 7-day expiry.
4. **For anyone who will not manage an account** — grandparents, usually — make a
   **No-Login Link**: **Members**, then **Manage** on their row. It is a URL that logs them
   in by itself, forever, until you revoke it. Print the QR code and put it on the fridge.

---

## Email

**Read this before you promise your family anything.**

Out of the box, Backyard sends **no email at all** — the console backend prints messages to
the container log. That is a working configuration: the app is fully usable without email.
You lose the weekly Email Updates and reply-by-email.

### Option A — your own SMTP server

```bash
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=backyard@example.com
EMAIL_HOST_PASSWORD=...
EMAIL_USE_TLS=1        # for 465, set EMAIL_USE_SSL=1 and EMAIL_USE_TLS=0
DEFAULT_FROM_EMAIL=backyard@example.com
```

The app refuses to boot with an SMTP backend and no host, rather than silently dropping
every message. If it crash-loops, read the log — it says which variable is missing.

**The honest limitation: this is OUTBOUND only.** Reply-by-email (a family member replying
to a digest and having it land as a comment) needs a provider that posts an inbound
webhook, and today the only wired one is Resend. With SMTP alone the digest sends and
replies happen on the web.

### Option B — Resend (also does inbound)

```bash
EMAIL_BACKEND=anymail.backends.resend.EmailBackend
RESEND_API_KEY=...
RESEND_INBOUND_SECRET=...
DEFAULT_FROM_EMAIL=backyard@mail.example.com
```

Then, in the Resend dashboard: verify the sending domain (SPF + DKIM), add the inbound MX
record, and register an `email.received` webhook pointing at
`https://your-domain/anymail/resend/inbound/`.

> **If you skip the webhook registration, inbound mail fails SILENTLY.** The mail server
> accepts the message with a 250, the sender gets no bounce, and it never reaches the app.
> Check that inbound actually arrives before telling anyone the feature exists.

**What inbound does and does not give you today, precisely.** The route is only mounted when
the inbound secret is configured — on an SMTP or console instance it does not exist at all,
rather than answering every unauthenticated POST with a 500. When it is mounted, a message is
attributed from the address the provider says it was **delivered to** (`data.received_for`),
never from the sender-written `To:` header, and a delivery naming more than one recipient is
refused rather than resolved to its first address. The fetch that collects the message is
bounded in bytes **and** in wall-clock time, so a slow or enormous message cannot occupy the
app. A refused message is not lost: it lands on **Members → Held Replies** with
the reason.

**But nothing currently hands a family member an address to use it with.** The weekly email
used to print a per-post reply address in every body; that address is a bearer credential, so
printing it forwarded the ability to comment as you along with the email, and it was removed.
There is no `Reply-To` header either. What each post carries instead is a **"Reply in
Backyard"** link straight to that thread's reply box, which carries no capability and takes
photographs. So the inbound pipeline is live, tested and worth configuring — and reply-by-email
is not a feature your family will use this release. Set inbound up if you want the capability
present; do not promise anyone they can answer the email.

### Deliverability

An email update to a Gmail address from a new domain lands in spam until the domain has a
reputation. Set SPF, DKIM and DMARC. Ask the first few people to mark it "not spam".

---

### The name and the address on your mail

```bash
BACKYARD_MAIL_FROM_NAME=Backyard        # or your family's name
DEFAULT_FROM_EMAIL=backyard@mail.example.com
```

Every message this instance sends carries the name, including the address confirmation —
often the first thing the software ever sends anybody. Without it, mail arrives as the bare
address, or as just the part in front of the `@` in the clients that shorten it, which is
how a family's own photographs come to look like something a spam filter should eat.

**Name the address after the product, not after the job that sends it.**
`backyard@<your mail domain>` is the one to use. That first word is what a shortening client
shows and what a relative reads before deciding whether to open anything, and the messages
it now carries are the password reset and the address confirmation as much as the weekly
update. Changing the part in front of the `@` is safe at any time. Changing the DOMAIN is
not the same move: `emailing.reply_domain()` derives the reply-by-email domain from this
setting, so a new domain means new reply addresses and inbound routing to re-point. Either
way, messages already sitting in somebody's inbox keep the old sender, so do it before you
invite people.

## Notifications on a phone

**Optional, and off until you do this.** With no keys set, the Notifications page in
Settings says notifications are not set up on this Backyard, nothing is sent, and nothing
else about the instance changes. A family that is happy with the weekly email update can
skip this section entirely.

Web push signs every notification with an **application-server key pair** (VAPID, RFC
8292). The pair identifies this instance to Apple's, Google's and Mozilla's push services.
It is not a per-member secret and it never goes in the database. Generate one **on the
box**, so no private key is ever pasted into a chat window or a browser:

```bash
docker compose exec -T web sh -c 'export DJANGO_SECRET_KEY=$(cat /data/secret_key); python manage.py generate_vapid_keys'
```

It prints three lines and writes nothing. Paste them into `.env`, set the subject to an
address you read, and rebuild:

```bash
BACKYARD_VAPID_PUBLIC_KEY=...
BACKYARD_VAPID_PRIVATE_KEY=...
BACKYARD_VAPID_SUBJECT=mailto:you@example.com
```

The subject is **required** once the keys are set, and it has to be a `mailto:`. It is how
a push service contacts you about this instance, and Apple's refuses a notification that
does not carry one — so an instance with keys and no subject would work on Android and
fail silently on every iPhone in the family. Setting one half of the pair and not the
other **refuses to boot**, with a message naming the variable: a working-looking Turn On
Notifications button whose notifications can never arrive is worse than no button.

Then restart both services, because the worker is what sends:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

**One worker sends everything.** The compose worker runs a single process at concurrency
1 across every queue, so a push service that stops answering would otherwise hold the
transcodes, the email updates and the nightly backup behind it. A whole fan-out is
therefore budgeted at two minutes; past that the remaining phones are skipped for that
one post and picked up by the next one. Nothing is deleted and no device is penalised for
a slow service.

**What a relative does.** Settings, Notifications, Turn On Notifications, then the phone's
own permission prompt. On an **iPhone this only works inside the home-screen app** — Apple
grants web push to an installed web app and not to a Safari tab — so the install comes
first (`/app/` in the product, "Get The App"). The page says so and offers the link when
the browser cannot do it. Each device is listed with a Remove button, signing out on a
device removes that device, and the two toggles are New Posts and Replies.

**What the push services see.** An endpoint, a size and a time. The notification body is
encrypted to the device's own key (RFC 8291), so the words are not readable by Apple,
Google or Mozilla. What a notification DOES show is a first name and the first words of a
post, on a lock screen, to whoever is holding the phone.

**Rotating the pair signs every device out of notifications.** A registration is bound to
the key it was made with, so after a rotation every push is refused, every stored
subscription is dead, and each relative turns notifications on again from Settings. Do it
if the private key is exposed; there is no reason to do it otherwise.

**Extending the list of push services** is `BACKYARD_PUSH_SERVICE_HOSTS`, a comma-separated
list of hostnames that is ADDED to the built-in set (Apple, Google, Mozilla, Microsoft).
You need it only if you run your own push relay. Leave it unset otherwise: the list is
what stops a device from asking this server to make an HTTP request to an address of its
choosing.

## Backups

**Take one before you need one, and test restoring it.**

You already set `BACKYARD_BACKUP_PASSPHRASE` in `.env` above, and compose passes it
into the container — so a backup is one command with no secret on it:

```bash
docker compose exec -T web sh -c \
  'DJANGO_SECRET_KEY=$(cat /data/secret_key) \
     python manage.py backup_instance /data/backups/backup-$(date +%F).bak'
```

The archive path is **positional**; there is no `--output` flag.

Never assign the passphrase inline in front of a `docker compose` command — that lands
in your shell history and in every process listing. Set it in `.env`, or use a keyfile.

A keyfile is tighter than the env var, because the env value is visible to
`docker inspect`. The path is read **inside** the container, so mount it read-only — and
never onto `/data`, which is the volume the archives live on: a key beside the ciphertext
is not encryption, and a stolen disk or provider snapshot would carry both.

```bash
printf '%s' 'four random words you can write down' > /root/backyard.key
chmod 600 /root/backyard.key        # every reader refuses a group/world-readable key

# Mount it into BOTH containers (docker-compose.prod.yml), and name it in .env:
#   web:    volumes: [ "/root/backyard.key:/run/secrets/backyard.key:ro" ]
#   worker: volumes: [ "/root/backyard.key:/run/secrets/backyard.key:ro" ]
#   .env:   BACKYARD_BACKUP_PASSPHRASE_FILE=/run/secrets/backyard.key
#
# Both containers, because both encrypt a copy of everything: the worker takes the nightly
# archive, and web's entrypoint dumps the whole database before every migration. With the
# variable set, this command needs no flag; --passphrase-file still overrides it.
docker compose exec -T web sh -c \
  'DJANGO_SECRET_KEY=$(cat /data/secret_key) \
     python manage.py backup_instance /data/backups/backup-$(date +%F).bak'
```

Backups are **encrypted by default**; the command refuses to write plaintext unless you
pass `--no-encrypt`. **There is no key escrow.** Lose the passphrase and the archive is
gone — fill in [backup-recovery-sheet.md](backup-recovery-sheet.md), print it, and keep it
somewhere that is not the same building as the server.

Copy the archive off the box. A backup on the same disk is not a backup.

Restoring is [backup-restore.md](backup-restore.md). A restore is a **security event**: it
kills every no-login link, email-update link and session the backup carried, because a restore can
otherwise resurrect the credentials of someone you removed.

---

## Upgrades

```bash
cd backyard
git fetch --tags
git checkout v0.2.0          # or whichever tag CHANGELOG.md says you want
docker compose -f docker-compose.yml -f docker-compose.prod.yml build --pull \
  && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

**`build --pull`, as a separate step — chained to the `up`.** `up -d --build` builds from
whatever base image the box already has cached, and the app image installs two long-lived
binaries on top of that base — the `pg_dump` client that takes your pre-flight backup, and
the `ffmpeg` that decodes video somebody sent your family. Neither layer is reached by a
change to the app, so without `--pull` they stay at the versions of the day you first built,
however many times you upgrade. `--pull` re-resolves the base tag and rebuilds them whenever
upstream has published a new `python:3.13-slim` since your last build — which is most months,
but not every time; `up -d --build` never does, and `up` has no flag that does (its `--pull`
is about pre-built images, not about your build). If the base has NOT moved and you need the
binaries refreshed anyway — you are acting on a Debian `ffmpeg` or PGDG client advisory —
`build --pull --no-cache` is the only command that forces it. Keep it for exactly that case
and for chasing a broken layer: it also discards the Python dependency layer and turns a
one-minute upgrade into several.

The `&&` is not decoration. `up --build -d` was one command, so a failed build started
nothing; two unchained lines let a failed build be followed by an `up -d` that quietly
starts the image you already had.

**Not `git pull`.** You cloned a tag, so you are on a detached HEAD, and this is not a
detail — it is the difference between upgrading and believing you upgraded. Both shapes
were run against this repository to check:

| what you cloned | `git pull` does |
|---|---|
| `git clone --branch <tag> …` (what the README tells you to run) | fails: *"You are not currently on a branch."* |
| the same with `--depth 1` | prints **"Already up to date"** and does nothing, forever — the fetch refspec is narrowed to `+refs/tags/<tag>:refs/tags/<tag>`, so there is nothing else it can even see |

The second is the dangerous one: an operator runs it, is told they are current, and stays
on the version they installed for as long as the instance lives. `git fetch --tags` plus an
explicit `git checkout` says out loud which version you are moving to, which is also what
the release notes are for.

The entrypoint takes a pre-flight database dump **before** any migration and refuses to
migrate if that dump fails, so a broken upgrade cannot take the data with it. The last
three are kept on the data volume.

Read the release notes before pulling. This is pre-1.0: it is not yet promised that every
upgrade is seamless, only that your data survives it (there is a CI guard that migrates a
database seeded at the oldest schema all the way to head).

### One-off, if your instance predates 2026-07-30

Postgres runs the scripts in `postgres/initdb/` **only when it initialises an empty data
directory**. So role-level settings added after your instance was created never reach it,
and pulling alone will not apply them. There is exactly one so far -- a query timeout that
stops a pathological query wedging every worker:

Note the `sh -c`. `$POSTGRES_USER` and `$POSTGRES_DB` exist **inside the container**, not in
your shell: compose reads `.env` for its own substitution and does not export those into your
session, so the obvious-looking version runs `psql -U ""` and fails confusingly. Verified on a
real box — `echo $POSTGRES_USER` on the host prints nothing; inside the container it prints
the user. `ON_ERROR_STOP=1` so a failure cannot be mistaken for success.

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
  sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    ALTER ROLE backyard_app SET statement_timeout = '"'"'15s'"'"';
    ALTER ROLE backyard_migrator SET statement_timeout = 0;"'
```

Check it took -- an upgrade step nobody verifies is an upgrade step nobody did:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
  sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
    "select rolname, rolconfig from pg_roles where rolname like '"'"'backyard_%'"'"';"'
# backyard_migrator|{statement_timeout=0}
# backyard_app|{statement_timeout=15s}
```

A fresh install gets this automatically and needs nothing.

### Let the operating system patch itself, and choose the reboot hour

Docker keeps the app's dependencies; nothing keeps the host's. Turn on unattended security
upgrades and pick the reboot window **deliberately** — it is the one moment the instance goes
down without you in front of it:

```bash
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades
# then, in /etc/apt/apt.conf.d/50unattended-upgrades:
#   Unattended-Upgrade::Automatic-Reboot "true";
#   Unattended-Upgrade::Automatic-Reboot-Time "09:00";
```

That time is **UTC**, like everything else on the box, so work out what it is where your
family lives before choosing it. Watched end to end on the reference instance: upgrades
installed at 06:47, reboot at the 09:00 window onto a new kernel, all four containers back
healthy with nobody touching it.

**One `web` restart right after a reboot is expected.** On a boot where the app wins the race
against Postgres, the pre-flight database dump fails, the entrypoint refuses to migrate and
the container exits 1 — which is the guard working — and the next attempt succeeds seconds
later. It is not a crash loop unless it keeps going, and the log names the dump's own error.

---

## Rate limits on the unauthenticated surfaces

Every page that can be opened with a link and no password — the elder page, the family
email's web version, the join and get-back-in pages, break-glass and the two digest
confirm/unsubscribe pages — is bounded at **240 opens and 60 actions per 10 minutes per
address**, on `GET` as well as `POST`. Over the limit, the visitor gets the product's own
calm "too many requests" page rather than a bare error.

Two things worth knowing before you read a support message about it. The limits are generous
on purpose: a whole household behind one home connection is one address, and a grandmother
refreshing because she is not sure it worked is perhaps twenty requests. And `/media/` is
excused by name — an elder's page pulls many photographs in a burst, and the audience check
on every byte is the control there, not a counter.

Both the app's limits and the sign-in limits share one store, the database cache table, so
they hold across all three web processes and survive a restart. That is deliberate: a
per-process limiter gives an attacker three times the attempts and a clean slate on every
deploy.

---

## Monitoring

There is no metrics stack, and for a family instance that is a deliberate choice rather
than an omission. What exists:

```bash
docker compose ps                    # all four containers healthy?
docker compose logs -f web           # request errors
docker compose logs -f worker        # transcodes, digest sends
df -h                                # the thing that actually bites: disk
```

Capability tokens are redacted from the application's logs, so a log file cannot be turned
into content access. Caddy is configured to log nothing at all for the same reason.

The one thing worth a cron job is **disk**. Photos and videos accumulate, and a full disk
stops uploads, backups and transcoding at once.

### The monitor that runs outside the box

Everything above runs *on* the instance, which means none of it speaks when the instance is
the thing that is wrong. `.github/workflows/monitor.yml` runs on GitHub's infrastructure
every 30 minutes and asks two questions from the outside: does `/healthz` answer, and how
many days are left on the TLS certificate. Point the repository variable
`BACKYARD_MONITOR_URL` (Settings → Secrets and variables → Actions → Variables) at your
instance's health URL to arm it; unset, it exits cleanly and watches nothing. What it finds
goes into **one** issue labelled `monitor-alarm` — the durable record, and the throttle that
keeps a week-long problem from becoming 48 messages a day — and the monitor closes that
issue itself when the instance is well again.

**It sends the e-mail itself, and it has to.** The issue mentions the repository owner, but
a mention is a GitHub *notification*, and whether a notification becomes mail is a setting
on that account. Rehearsed here: the issue opened, the monitor closed it on recovery,
GitHub recorded the mention — and no mail arrived, so "the instance is down" reached nobody.
The weekly health email cannot cover that case either, because a box that is down sends
nothing. So the monitor posts the alarm to Resend from the runner, outside the box, on the
two state **changes** only: once when a new alarm issue is opened (subject "Backyard Needs
Attention") and once when it closes on recovery ("Backyard Is Well Again"). The daily
reminder comment mails nothing — that is what the issue is for.

Three repository **secrets** arm that half. Secrets rather than variables: two of them are
mailbox addresses, and a variable is readable by anyone who can see a public repository.

| Secret | What to put in it |
| --- | --- |
| `MONITOR_RESEND_API_KEY` | A Resend API key with **sending permission only**, restricted to the mail domain you verified for this instance. Not your account-wide key — this one lives on GitHub, and all it ever does is send one message to one address. |
| `MONITOR_ALERT_TO` | Where the alarm goes: your own mailbox, not the family's. |
| `MONITOR_ALERT_FROM` | The sender, on that same verified mail domain (for example `monitor@example.com`). |

Set them with the GitHub CLI, from a checkout of your own fork. Each command prompts for the
value, so nothing lands in your shell history:

```bash
gh secret set MONITOR_RESEND_API_KEY
gh secret set MONITOR_ALERT_TO
gh secret set MONITOR_ALERT_FROM
```

With any of the three unset, the workflow behaves exactly as it did before the e-mail leg
existed and prints one line naming what to set. Nothing it prints names the key, either
address, the monitored host, or Resend's reply — only `alert e-mail sent (HTTP 200)` or
`alert e-mail FAILED (HTTP <code>)`. That matters because the Actions log of a public
repository is world-readable, and an alarm that could not be delivered is the one case that
turns the run red.

**Rehearse it before you need it**, which takes about five minutes and is the only way to
know it works:

1. Point `BACKYARD_MONITOR_URL` at a path on your instance that does not exist — the same
   host with `/healthz-rehearsal` on the end. The health half asks with `curl -f`, so a 404
   counts as no answer at all, and after five attempts over about 100 seconds the monitor
   reports the instance UNREACHABLE. The certificate half still passes, so the issue names
   exactly one problem.
2. Open the repository's **Actions → monitor** page and press **Run workflow** (or
   `gh workflow run monitor.yml`). Within a minute or two an issue titled "Backyard needs
   attention" appears, and the same words arrive in the mailbox you set.
3. Put the variable back to the real health URL.
4. Press **Run workflow** again. The issue is commented and closed, and "Backyard is well
   again" arrives.

Four things observed, and nothing about the instance touched. If step 2 opens the issue but
no mail arrives, the run's log says which of it worked: no `alert e-mail` line at all means
the secrets are not set, and `alert e-mail FAILED` with a code means Resend refused — a key
without send permission, or a `MONITOR_ALERT_FROM` on a domain it has not verified.

---

## What does not work yet

Stated plainly, because finding out later is worse:

- **Nobody can answer an email update.** The inbound pipeline exists and is Resend-only
  (SMTP covers outbound only), but no reply address is published in the mail and there is no
  `Reply-To`, so replying goes nowhere. The post blocks link into the app instead. See
  [Email](#email).
- **A second factor is offered, never required.** Passkeys, an authenticator app and recovery
  codes are available to every account and an admin with none enrolled sees one calm,
  dismissible prompt. Nothing enforces it, on purpose: on a family box the locked-out admin
  is exactly the person who does not have a server shell to recover from.
- **There is no "send the email now" button.** The worker sends what is **due** — the
  cadence has to have elapsed since confirmation or since the last window — so testing the
  email update means waiting for a window rather than forcing one.
- **Web push is off unless you set a VAPID key pair.** No keys, no notifications, and the
  Settings page says so — see [Notifications on a phone](#notifications-on-a-phone). Even
  with keys, an iPhone gets them only once Backyard is on the home screen, and there is no
  way for the server to know whether a relative ever completed that.
- **No native apps.** It is an installable PWA; add it to your home screen from the
  browser. That is a deliberate decision, not a gap ([ADR-002](../adr/ADR-002-stack.md)).
- **Video is transcoded one clip at a time**, and on a small box a long clip takes minutes.
  The post appears immediately and the video fills in.
- **Profiles are thin.** Names, kinship names, birthdays and contact fields with per-field
  visibility — but no profile photo and no work/school history yet.
- **Pre-flight migration dumps are plaintext only if you configure NEITHER
  `BACKYARD_BACKUP_PASSPHRASE` nor `BACKYARD_BACKUP_PASSPHRASE_FILE`.** Set either and the
  entrypoint encrypts them too; set neither and the instance warns on every boot that it
  just wrote an unencrypted dump of the whole database to the data volume.

The current, deliberately harsh list is
[the self-audit](../audits/2026-07-26-honest-100-audit.md).

---

## Getting help

Open an issue. Include `docker compose ps`, the relevant log lines, and what you expected —
and please redact any URL containing a token before pasting it, since those are credentials.
