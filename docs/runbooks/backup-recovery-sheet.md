# Backyard — backup recovery sheet

**Print this. Fill it in by hand. Keep it somewhere a house fire would not take with it —
ideally not in the same building as the server.**

There is no key escrow and no password reset. If this passphrase is lost, every backup
taken with it is unrecoverable by anyone, including you. That is the deliberate trade for
the app never holding long-lived key material — but it means this sheet is the single
point of failure for your family's history.

---

    Instance domain: ______________________________________________

    Backup passphrase (write it, do not print it):

      ____________________________________________________________

      ____________________________________________________________

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
