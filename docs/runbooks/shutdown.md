# Shutting Backyard down for good

For deciding to stop, rather than drifting into it. The aim is that **nobody loses their
history and no old link outlives the instance**.

If you might come back to it, don't do this — take a backup, copy it off the box, and turn
the VM off. This procedure is for ending it.

---

## The order matters, and it is not the intuitive one

```
    1. EXPORT   for at least two people
    2. REVOKE   every credential, while the box is still up
    3. DESTROY  volumes and provider snapshots, by hand
```

**Export before revoke.** A shutdown that revoked first and then failed to export would
have destroyed access to data nobody held a copy of.

**Revoke before destroy, while the box still answers.** Every printed QR and bookmarked
elder link points at your hostname. Revoking while the instance is up means an old link
meets a real 404 from *you*. Skip it, and the first thing those links meet is whoever
re-registers the domain (threat row **T-OP-G4**).

---

## 1 and 2: one command

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web sh -c \
  'DJANGO_SECRET_KEY=$(cat /data/secret_key) python manage.py decommission_instance \
     --to "Their Name" --to "Someone Else" \
     --output-dir /data/final-exports \
     --confirm "shut it down"'
```

It refuses unless you name **at least two different** members — one custodian is the bus
factor this whole procedure exists to remove. It refuses on a name it cannot find or that
matches two members, and it changes nothing when it refuses.

It writes one zip per named member, tells you to check they open, **then** revokes every
credential class through the same code a restore uses.

Copy those zips off the box before you go further.

```bash
scp -i ~/.ssh/backyard_vm 'ubuntu@YOUR-IP:/data/final-exports/*.zip' ~/backyard-final/
```

---

## 3: the parts the command will not do for you

Deliberately manual. Destroying a provider snapshot needs credentials the app has no
business holding, and *"the command deleted the snapshots before I had checked the export"*
is not a recoverable mistake.

1. **Deliver the exports.** Not "send them" — watch each person open theirs. A zip nobody
   ever opened is not a copy.
2. **Take a final encrypted instance backup** and copy it off the box. Members' exports
   contain what each person authored; only the instance backup has the whole archive.
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web sh -c \
     'DJANGO_SECRET_KEY=$(cat /data/secret_key) BACKYARD_BACKUP_PASSPHRASE=... \
        python manage.py backup_instance --output /data/final-backup.tar.enc'
   ```
   Keep the passphrase with the archive's *location*, never in the same place as the
   archive. There is no key escrow: lose it and that file is gone.
3. **Bring the stack down**, then destroy the volume.
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml down -v
   ```
4. **Destroy the provider snapshots.** These are the copies people forget, and they contain
   the entire family database and every photograph.
5. **Terminate the VM.**

---

## 4. The domain, last and slowest

Do **not** drop the registration the week you shut down.

Printed QR codes are in kitchen drawers. Elder links are in text-message history. Those
point at a hostname, and a bearer URL cannot distinguish your host from the next one — so
a squatter who picks the domain up inherits every one of them, plus the ability to receive
mail addressed to your family.

- Keep it registered, parked, with **auto-renew on**, for as long as you plausibly can.
- When you do let it go, ask the family to destroy the printed QR codes first.
- If you hand the domain to someone else, do the full
  [handover](handover.md) instead of this document.

---

## What you should be left with

- At least two people each holding a zip **they have opened**.
- One encrypted instance backup, off the box, with its passphrase location written down.
- No volumes, no snapshots, no VM.
- A domain that is still yours, parked, until the paper is out of circulation.
- A family that was told in words, by a person, where their copy is — not one that noticed
  the site had stopped working.
