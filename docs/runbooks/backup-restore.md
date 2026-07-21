# Backup and restore runbook (S-704, S-802)

Backing up and restoring a whole Backyard instance is one command each, and the
restore is exercised as a drill before every release. This is the documented,
tested path.

## What a backup contains

One archive holds the two stateful things:

- the **database** (`pg_dump -Fc` custom-format dump), and
- the **media tree** (`MEDIA_ROOT`, every uploaded photo and derivative).

It is a plain tar of three members: `backup-manifest.json`, `database.dump`,
and `media.tar.gz`. Open it, verify it, and encrypt or ship it with your own
tools. The app holds no encryption key; at-rest encryption is your storage
layer's job (`age`, `gpg`, or an encrypted volume), kept out of the app so the
app never custodies long-lived key material.

## Trust and safety

A restore archive is executed against the database as the migrator (DDL) role,
so restoring one is equivalent to handing its author a shell on the box. Only
ever restore an archive you produced and kept custody of; never a third-party or
untrusted archive. The manifest is a shape check, not a signature, so it does
not make an untrusted archive safe. Restore also clean-restores the database
before it replaces the media tree, so a mid-restore failure can leave the
database restored and the media stale; re-run the restore from the same archive
to converge. Backups and the pre-flight dumps all live unencrypted on the same
`/data` volume, so read access to `/data` yields the full database and media in
the clear: encrypt archives the moment they leave the box.

## Back up

Run in the migrator's environment (the compose stack already has
`POSTGRES_MIGRATOR_PASSWORD` for the migrate step):

```sh
docker compose exec \
  -e POSTGRES_MIGRATOR_PASSWORD="$MIGRATOR_PW" \
  web python manage.py backup_instance /data/backups/backup-$(date +%F).tar
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
docker compose exec \
  -e POSTGRES_MIGRATOR_PASSWORD="$MIGRATOR_PW" \
  web python manage.py restore_instance /data/backups/backup-YYYY-MM-DD.tar
```

To overwrite an instance that still has data (you have decided to roll back),
add `--force`.

## The restore drill (before every release)

Prove the backup is restorable without touching live data, by restoring into a
throwaway scratch database. The migrator cannot create databases, so the
superuser (inside the postgres container) creates the scratch DB owned by the
migrator, and the migrator restores into it.

```sh
# 1. Take a backup (as above).
# 2. Create a scratch DB owned by the migrator (superuser, inside postgres).
docker compose exec postgres createdb -U "$POSTGRES_SUPERUSER" -O backyard_migrator drill_scratch
# 3. Restore the dump into the scratch DB (as the migrator).
docker compose exec web sh -c '
  cd /tmp && tar xf /data/backups/backup-YYYY-MM-DD.tar database.dump
  PGPASSWORD="$POSTGRES_MIGRATOR_PASSWORD" pg_restore -h postgres -U backyard_migrator \
    --clean --if-exists --no-owner -d drill_scratch database.dump'
# 4. Verify the data restored, e.g. member count matches the source.
docker compose exec postgres psql -U "$POSTGRES_SUPERUSER" -d drill_scratch \
  -tAc "select count(*) from core_member"
# 5. Drop the scratch DB.
docker compose exec postgres dropdb -U "$POSTGRES_SUPERUSER" drill_scratch
```

This exact drill runs green in `scripts`-driven live verification: a canary
member and its media survive the round-trip, and the destructive restore is
proven to refuse a populated database without `--force`.
