# Backup and restore runbook (S-704, S-802)

Backing up and restoring a whole Backyard instance is one command each, and the
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

## Back up

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

Restore is **destructive**: it clean-restores the database (dropping existing
objects) and replaces the media tree. It refuses a database that still has
members unless you pass `--force`, so it is safe to point at a fresh box and
hard to fire by accident.

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
