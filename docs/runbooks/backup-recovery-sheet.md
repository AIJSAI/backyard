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
admin (Members → Set role → Instance admin) and write their name below. One admin is one bus.

---

## Who else can run this

    Second instance admin (name): ________________________________

      their email: ________________________________________________

      they can SSH to the box:        [ ] yes   [ ] not yet
      they can sign in as admin:      [ ] yes   [ ] not yet
      they receive the weekly health email:  [ ] yes   [ ] not yet

    Third person who knows this sheet exists: ____________________

## The accounts, not just the passwords

    Domain registrar: ____________________  login: _______________

      domain renews on: ______________  auto-renew: [ ] on  [ ] off

      registrar lock: [ ] on  [ ] off      multi-year: [ ] yes  [ ] no

      A lapsed domain hands every printed QR and elder link to a squatter
      (T-OP-G4). This line is the one that fails quietly.

    Server / VPS provider: ______________  login: _______________

    Email provider (sending domain): ____________________________

## Where a copy of the family's history is, off this box

    Off-box backup location: _____________________________________

      last copied off the box on: __________________

      The instance CANNOT see this and reports it as NOT MEASURED in the
      health email every week. It is yours to check.

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

1. Bring up the stack (see `docs/runbooks/live-repro.md` §B). It will generate a new
   `DJANGO_SECRET_KEY`; that is fine, the restore replaces the database.
2. Put the archive somewhere the `web` container can read, and the passphrase in a file:

       printf '%s' '<the passphrase above>' > /root/backyard.key
       chmod 600 /root/backyard.key

3. Restore:

       docker compose exec -T web python manage.py restore_instance \
         /data/backups/<archive>.bak --passphrase-file /root/backyard.key --force

4. **A restore is a security event (TM-7).** The command will tell you what it did: every
   elder link, digest link and reply-by-email address the backup carried is dead, every
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
