# Handing Backyard to someone else

For when the person running the instance stops being the person running the instance —
moving house, losing interest, getting ill, or dying. The threat model calls
single-maintainer abandonment **the likeliest way this instance ends**, so this is not a
hypothetical procedure.

**The receiving person needs three things: the accounts, the secrets, and the sheet.** If
any one of the three is missing, the family's history is a countdown.

---

## Before you need it: the succession sheet

Fill in [`backup-recovery-sheet.md`](backup-recovery-sheet.md) *now*, not on the day. It is
the only document that connects the backup passphrase, the registrar, the host, and the
second admin. Everything below assumes it exists and is current.

**A second admin is not optional.** One admin is one bus. Appoint one today: **Members →
the person → Set role → Instance admin**. What that lets them do is described in the role
key on the same page.

---

## 1. Give them an account with the keys

| | |
|---|---|
| Backyard | Make them **Instance admin** (Members → Set role). Confirm they can reach `/members/`. |
| Server | Add their SSH key to `~/.ssh/authorized_keys` on the box. Confirm they can log in **before** you remove yours. |
| Host account | Transfer or share the VPS provider account. A shared password manager entry beats a forwarded email. |
| Registrar | Transfer the domain, or add them to the registrar account. See §4 — the domain is the part people forget. |
| Email provider | Transfer or share the sending-domain account (Resend or whatever is configured). |

---

## 2. Rotate every secret

Anything the outgoing person knew, they still know. Rotate all of it, in this order — the
database passwords last, because the app has to come back up between steps.

```bash
# On the box, in ~/backyard
cp .env .env.before-handover      # so a mistake is recoverable

# 1. Django secret key — invalidates every existing session immediately
python -c "import secrets; print(secrets.token_urlsafe(64))"   # put in DJANGO_SECRET_KEY

# 2. Email provider API key and inbound signing secret — mint fresh ones in the provider UI
#    RESEND_API_KEY, RESEND_INBOUND_SECRET

# 3. The three Postgres role passwords
python -c "import secrets; print(secrets.token_urlsafe(24))"   # x3

# 4. Bring it back up and confirm it serves
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
curl -sSf https://YOUR-DOMAIN/manifest.webmanifest > /dev/null && echo "serving"
```

**The backup passphrase is different.** Changing it does **not** re-encrypt old archives:
every backup taken under the old passphrase still needs the old passphrase, forever. So
either keep both on the sheet with dates, or take a fresh backup under the new passphrase
and destroy the old archives once you have verified the new one restores.

---

## 3. Regenerate every token

Rotating the Django key kills sessions. It does **not** kill elder links, digest links or
reply addresses — those are generation-anchored per member. One command kills all of them:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web sh -c \
  'DJANGO_SECRET_KEY=$(cat /data/secret_key) python manage.py shell -c "
from core import backups; print(backups.revoke_every_credential())"'
```

**This is the same code a restore runs**, deliberately — one implementation, so neither can
come to miss a credential class.

**Then re-issue the elder links**, or the grandparents are locked out with no way to ask:

1. **Members → the elder → Elder link** for each one.
2. Hand each link over in person or by private message, and reprint any QR.
3. Post something to the whole side of the family **first**, so the page they open is not
   empty — see the note at the top of [`founder-qa.md`](founder-qa.md).

---

## 4. The domain is a family asset

A lapsed domain is the worst outcome in this document. Every printed QR, every bookmark and
every elder link points at a hostname; a bearer URL cannot tell the new host from the old
one, so a squatter who re-registers it inherits **working credentials** and can stand up a
convincing phishing surface plus the family's mail (threat row **T-OP-G4**).

Treat it accordingly:

- **Auto-renew ON**, with a payment method that outlives one person's expiring card.
- **Register multi-year**, not annually.
- **Registrar lock ON** to block a transfer nobody authorised.
- **Two people** on the registrar account.
- Put the registrar, the login, and the renewal date on the succession sheet.

The instance watches this for you: the weekly health email reports **days remaining** and
flags it inside 45 days. If that email is not arriving, see below.

---

## 5. Confirm the health email actually reaches the new person

The instance's only way of telling anyone it is unwell is the weekly health email, and it
only goes to **instance admins with a confirmed email address**. An admin who never
confirmed one gets nothing — and then nobody is watching, which is the whole condition the
email exists to prevent.

So, as the new admin:

1. **Settings → Digest** and confirm your address.
2. Check you receive the Monday health email.
3. It should report: last backup, disk headroom, domain days-remaining. Two lines will say
   `NOT MEASURED` — failed sign-ins and off-box backup age. That is honest, not broken: the
   instance genuinely cannot see either one. **Off-box backup age is yours to check by
   hand.**

---

## 6. Take the outgoing person's access away

Last, and only once the new person has demonstrably done everything above:

- Remove their SSH key from the box.
- Demote their Backyard role, or remove the member if they are leaving the family software
  entirely (**Members → Remove**, which asks what happens to their posts).
- Remove them from the registrar, host and email-provider accounts.
- Take the old `.env.before-handover` off the box.

---

## If you are reading this because someone died

Do the parts that stop the clock, in this order, and leave the rest for later:

1. **Take a backup and copy it off the box.** Nothing else matters if the volume dies.
2. **Check the domain's renewal date and payment method.** This is the one that fails
   quietly and cannot be undone.
3. **Appoint a second admin** so the instance is not one login away from unreachable.

Then stop. The rotations can wait a week. Marking the person's account is covered by
**Members → Remove → "Keep their posts, still attributed to them"**, which stops their
credentials without erasing them from the family's history.
