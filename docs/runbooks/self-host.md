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
  printed QR code, every bookmarked elder link and every link in an old digest points at
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

## 2. Configure

```bash
git clone https://github.com/AIJSAI/backyard.git
cd backyard
cp .env.example .env
```

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

## 3. Start it

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Four containers come up: Caddy (TLS), Postgres, the web app, and a worker. On first boot
the entrypoint generates the secret key, runs migrations as a DDL-only role, collects
static files, and prints a **one-time setup URL**:

```bash
docker compose logs web | grep -i "setup"
```

Open it and create the first instance admin. That URL is single-use and dies with the
first admin account — there is no default login to forget about.

## 4. Make it a family

As instance admin, at `/members/`:

1. **Create a yard** per side of the family ("The Whitfields", "The Ferraras").
2. **Create a pod** per household, and attach it to the yard(s) it belongs to. A household
   that bridges two sides belongs to both — its members see both, and the two sides never
   see each other.
3. **Invite people.** Each invite is a single-use link.
4. **For anyone who will not manage an account** — grandparents, usually — mint an
   **elder link** on their member page. It is a URL that logs them in by itself, forever,
   until you revoke it. Print the QR code and put it on the fridge.

---

## Email

**Read this before you promise your family anything.**

Out of the box, Backyard sends **no email at all** — the console backend prints messages to
the container log. That is a working configuration: the app is fully usable without email.
You lose the weekly digest and reply-by-email.

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

> **If you skip the webhook registration, inbound replies fail SILENTLY.** The mail server
> accepts the message with a 250, the sender gets no bounce, and it never reaches the app.
> After your first digest goes out, check that replies actually arrive before telling
> anyone the feature exists.

### Deliverability

Family email to Gmail addresses from a new domain lands in spam until the domain has a
reputation. Set SPF, DKIM and DMARC. Ask the first few people to mark it "not spam".

---

## Backups

**Take one before you need one, and test restoring it.**

```bash
# Keyfile, not an inline variable: an inline one lands in your shell history.
printf '%s' 'four random words you can write down' > /root/backyard.key
chmod 600 /root/backyard.key

docker compose exec -T web python manage.py backup_instance \
  /data/backups/backup-$(date +%F).bak --passphrase-file /root/backyard.key
```

Backups are **encrypted by default**; the command refuses to write plaintext unless you
pass `--no-encrypt`. **There is no key escrow.** Lose the passphrase and the archive is
gone — fill in [backup-recovery-sheet.md](backup-recovery-sheet.md), print it, and keep it
somewhere that is not the same building as the server.

Copy the archive off the box. A backup on the same disk is not a backup.

Restoring is [backup-restore.md](backup-restore.md). A restore is a **security event**: it
kills every elder link, digest link and session the backup carried, because a restore can
otherwise resurrect the credentials of someone you removed.

---

## Upgrades

```bash
cd backyard
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The entrypoint takes a pre-flight database dump **before** any migration and refuses to
migrate if that dump fails, so a broken upgrade cannot take the data with it. The last
three are kept on the data volume.

Read the release notes before pulling. This is pre-1.0: it is not yet promised that every
upgrade is seamless, only that your data survives it (there is a CI guard that migrates a
database seeded at the oldest schema all the way to head).

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

---

## What does not work yet

Stated plainly, because finding out later is worse:

- **Inbound reply-by-email is Resend-only.** SMTP covers outbound only.
- **No web push.** The notification opt-in sends **email**, not a push notification.
- **No native apps.** It is an installable PWA; add it to your home screen from the
  browser. That is a deliberate decision, not a gap ([ADR-002](../adr/ADR-002-stack.md)).
- **Video is transcoded one clip at a time**, and on a small box a long clip takes minutes.
  The post appears immediately and the video fills in.
- **Profiles are thin.** Names, kinship names, birthdays and contact fields with per-field
  visibility — but no profile photo and no work/school history yet.
- **Pre-flight migration dumps are plaintext** on the data volume. They exist to save a
  failed migration, when nothing can be holding a passphrase.

The current, deliberately harsh list is
[the self-audit](../audits/2026-07-26-honest-100-audit.md).

---

## Getting help

Open an issue. Include `docker compose ps`, the relevant log lines, and what you expected —
and please redact any URL containing a token before pasting it, since those are credentials.
