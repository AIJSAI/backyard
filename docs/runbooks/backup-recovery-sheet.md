# Backyard — succession sheet

**Print this. Fill it in by hand. Keep it somewhere a house fire would not take with it —
ideally not in the same building as the server. Tell one other person where it is.**

This used to be only a backup passphrase. It is a **succession sheet** (S-804): the one
document that connects the passphrase, the registrar, the host account and the second admin.
A passphrase with no note of who else can reach the server, or of when the domain renews,
recovers the files and loses the instance anyway.

There is no key escrow and no password reset. If the passphrase is lost, every backup taken
with it is unrecoverable by anyone, including you. That is the deliberate trade for the app
never holding long-lived key material — but it means this sheet is the single point of
failure for your family's history.

**The one thing to do today, before filling in anything else:** appoint a second instance
admin (Members, then Manage on their row, then Change Role to Family Admin) and write their name below. One admin is one bus.

---

## Who else can run this

    Second Family Admin (name): __________________________________

      their email: ________________________________________________

      they can SSH to the box:        [ ] yes   [ ] not yet
      they can sign in as admin:      [ ] yes   [ ] not yet
      they receive the weekly health email:  [ ] yes   [ ] not yet

    Third person who knows this sheet exists: ____________________

## The accounts, not just the passwords

    Domain registrar: ____________________  login: _______________

      domain renews on: ______________  auto-renew: [ ] on  [ ] off

      registrar lock: [ ] on  [ ] off      multi-year: [ ] yes  [ ] no

      A lapsed domain hands every printed QR and no-login link to a squatter
      (T-OP-G4). This line is the one that fails quietly.

    Server / VPS provider: ______________  login: _______________

    Email provider (sending domain): ____________________________

## Where a copy of the family's history is, off this box

    Off-box backup location: _____________________________________

      last copied off the box on: __________________

      The instance can only see this if the copy job on the host tells it:
      the optional `.offbox-status.json` file in docs/runbooks/backup-restore.md
      ("Getting a copy off the box"). Without it the health email reports
      NOT MEASURED every week and this line is yours to check.

      Does a host job report it here?  yes / no  ______

---

    Instance domain: ______________________________________________

    Backup passphrase (write it, do not print it):

      ____________________________________________________________

      ____________________________________________________________

    ...or, if it lives in a password manager, name the vault and item here
    instead of copying the value:

      ____________________________________________________________

    > A password manager is a fine place for it — but only if **somebody else can
    > reach it**. If the passphrase exists solely inside an account that dies with
    > you, you have moved the single point of failure, not removed it. Set up
    > emergency access / a legacy contact, or write the value on this sheet too.
    > The archive does not care which; it cares that exactly one person is not the
    > only route to it.

    Date set: ____________________   Set by: ______________________

    Where backups are written: ____________________________________

    Where backups are copied OFF the box: _________________________

---

## To restore, on a fresh machine

Do these in order. **Do not open `/setup/` and make yourself an admin first** — the restore
replaces the database anyway, and an instance that has a member in it makes the restore
refuse (step 3 says what to do if you already did).

On the reference box every `docker` command needs `sudo`, because a fresh machine leaves
your user outside the `docker` group; the socket error it prints otherwise reads exactly
like "the stack is not running".

1. **Put the passphrase in the box's `.env` BEFORE the stack comes up**, then bring the
   stack up (`docs/runbooks/live-repro.md` §B). Write the line by hand — not with a shell
   command, which would put the passphrase in your history:

       BACKYARD_BACKUP_PASSPHRASE=<the passphrase above>

   Compose passes that variable into both `web` and `worker`, and the new box needs it
   there permanently anyway, so its own nightly backups keep encrypting under the same
   passphrase. A new `DJANGO_SECRET_KEY` gets generated on first boot; that is fine.

   *(The tighter alternative, if the sheet's owner set one up, is a 0600 keyfile mounted
   read-only into both containers with `BACKYARD_BACKUP_PASSPHRASE_FILE` naming its path
   **inside** the container — `/run/secrets/backyard.key`, never anything under `/data`.
   That only works if the mount is in `docker-compose.prod.yml`, so unless you can see it
   there, use the `.env` line above.)*

   *(If you still have the old `.env`, copy its three `BACKYARD_VAPID_*` lines across too
   and phone notifications keep working. Without them notifications are off — everything
   else restores — until you generate a new pair; see "Notifications on a phone" in
   `docs/runbooks/self-host.md`.)*

2. **Stream the archive in as the app user.** Do not use `docker compose cp`: it lands the
   file owned by the host's user and the container's unprivileged user cannot read it
   (`backup-restore.md`, "Getting the archive INTO the container").

       cat <archive>.bak | sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml \
         exec -T web sh -c 'umask 077; cat > /data/backups/<archive>.bak'

3. **Restore. No `--passphrase-file`** — the command reads `BACKYARD_BACKUP_PASSPHRASE`
   out of the container's environment, which step 1 put there:

       sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web sh -c \
         'export DJANGO_SECRET_KEY=$(cat /data/secret_key); python manage.py restore_instance /data/backups/<archive>.bak'

   If it says it is **refusing to restore over a database that still has members**, you
   created the first admin before restoring. Run it again with `--force` INSIDE the quotes,
   at the end of the `manage.py` line. After the closing `'` it becomes the shell's `$0`,
   never reaches the command, and the restore refuses again with the identical message:

       sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web sh -c \
         'export DJANGO_SECRET_KEY=$(cat /data/secret_key); python manage.py restore_instance /data/backups/<archive>.bak --force'

   If it says the archive is encrypted and asks for a passphrase, step 1 did not take:
   check the `.env` line and bring the stack up again. The passphrase must be at least 12
   characters, and leading and trailing whitespace is ignored.

4. **Restart, then check.** `restore_instance` does not migrate — the entrypoint does — so
   an archive from an older release leaves the schema behind until the containers come back:

       sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml restart web worker
       sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web sh -c \
         'export DJANGO_SECRET_KEY=$(cat /data/secret_key); python manage.py migrate --check'

   That must exit 0 before you tell anyone the instance is up.

5. **A restore is a security event (TM-7).** The command will tell you what it did: every
   no-login link, email-update link and reply-by-email address the backup carried is dead, every
   session is flushed, and outstanding invites are void. Re-provision only the people who
   should still have access — and remember the restore cannot know who was removed *after*
   the backup was taken, so check the roster.

## Test this before you need it

A backup you have never restored is a hope, not a backup. Do a restore drill on a
throwaway machine at least once, and after any upgrade that changes the database.

## If you are handing it over, or shutting it down

Neither is improvised well. Both have their own procedure:

- **Handing it to someone else:** [`handover.md`](handover.md) — rotate every secret,
  regenerate every token, transfer the registrar and host accounts, and confirm the health
  email reaches the new person before you remove your own access.
- **Ending it on purpose:** [`shutdown.md`](shutdown.md) — export for at least two people
  **first**, revoke every credential while the box is still up to answer with a 404, and
  destroy volumes and provider snapshots last. `manage.py decommission_instance` does the
  first two and refuses to pretend it did the third.
