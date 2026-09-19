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
passphrase from `--passphrase-file`, `BACKYARD_BACKUP_PASSPHRASE`, or the keyfile
`BACKYARD_BACKUP_PASSPHRASE_FILE` names, in that order — never from the command
line, where it would land in shell history and every process listing.
There is no key escrow: **lose the passphrase and the archive is gone.** Write it
on the recovery sheet and keep that somewhere a house fire would not take with it.

The **pre-flight dumps** taken by the entrypoint before each migration are
**encrypted too, whenever a passphrase is configured by EITHER route** —
`BACKYARD_BACKUP_PASSPHRASE` or the keyfile `BACKYARD_BACKUP_PASSPHRASE_FILE`
names. Compose passes both variables to the web container, which is the one that
takes the dump, and the resolver that reads them (`core/backup_passphrase.py`) is
the same one the backup command and the nightly run use — so the keyfile
configuration this guide recommends encrypts all three.

This used to say they were "still plaintext … because nothing can be holding a
passphrase at that moment". That reasoning was wrong, and it was load-bearing: it
justified writing an unencrypted dump of the entire family database on every
container start, three copies deep, which is verbatim T-BACKUP-1 and T-MEDIA-5.

**If NEITHER is configured, the dumps are plaintext and the instance says so on
every boot.** That warning is the fix working, not a cosmetic nag. Read access to
`/data` yields those dumps whole. Set one of them.

## The nightly backup

The worker takes one at **03:30 UTC every day** (`core/tasks.scheduled_backup_task`) —
the schedule is UTC because the instance is (`TIME_ZONE = "UTC"`), so work out what that
is where you live before you go looking for last night's archive. It runs
through the same `backup_instance` command this runbook documents — there is no
second backup implementation to drift.

- **Where:** `/data/backups/scheduled-YYYY-MM-DD.bak` on the data volume, one file
  per day. It is on the same volume as the media it archives, which is the point
  worth being uncomfortable about: see "Getting a copy off the box" below.
- **Encrypted, or nothing.** The nightly run never passes `--no-encrypt`, so with
  no passphrase set it writes **no archive at all** and records the reason. It
  does not fall back to plaintext.
- **If you use a keyfile instead of `.env`,** set `BACKYARD_BACKUP_PASSPHRASE_FILE` to
  the in-container path of the mounted key. Compose passes that variable to **both** web
  and worker, so mount the key (read-only, `chmod 600`, never under `/data`) into both:
  the worker takes the nightly archive and web takes the pre-flight dump before every
  migration. The nightly run has no command line to pass `--passphrase-file` on, so
  without that variable it refuses every night.
- **It refuses rather than fills the disk.** If the volume does not hold roughly twice
  the last archive, the run records that and stops. Twice, because the run builds two
  more full copies beside the archive before it exists — the database dump plus the media
  tar, and the single tar built from them — and all of them land on this volume, which is
  what makes the check honest. An archive is a full copy of the media tree, and filling
  `/data` stops uploads and the database too.
- **Retention:** the last 14 days, plus the newest archive of each of the last 8
  ISO weeks. It deletes only archives a scheduled run RECORDED writing — the name alone
  is not enough — so your own archives, the entrypoint's `preflight-*` dumps, and a
  `scheduled-*.bak` you restored or copied in from another box are never candidates.
- **Who dumps:** the worker holds no migrator password (it runs ffmpeg on
  uploaded video and must never hold DDL credentials), so the dump runs as
  `backyard_app`, which ADR-004 already grants SELECT on every table.

### When it fails

It fails loudly in three places at once, which is the whole design:

1. the **weekly health email** grows a `[!] Scheduled backup: FAILING since …`
   line carrying the reason;
2. `/healthz` answers `degraded` instead of `ok` — and the external monitor
   (`.github/workflows/monitor.yml`) turns that into a GitHub issue within half an
   hour, which e-mails you because it mentions you. See "The monitor outside the
   box" below for exactly how often it will and will not speak;
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

# Then, in the host's crontab. Mind the clocks: the instance writes at 03:30 UTC and cron
# runs in the HOST's timezone, so pick an hour comfortably after 03:30 UTC where you are.
#
# Copy ONLY the scheduled archives, which are always encrypted. `preflight-*.dump` sits in
# the same directory and is PLAINTEXT whenever NEITHER passphrase route is configured (the
# entrypoint says so on every boot) -- a wildcard here would ship the entire family
# database in the clear.
#
# And no `--delete`: an off-box copy that mirrors deletions is not a backup against the
# things it exists for. A mistaken `rm`, a retention bug or ransomware on the box would be
# replicated to the copy within the hour. Prune the far side by hand, deliberately.
# `cutover-*.bak` is in the pattern too: it is the name reserved for an archive you took by
# HAND that must reach the far side (the final backup before a server move). Anything else
# you name a hand-taken archive stays on the box.
# 30 9 * * * rsync -a --include='scheduled-*.bak' --include='cutover-*.bak' --exclude='*' <that path>/backups/ <your-backup-host>:/srv/backyard/
```

#### Telling the instance how the copy went (optional)

The copy runs on the host, so the instance cannot watch it. It can be **told**. If
your job writes one small JSON file into the backups directory, a failed or stalled
copy joins the alarms the instance already raises: the weekly health email gets an
`[!]` line, `/healthz` answers `degraded`, and the monitor outside the box opens its
issue. Write nothing and nothing changes — the line reads `NOT MEASURED` exactly as
it always has, and the instance stays `ok`. Most self-hosters have no off-box job,
and an instance that shouted about one they never set up would teach them that
`degraded` means nothing.

The file is `.offbox-status.json`, in the same directory as the archives
(`/data/backups/` inside the container; the host path is the `docker volume inspect`
one above). It holds exactly one of:

```json
{"ok": true,  "at": "2026-09-18T09:30:12Z", "remote_objects": 412}
{"ok": false, "at": "2026-09-18T09:30:12Z", "error": "rclone: quota exceeded"}
```

- `at` is when the job **finished**, in UTC, ISO 8601. A success older than **48
  hours** reads as stale and raises the line, so a nightly job stopping is visible
  on the second missed night rather than never.
- `remote_objects` is optional and decorative: how many files are at the destination.
- `error` is your job's own words, shown to the instance admin only — never on the
  public `/healthz`, which keeps saying just `ok` or `degraded`. It is quoted, flattened
  to one line and truncated.
- A file the instance cannot read — not JSON, no `ok`, no usable `at`, dated in the
  future, a symlink, or larger than a few KB — reads as `UNREADABLE` and **raises the
  line**. A status file that is present and wrong means the question can no longer be
  answered, which is different from nobody having asked it.

Write it **after** the copy, from the copy's own exit status, and write it whether the
copy succeeded or failed — a job that only reports its successes goes quiet in exactly
the case this exists for:

```sh
#!/bin/sh
# On the host, run from cron instead of the bare rsync line above.
set -u
backups="$(docker volume inspect backyard_appdata --format '{{ .Mountpoint }}')/backups"
status="$backups/.offbox-status.json"

if err="$(rsync -a --include='scheduled-*.bak' --include='cutover-*.bak' --exclude='*' \
            "$backups/" <your-backup-host>:/srv/backyard/ 2>&1)"; then
  ok=true; err=""
else
  ok=false
fi
# Stamped AFTER the copy returns, because `at` is when the job FINISHED: a copy that ran
# for three hours would otherwise hand the instance a time three hours stale on arrival.
at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# A real JSON encoder rather than printf, because rsync's message is not yours to predict:
# a quote, a backslash, a tab or any other control byte would make a hand-built file
# invalid JSON, and the instance would report UNREADABLE instead of the failure you were
# trying to tell it about. (`jq -n --arg` does the same job if you prefer it to python3.)
# Written beside the file and moved into place, so the instance never reads half of one.
OK="$ok" AT="$at" ERR="$err" python3 -c '
import json, os
out = {"ok": os.environ["OK"] == "true", "at": os.environ["AT"]}
if not out["ok"]:
    out["error"] = os.environ["ERR"][:200]
print(json.dumps(out))' > "$status.new"
mv "$status.new" "$status"
```

### The monitor outside the box

`.github/workflows/monitor.yml` runs on GitHub's infrastructure every 30 minutes and asks
this instance two questions: does `/healthz` answer, and how many days are left on the TLS
certificate. Both are asked on every run — neither result skips the other. Arm it by
setting the repository variable `BACKYARD_MONITOR_URL` (Settings → Secrets and variables →
Actions → Variables) to the instance's `/healthz` URL; with it unset the workflow exits
cleanly and watches nothing.

**How it tells you.** Not by failing: a failed run e-mails once per run, so a problem that
persists — a nightly backup that has been refusing for a week — would send 48 identical
e-mails a day, and the reliable end of that is a muted repository and no alarm at all. It
opens **one issue** instead, labelled `monitor-alarm` and titled "Backyard needs
attention", and sends you one e-mail of its own — the mention in that issue is a GitHub
notification, which measurably does not reach a mailbox on its own, so the monitor mails
the alarm itself from outside the box (three repository secrets arm that half; see
[the outside monitor in self-host.md](self-host.md#the-monitor-that-runs-outside-the-box)).
While the
problem lasts, later runs add a comment to that same issue **at most once a day**. When the
instance is well again the monitor comments "Recovered" and closes it, so *no open
`monitor-alarm` issue* is the all-clear. The check run itself goes red only when the alarm
MECHANISM fails (GitHub's API refusing, a missing permission) — the one failure nothing
else would ever report.

**It has its own way of going quiet.** GitHub disables scheduled workflows in a public
repository after 60 days with no repository activity, and e-mails the owner when it does.
Any push, or pressing "Run workflow" on that page, resets the clock. If this repository
goes quiet for two months, re-enable this before trusting the silence.

The health email's "Off-box copy" line reads NOT MEASURED until your host job tells
the instance how it went, and on an instance with no such job it should: the app
cannot see where you copied a file to, and a line claiming otherwise would be the
more dangerous kind of wrong (T-OP-G3). Once the job writes `.offbox-status.json`
(above), that line carries the answer and a failed or stalled copy reaches this
monitor like any other alarm.

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
#   chmod 600 /root/backyard.key        # every reader refuses a group/world-readable key
#   # add to BOTH the web and worker services in docker-compose.prod.yml:
#   #   volumes: [ "/root/backyard.key:/run/secrets/backyard.key:ro" ]
#   # and name it once in .env, which compose passes to both:
#   #   BACKYARD_BACKUP_PASSPHRASE_FILE=/run/secrets/backyard.key
#   # With that set, the command above needs no flag at all -- and so do the nightly run
#   # and the entrypoint's pre-flight dump. --passphrase-file still overrides it:
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

Then copy the archive off the box. It is **already encrypted** — that is what
`backup_instance` writes unless you passed `--no-encrypt` — so there is nothing to wrap it
in:

```sh
docker compose cp web:/data/backups/backup-YYYY-MM-DD.bak ./
```

> This block used to name `backup-YYYY-MM-DD.tar` and pipe it through `age -r <key>`.
> Neither is right any more: archives are `.bak`, encryption is the command's own default
> (`core/backup_crypto`), and there is no `age` anywhere in this project. Copying a file
> that does not exist and then encrypting ciphertext is the kind of step an operator
> discovers is wrong at the worst moment.

### Name it `cutover-…` if the off-box copy must pick it up

The host-side copy job in "Getting a copy off the box" below deliberately copies by pattern
rather than by wildcard, because `preflight-*.dump` sits in the same directory and is
plaintext when no passphrase is configured. The patterns it copies are `scheduled-*.bak`
(the nightly) and `cutover-*.bak`. So an archive you take **by hand** that has to reach the
second site — the final backup before a server move, the one before a risky migration —
must be named `cutover-<something>.bak`, or the job will leave it on the box:

```sh
docker compose exec -T web sh -c \
  'export DJANGO_SECRET_KEY=$(cat /data/secret_key); python manage.py backup_instance /data/backups/cutover-$(date +%F).bak'
```

Retention never touches it either: the nightly prune deletes only archives a scheduled run
recorded writing, so a `cutover-*.bak` stays until you remove it yourself.

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

### Getting the archive INTO the container

If the archive is on the host rather than already on the data volume, **stream it in as the
app user**. Do not use `docker compose cp` for this direction:

```sh
cat backup-YYYY-MM-DD.bak | docker compose exec -T web sh -c \
  'umask 077; cat > /data/backups/backup-YYYY-MM-DD.bak'
```

`docker compose cp` writes the file owned by the **host's** uid with mode 600, and the
container runs as an unprivileged user with no `DAC_OVERRIDE`, so the app user cannot read
its own archive and `chown` inside the container fails too. The restore then refuses on a
file that is sitting right there. Streaming it through the app user's own `cat` makes the
ownership correct by construction, and `umask 077` keeps it 600.

### Restoring

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

### Then restart, and only then say it is up

**`restore_instance` does not run migrations, and it is not the thing that does.** The
entrypoint runs `migrate` at container start, so restoring an archive taken on an OLDER
schema leaves the database behind the code, and `migrate --check` exits **1** until the
containers come back:

```sh
docker compose restart web worker
docker compose exec -T web sh -c \
  'DJANGO_SECRET_KEY=$(cat /data/secret_key) python manage.py migrate --check'
```

That command must exit **0** before anyone is told the instance is back. It is the whole
check: a restored box that answers `/healthz` while the schema is a release behind will
serve some pages and 500 on others, which reads as a bad restore rather than an unfinished
one. Check the roster in the same breath — a restore brings back anybody removed since the
backup (the table above).

### A restart right after a failed pre-flight dump is expected

The entrypoint refuses to migrate if its pre-flight dump fails, so the container exits 1 and
Docker restarts it. That is the guard working, not a crash loop: on a boot where `web` wins
the race against Postgres, `pg_dump` fails, the container exits, and the next attempt
succeeds a few seconds later once the database is accepting connections. Observed for real
on an unattended-reboot morning. The failure path now removes the partial file it wrote, so
a failed dump no longer leaves a 0-byte plaintext `preflight-<stamp>.dump` behind. If the
restarts do not stop, read the `web` log for the dump's own error rather than the migration's.

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
