# Moving an instance to a new server

Rebuilding the box under a live family instance, without the site going down for longer
than a DNS change and without TLS dropping for a second.

This is written from having done it, not from having planned it. Every gotcha below cost
real time on the day: the ones marked **trap** are where the obvious command is the wrong
one. Read the whole thing before you start — several steps are in this order for a reason,
and the last one is "do not destroy anything yet".

Placeholders: `example.com` is your instance's domain, `NEWBOX` and `OLDBOX` are whatever
your shell can reach each machine by, and `203.0.113.10` stands in for the new machine's
public address. Fill in your own; nothing real belongs in a public runbook.

---

## Before you touch anything

- [ ] You can reach both machines.
- [ ] You have the **`.env` from the old box**. It holds the three database passwords, the
      backup passphrase and the mail credentials. Without it the archive is unreadable and
      the family's history is gone — there is no key escrow.
- [ ] You know which **tag** the old box is running, and the new box will run the same one.
      A move and an upgrade at once gives you two suspects for one symptom.
- [ ] You have done a **restore drill** (`backup-restore.md`) at least once, on any box. Do
      it before the cutover, never as the cutover.
- [ ] You have told whoever uses the instance that links will be briefly unavailable — and
      that nothing they are holding stops working, because you are restoring, not rebuilding.

**Budget the DNS TTL.** Drop the A record's TTL to 60 seconds a day before, so the cutover
is a minute rather than an hour. That is the one step that cannot be hurried on the day.

---

## 1. Build the new box

A current Linux distribution, Docker with the Compose plugin, and nothing else.

```bash
ssh NEWBOX
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin git
```

> **trap — compose needs `sudo` here.** A fresh box has your user outside the `docker`
> group, so `docker compose ps` prints a permission error on the socket and reads exactly
> like "the stack is not running". Either prefix every compose command in this runbook with
> `sudo`, or add yourself to the group and open a **new** session — group membership is read
> at login, so `newgrp`-less re-use of the same shell keeps failing after you "fixed" it.

Turn on unattended security patching while you are here, and decide the reboot window
deliberately — it is the one moment the instance goes down without you:

```bash
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades
# Then set the reboot time in /etc/apt/apt.conf.d/50unattended-upgrades:
#   Unattended-Upgrade::Automatic-Reboot "true";
#   Unattended-Upgrade::Automatic-Reboot-Time "09:00";
```

That window is **UTC**, like everything else on the box. Pick an hour nobody in the family
is awake for. Watched end to end on the reference instance: upgrades installed at 06:47,
reboot at the 09:00 window onto a new kernel, all four containers back healthy with nobody
touching it.

## 2. Check the code out, and carry the environment across

The box is a **git checkout**, not a file copy. That is what makes the deploy a
`git checkout <tag>` rather than a tar over ssh, and it is what lets you prove which
revision is serving.

```bash
git clone https://github.com/AIJSAI/backyard.git ~/backyard
cd ~/backyard
git fetch --tags
git checkout v0.1.1          # the SAME tag the old box is on
```

Now carry the environment file box to box. It never touches your laptop's disk and it never
goes through a pastebuffer:

```bash
ssh OLDBOX 'cat ~/backyard/.env' | ssh NEWBOX 'umask 077; cat > ~/backyard/.env'
ssh NEWBOX 'ls -l ~/backyard/.env'      # must be -rw------- and NOT empty
```

Check the mode and the size before you go on. A zero-byte `.env` produces a stack that
comes up and fails in a way that looks like a code problem.

## 3. Take the final backup on the OLD box, and stream it across

Take it now, with the family still using the old box, so the window between this archive and
the cutover is minutes rather than hours.

```bash
ssh OLDBOX
cd ~/backyard
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web sh -c \
  'export DJANGO_SECRET_KEY=$(cat /data/secret_key); python manage.py backup_instance /data/backups/cutover-final.bak'
```

> **Name it `cutover-…`.** The host-side off-box copy job matches `scheduled-*.bak` and
> `cutover-*.bak` and nothing else (`backup-restore.md`), so an archive called anything else
> stays on a machine you are about to switch off. `cutover-*` is also never pruned by the
> nightly retention, which only deletes archives a scheduled run recorded writing.

Get it onto the new box. Out of the old container, then **into** the new one as the app
user:

```bash
ssh OLDBOX 'docker compose -f ~/backyard/docker-compose.yml -f ~/backyard/docker-compose.prod.yml exec -T web cat /data/backups/cutover-final.bak' > cutover-final.bak
```

```bash
cat cutover-final.bak | ssh NEWBOX 'cd ~/backyard && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web sh -c "umask 077; cat > /data/backups/cutover-final.bak"'
```

> **trap — do not use `docker compose cp` for the inbound direction.** It writes the file
> owned by the **host's** uid with mode 600, and the container runs as an unprivileged user
> with no `DAC_OVERRIDE`, so the app cannot read its own archive and `chown` inside the
> container fails too. The restore then refuses on a file that is plainly sitting there.
> Streaming it through the app user's own `cat` makes the ownership right by construction.

(The stack has to be up on the new box before that inbound stream works — so run step 4
first if you prefer, and come back. The order here is the order the archive should be *taken*
in, which is what matters.)

## 4. Build the image and start the app, with Caddy held back

```bash
cd ~/backyard
docker compose -f docker-compose.yml -f docker-compose.prod.yml build --pull \
  && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d postgres web worker
```

**`build --pull`, chained into the `up`.** The app image installs `postgresql-client-18` and
`ffmpeg` in a layer above `python:3.13-slim`, and nothing in an ordinary build re-resolves
that base — so `up --build` would give a brand-new machine the binaries of whenever the base
tag was last cached. The `&&` matters too: unchained, a failed build is followed by an `up`
that starts whatever image was there.

**Caddy is deliberately not in that list.** Starting it now means it asks Let's Encrypt for
a certificate for a name that still points at the old box, which fails the HTTP-01 challenge
and eats attempts against the rate limit. It starts in step 6, with the old certificate
already in place.

Watch the first boot. The entrypoint generates a fresh `DJANGO_SECRET_KEY`, runs migrations
and writes a one-time setup secret — all of which the restore is about to replace:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs web | tail -40
```

## 5. Restore, restart, and prove the schema is current

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web sh -c \
  'export DJANGO_SECRET_KEY=$(cat /data/secret_key); python manage.py restore_instance /data/backups/cutover-final.bak'
```

Add `--force` if the box already has members — a fresh one will not, and needing `--force`
on a machine you believe is empty is worth stopping over rather than typing through.

> **trap — restore does not migrate, and you must restart.** The **entrypoint** is what runs
> `migrate`, so restoring an archive taken on an older schema leaves the database behind the
> code and `migrate --check` exits 1. Restart, then check:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart web worker
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web sh -c \
  'export DJANGO_SECRET_KEY=$(cat /data/secret_key); python manage.py migrate --check'
```

That must exit **0**. It is the whole proof that the new box is serving the same schema the
code expects; a box that answers `/healthz` with a schema a release behind renders some
pages and 500s on others, which reads as a bad restore rather than an unfinished one.

A restore is a security event: every elder link, digest link, reply address and session the
archive carried is dead, instance-wide, and anybody removed **after** the backup comes back.
Read the table in [`backup-restore.md`](backup-restore.md) and check the roster before you
tell anyone the instance is up.

## 6. Carry the TLS certificate across, so HTTPS never drops

Caddy keeps its ACME account and its issued certificates in the `caddydata` volume. Copy it
and the new box serves the **existing** certificate the instant it starts — no issuance, no
challenge, no gap, and no attempts spent against the rate limit at the worst moment.

```bash
# On the OLD box: stream the volume out as a tar.
ssh OLDBOX 'docker run --rm -v backyard_caddydata:/from alpine tar -C /from -cf - .' > caddydata.tar
```

```bash
# On the NEW box: unpack it into the volume compose will use.
cat caddydata.tar | ssh NEWBOX 'docker run --rm -i -v backyard_caddydata:/to alpine tar -C /to -xf -'
```

The volume is named after the compose project, which is the directory name — `backyard_` if
you cloned into `~/backyard` as above. Check with `docker volume ls` rather than assuming.

Then start the edge:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d caddy
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

All four containers must read healthy before you go near DNS.

## 7. Verify the new box BEFORE you repoint anything

This is the step that makes the cutover reversible. `--resolve` sends the request to the new
address while still presenting the real hostname and checking the real certificate, so you
are testing exactly what a family member's browser will do, minutes before it does it:

```bash
curl -sS -o /dev/null -w '%{http_code} %{ssl_verify_result}\n' \
  --resolve example.com:443:203.0.113.10 https://example.com/healthz
```

`200 0` is the answer you want: served, and the certificate verified against the real name.
Walk a page or two the same way. If anything here is wrong, nothing has moved yet and the
family is still on the old box.

## 8. Repoint DNS

Change the `A` record to the new address. **DNS-only** — if your DNS provider offers a proxy
or CDN mode, leave it off: Caddy terminates TLS itself, and a proxy in front changes the hop
count every per-address rate limit in the app is keyed on.

Watch it land, then ask the real name with no `--resolve` at all:

```bash
dig +short example.com
curl -sS -o /dev/null -w '%{http_code}\n' https://example.com/healthz
```

## 9. Stop the old stack — stop, do not destroy

```bash
ssh OLDBOX 'cd ~/backyard && docker compose -f docker-compose.yml -f docker-compose.prod.yml stop'
```

`stop`, never `down -v`. The old volumes are your rollback: if the new box turns out to be
wrong in a way the checks above did not catch, starting the old stack and putting the DNS
record back is a two-minute recovery, and it stops being available the moment you delete
them.

**Keep them until the walk passes.** Sign in as a real member on the new instance, open a
photograph, post something, open an elder link, and take a backup on the new box and prove
it decrypts. Only when all of that is done:

```bash
ssh OLDBOX 'cd ~/backyard && docker compose -f docker-compose.yml -f docker-compose.prod.yml down'
# and only then destroy the old machine, through your provider's console.
```

---

## Afterwards

- **Mint fresh elder links** for everybody who had one. The restore killed them all, and
  "her link stopped working" is not something to discover from the person holding it.
- **Re-point the off-box backup job** at the new host, and check `.offbox-status.json`
  appears where the instance can read it (`backup-restore.md`). Until it does, the weekly
  health email reports `NOT MEASURED`, which is honest and not reassuring.
- **Re-point the external monitor.** `BACKYARD_MONITOR_URL` is a repository variable and
  follows the domain, so it needs nothing if the name did not change — but confirm a run
  went green rather than assuming.
- **Update the succession sheet** ([`backup-recovery-sheet.md`](backup-recovery-sheet.md)):
  the server provider, the login, and where backups are written now.
- **Take the TTL back up** if you dropped it to 60 for the cutover.
