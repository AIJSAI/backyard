# Backup and restore runbook (S-704, S-802)

The instance backs itself up every night without being asked (see "The nightly
backup" below). Backing up and restoring by hand is one command each, and the
round trip — back up, delete the row, restore, assert it came back — runs in CI on
every push, in the `code` job's "Compose live probe" step against a real Postgres.

**What that gate does not cover:** it exercises the code path against a real
Postgres, not *your* archive on *your* box. A backup you have never restored is
a hypothesis. Run a restore drill against a scratch instance before you need one.

## What a backup contains

One archive holds the two stateful things:

- the **database** (`pg_dump -Fc` custom-format dump), and
- the **media tree** (`MEDIA_ROOT`, every uploaded photo and derivative).

Inside, it is a tar of three members: `backup-manifest.json`, `database.dump`,
and `media.tar.gz` — but that tar is **encrypted at rest by default** (S-802),
so what lands on disk is ciphertext unless you explicitly passed `--no-encrypt`.
See "Trust and safety" below for how the passphrase is supplied.

> This paragraph used to read *"The app holds no encryption key; at-rest
> encryption is your storage layer's job."* That stopped being true when S-802
> shipped, and it is the exact sentence a prior audit caught a plaintext archive
> shipping under. If you are reading a copy that still says it, the copy is stale.

## Trust and safety

A restore archive is executed against the database as the migrator (DDL) role,
so restoring one is equivalent to handing its author a shell on the box. Only
ever restore an archive you produced and kept custody of; never a third-party or
untrusted archive. The manifest is a shape check, not a signature, so it does
not make an untrusted archive safe. Restore also clean-restores the database
before it replaces the media tree, so a mid-restore failure can leave the
database restored and the media stale; re-run the restore from the same archive
to converge. **Backups are encrypted by default (S-802).** `backup_instance` refuses to write
a plaintext archive unless you pass `--no-encrypt` explicitly, and it takes the
passphrase from `BACKYARD_BACKUP_PASSPHRASE` or `--passphrase-file` — never from
the command line, where it would land in shell history and every process listing.
There is no key escrow: **lose the passphrase and the archive is gone.** Write it
on the recovery sheet and keep that somewhere a house fire would not take with it.

The **pre-flight dumps** taken by the entrypoint before each migration are
**encrypted too, whenever `BACKYARD_BACKUP_PASSPHRASE` is set** — compose passes
it into the web container, so the process taking the dump has it.

This used to say they were "still plaintext … because nothing can be holding a
passphrase at that moment". That reasoning was wrong, and it was load-bearing: it
justified writing an unencrypted dump of the entire family database on every
container start, three copies deep, which is verbatim T-BACKUP-1 and T-MEDIA-5.

**If the passphrase is unset, the dumps are plaintext and the instance says so on
every boot.** That warning is the fix working, not a cosmetic nag. Read access to
`/data` yields those dumps whole. Set the passphrase.

## The nightly backup

The worker takes one at **03:30 every day** (`core/tasks.scheduled_backup_task`),
through the same `backup_instance` command this runbook documents — there is no
second backup implementation to drift.

- **Where:** `/data/backups/scheduled-YYYY-MM-DD.bak` on the data volume, one file
  per day. It is on the same volume as the media it archives, which is the point
  worth being uncomfortable about: see "Getting a copy off the box" below.
- **Encrypted, or nothing.** The nightly run never passes `--no-encrypt`, so with
  no passphrase set it writes **no archive at all** and records the reason. It
  does not fall back to plaintext.
- **Retention:** the last 14 days, plus the newest archive of each of the last 8
  ISO weeks. Only files named `scheduled-*.bak` are ever deleted — your own
  archives and the entrypoint's `preflight-*` dumps are not candidates.
- **Who dumps:** the worker holds no migrator password (it runs ffmpeg on
  uploaded video and must never hold DDL credentials), so the dump runs as
  `backyard_app`, which ADR-004 already grants SELECT on every table.

### When it fails

It fails loudly in three places at once, which is the whole design:

1. the **weekly health email** grows a `[!] Scheduled backup: FAILING since …`
   line carrying the reason;
2. `/healthz` answers `degraded` instead of `ok` — and the external monitor
   (`.github/workflows/monitor.yml`) turns that into mail from GitHub within half
   an hour;
3. the worker log carries it at error level:

```sh
docker compose logs --since 24h worker | grep -i "scheduled backup"
```

To see the detail without waiting for Monday's email, sign in as the instance
admin and open `/healthz` — the fields are there for an admin and for nobody
else. To run one right now rather than waiting for 03:30:

```sh
docker compose exec -T worker sh -c \
  'DJANGO_SECRET_KEY=$(cat /data/secret_key) \
     python manage.py shell -c "from core import scheduled_backup; print(scheduled_backup.run())"'
```

### Getting a copy off the box

**Nothing in the product copies a backup off the server, and that is deliberate.**
A copy step inside the container needs a credential for the destination, and that
credential would sit next to the ciphertext on the same volume — the same reason
this runbook tells you not to keep the passphrase file in `/data`. A stolen disk
or a provider snapshot would then carry both halves.

So the hook point is on the **host**, where the destination credential already
lives, outside the containers. The archives are in the `appdata` volume under
`backups/`; find its path once and put a copy step in the host's own cron:

```sh
# Where the archives actually are on this host:
docker volume inspect backyard_appdata --format '{{ .Mountpoint }}'

# Then, in the host's crontab (04:30, an hour after the instance writes one):
# 30 4 * * * rsync -a --delete <that path>/backups/ <your-backup-host>:/srv/backyard/
```

The health email's "Off-box backup age" line still reads NOT MEASURED, and it
should: the instance cannot see where you copied a file to, and a line claiming
otherwise would be the more dangerous kind of wrong (T-OP-G3).

## Back up by hand

Compose already places `POSTGRES_MIGRATOR_PASSWORD` in the web service's
environment, so you do **not** need to pass it — and passing it with `-e` puts a
database password in your shell history and every process listing, which is the
same mistake this document forbids two paragraphs above for the passphrase:

```sh
docker compose exec -T web sh -c \
  'DJANGO_SECRET_KEY=$(cat /data/secret_key) \
     python manage.py backup_instance /data/backups/backup-$(date +%F).bak'

# The passphrase never goes on the command line. The command reads
# BACKYARD_BACKUP_PASSPHRASE, which compose passes in from `.env` — that is the
# documented path and it needs no extra flag.
#
# `--passphrase-file` is the tighter option, but the path is read INSIDE the
# container, and the one place you must NOT put it is `/data`: that is the volume
# holding the archives, so a stolen disk or provider snapshot would carry the key
# next to the ciphertext and the encryption would buy nothing (T-BACKUP-1 is
# exactly that threat). Mount a host keyfile read-only instead:
#   printf '%s' 'your four-word diceware phrase' > /root/backyard.key
#   chmod 600 /root/backyard.key        # the command refuses a group/world-readable key
#   # add to the web service in docker-compose.prod.yml:
#   #   volumes: [ "/root/backyard.key:/run/secrets/backyard.key:ro" ]
#   docker compose exec -T web sh -c 'DJANGO_SECRET_KEY=$(cat /data/secret_key) \
#     python manage.py backup_instance /data/backups/backup-$(date +%F).bak \
#       --passphrase-file /run/secrets/backyard.key'
#
# The environment variable BACKYARD_BACKUP_PASSPHRASE also works (set it in .env, which
# compose passes in). It is NOT visible in `ps`, but it IS visible in
# /proc/<pid>/environ and `docker inspect` — a keyfile with 0600 is tighter.
# Typing it inline as `VAR=secret docker compose ...` puts it in your shell history:
# don't.
#
# To deliberately write a PLAINTEXT archive (it will warn, loudly):
#   ... sh -c 'DJANGO_SECRET_KEY=$(cat /data/secret_key) \
#          python manage.py backup_instance /path/out.tar --no-encrypt'
```

Then copy the archive off the box and encrypt it:

```sh
docker compose cp web:/data/backups/backup-YYYY-MM-DD.tar ./
age -r "$YOUR_AGE_PUBLIC_KEY" -o backup-YYYY-MM-DD.tar.age backup-YYYY-MM-DD.tar
```

## Restore

The nightly archives are what you will usually be restoring, so start by seeing
what is actually there rather than assuming last night's exists:

```sh
docker compose exec -T web sh -c 'ls -lt /data/backups/'
```

`scheduled-YYYY-MM-DD.bak` is the nightly one, `backup-*` is whatever you took by
hand, and `preflight-*` are the dumps the entrypoint takes before each migration
(three of them, kept for the upgrade that goes wrong, not for this).

Restore is **destructive**: it clean-restores the database (dropping existing
objects) and replaces the media tree. It refuses a database that still has
members unless you pass `--force`, so it is safe to point at a fresh box and
hard to fire by accident.

### What a restore does to things people are holding

A restore replays the database as it was. That is not the same as putting the
instance back how it was, because credentials live in the rows and people are
holding the old ones. Read this before restoring an instance the family is using —
none of it is an error, and all of it will look like one.

| What | What happens | Who notices |
|---|---|---|
| Every elder link | Dies, instance-wide | Every grandparent, at once. The page shows the shared 404 |
| Every digest deep link and reply-by-email address | Dies, instance-wide | Anyone who replies to an old email |
| Every signed media URL | Dies, instance-wide | Anyone with a photo open in a tab |
| Everyone's session | Flushed | Everybody is signed out |
| Invites minted since the backup | Gone | Whoever was mid-join |
| **Members removed since the backup** | **Come back** | The removed person and everyone who can see them |

The first four are one mechanism: a restore bumps every `Member.token_generation`,
and every derived credential carries the generation it was minted under (ADR-003
rule 3). That is deliberate — a restored database cannot know which credentials
were revoked after the backup was taken, so it invalidates all of them rather than
resurrect a capability somebody deliberately killed.

The last row is the one to plan for, and it is the reason a restore is not a quiet
operation: a backup cannot know about a removal that happened after it. If somebody
was removed under S-702 since this backup, **restoring brings them back**, with
their pods, their content and their visibility. Re-run the removal immediately
afterwards and check the roster before telling anyone the instance is up.

Mint fresh elder links for every grandparent as part of the restore, not after
somebody reports that theirs is broken.

On a fresh instance (no members yet):

```sh
docker compose exec -T web sh -c \
  'DJANGO_SECRET_KEY=$(cat /data/secret_key) \
     python manage.py restore_instance /data/backups/backup-YYYY-MM-DD.bak'

# Restore auto-detects the archive shape. An encrypted one needs the same
# passphrase; a wrong passphrase, an altered archive and a truncated one all
# refuse loudly rather than restoring a partial copy of the family's history.
#
# If a passphrase is configured and the archive turns out NOT to be encrypted,
# restore REFUSES. A plaintext archive has no integrity protection and its dump
# is executed against the database as the migrator role, so a swapped file would
# otherwise be restored without a word. Override with --allow-plaintext only for
# an archive whose provenance you are certain of.
#
# SPACE: a restore holds the media tree TWICE (staged beside MEDIA_ROOT for an
# atomic promote) plus the tar.gz and the dump. Make sure /data has room.
```

To overwrite an instance that still has data (you have decided to roll back),
add `--force`.

## The restore drill (run it on your own box, before you need it)

Prove the backup is restorable without touching live data, by restoring into a
throwaway scratch database. The migrator cannot create databases, so the
superuser (inside the postgres container) creates the scratch DB owned by the
migrator, and the migrator restores into it.

```sh
# 1. Take a backup (as above).
# 2. Create a scratch DB owned by the migrator (superuser, inside postgres).
docker compose exec postgres createdb -U "$POSTGRES_SUPERUSER" -O backyard_migrator drill_scratch
# 3. Decrypt the archive, then extract the dump from it.
#    Backups are ENCRYPTED by default, so `tar xf` on the archive itself fails:
#    it is ciphertext, not a tar. Decrypt to a temp file first.
docker compose exec -T web sh -c '
  python -c "
import os, sys
sys.path.insert(0, \"/app/src\")
from core.backup_crypto import decrypt
with open(\"/data/backups/backup-YYYY-MM-DD.bak\", \"rb\") as src, open(\"/tmp/drill.tar\", \"wb\") as out:
    decrypt(src, out, os.environ[\"BACKYARD_BACKUP_PASSPHRASE\"])
"
  cd /tmp && tar xf drill.tar database.dump
  PGPASSWORD="$POSTGRES_MIGRATOR_PASSWORD" pg_restore -h postgres -U backyard_migrator \
    --clean --if-exists --no-owner -d drill_scratch database.dump
  rm -f /tmp/drill.tar /tmp/database.dump'
# 4. Verify the data restored, e.g. member count matches the source.
docker compose exec postgres psql -U "$POSTGRES_SUPERUSER" -d drill_scratch \
  -tAc "select count(*) from core_member"
# 5. Drop the scratch DB.
docker compose exec postgres dropdb -U "$POSTGRES_SUPERUSER" drill_scratch
```

Step 3 leaves a **plaintext** copy of the whole database in `/tmp` inside the
container while the drill runs; that is why it removes both files at the end, and
why a drill belongs on a box you control rather than a shared one.

This section used to claim *"This exact drill runs green in `scripts`-driven live
verification."* There was no such script and there never had been. What is
actually verified, on every push, is the round trip in CI's `code` job — seed,
back up, delete, restore, assert — against a real Postgres. That is a narrower
claim than the one it replaces, and it is true.
