# Resume here — session state, 2026-08-01

Written to survive a context compaction. Read this, then
**[`docs/OUTSTANDING.md`](OUTSTANDING.md) — the ranked backlog, whose §6 carries what the
2026-08-01 readiness audit added**, whose only record is §6 of that file — there is no separate audit document — then `docs/PATH-TO-100.md`. Verify with a primary check
(`git log`, `gh pr list`, run the probe an item names) rather than trusting anything written
down. That instruction earned its keep: OUTSTANDING.md called itself "the single list" and
a re-measurement found ~30 items it did not contain.

> **Start here after a compaction:** the two live production exposures are **CLOSED** as of
> the evening of 2026-08-01 US Central — which is **2026-08-02 UTC**, the date the box stamped
> on its own artefacts (`backup-2026-08-02.bak`). Same moment; compare in UTC when matching a
> runbook entry to a file on the box (OUTSTANDING §0). The burned credential no longer
> authenticates — verified over HTTPS against the live site — pre-flight dumps are encrypted,
> and the instance has its first verified backup, held off-box and proven to decrypt. No
> plaintext copy of the family database exists anywhere any more.
>
> Secrets live in the **1Password `Backyard` vault**. There is **no key escrow** for
> `BACKYARD_BACKUP_PASSPHRASE`: if that item is lost, every backup taken with it is
> permanently unreadable.
>
> **`v0.1.0` is WITHDRAWN.** It carried the burned credential in three tracked files and the
> cross-yard disclosure fixed in #110. `v0.1.1` replaces it and the README installs that.
> The credential itself is rotated and dead, so this is hygiene rather than a live exposure —
> but do not point anyone at the old tag.

**`v0.1.1` is the current tag** (`v0.1.0` withdrawn). The README installs the tag, not `main`, and `CHANGELOG.md` lists what
does not work as prominently as what does. If you add a user-visible change, add a changelog
entry under an `## [Unreleased]` heading — the install path is now a fixed point that people
can be pointed at, and the whole value of that is it not moving under them.

**Do not put a real credential in a receipt.** The `secrets` job caught exactly that: a receipt
quoted the generated demo password as evidence, and gitleaks' `generic-api-key` rule matched a
16-character random string on sight. Redact to a shape (`<16 url-safe random characters>`), never
allowlist. Note the asymmetry that caused the whole pass: gitleaks is **blind** to
`PW = "<a password a person chose>"` and **catches** a high-entropy value, so the fix moved the credential
into the class the gate can see. The enforcing check for the blind class is
`src/core/tests/test_no_hardcoded_demo_credentials.py` (an `ast` check — a comment cannot defeat
it), and it covers two shapes, the second being a literal fallback inside
`os.environ.get(KEY, "literal")`.

---

## Where things stand

| | |
|---|---|
| `main` | verify with `git log --oneline -1` |
| production | `https://backyard.family`, deployed from `main` after every merge this session |
| stories | **45 passing · 2 superseded · 2 spec** — verify with the snippet below |
| open PRs | `gh pr list` |
| gate | ruff + format + mypy(165) clean · **pytest 737 passed / 2 skipped** |

```bash
uv run --with pyyaml python -c "
import re,collections,pathlib
t=pathlib.Path('stories/stories.yaml').read_text()
print(dict(collections.Counter(re.findall(r'status:\s*(\S+)', t))))
blocks=re.split(r'\n(?=\s*-\s*id:)', t)
print('spec:', [re.search(r'id:\s*(\S+)',b).group(1) for b in blocks if re.search(r'status:\s*spec\b',b)])"
```

## What is actually left

**One story.** S-904 (vCard export) shipped in #103 — serializer over `ViewableProfile`,
never a `Member`, registered as threat row **T-YARD-10**.

**S-603 — ambient photo frame** is the last `spec` entry, and the riskiest thing remaining: a
signed display URL rotating recent photos on an old tablet with zero interaction. It is a NEW
always-on bearer-credential class living on a device in a room, so per the threat model's own
rule (*"New capability types cannot ship without registering here"*) it needs a threat-model
entry — TM-1 registry + `T-DISPLAY-*` rows — **before** code. A draft of that entry, with five
rows worked out, is in the S-603 section below.

### S-603 carries a founder decision, and it is not a small one

Its second acceptance criterion reads *"Display heartbeat counts as an elder touch when
assigned to an elder."* **That criterion contradicts the metrics doc, inside one file:**

- `docs/metrics.md:9` — *"'Active' means any **deliberate** touch: opening the feed, posting,
  reacting, replying by email, or a token-link visit."*
- `docs/metrics.md:21` — the Elder touch rate row counts *"frame display heartbeat"*, and that
  row is described as *"The hardest segment; if elders connect, the design is working."*

A heartbeat is a powered-on tablet, not a deliberate act. Every current input to
`metrics.touched` is a human doing something. Wire a heartbeat in and the one signal that would
tell the family Nana has gone quiet reads "active" for as long as her frame has electricity —
and the KPI becomes unfalsifiable for any member who owns a frame.

**Recommendation on record:** keep the heartbeat, record it under its own name (*"the frame in
the kitchen has been dark for nine days"* is a real signal, arguably a better one), and keep it
**out of `touched`**. That is the reversible direction — wiring a signal into the KPI later is
one line; un-corrupting a metric's history is not. Founder call, because it is a measurement
judgment, not a mechanical one.

Then: **founder manual QA** (PATH-TO-100 criterion 4) is and always was the gate.

## Founder decisions made this session — do not re-litigate

- **The `v1: false` flag on five stories was inherited, not decided.** `story-map.md`
  justified it with *"None is required to pass the alpha KPI"* — a KPI the founder
  superseded on 2026-07-22. Corrected in place; each story re-decided individually.
- **S-706 (deceased-member state) — SUPERSEDED.** *"No to the passed away thing... it can
  just be a deactivation from admin controls. That is not sensitive at all."*
- **S-503 (email-photo-to-pod) — SUPERSEDED.** *"I wouldn't put too much energy into the
  reply by email thing... it would be better if it just opened the app to where they reply."*
- **The warm/cream palette was REJECTED on sight** as belonging to a design run already
  turned down. The colour system is v3.1's, token for token. **Do not re-warm the ground.**
- **Lone photos are CENTRED** in their card. Left-aligning them was tried and called.
- **Verify design by looking at a render at 1440**, not by axe. The standing lesson: axe
  reported 154 renders / 0 violations with every desktop defect present. It paid again in
  #103: "Save to my contacts" sat at the contact list's own row pitch and read as a third
  contact field. Nothing automated would have said so.
- **Park the screenshot harness's cursor off the content** (`page.mouse.move(2, 2)`). Playwright
  leaves the mouse where it last clicked — after a login-then-navigate that lands on a card and
  renders it `:hover`, which reads as an inconsistent-underline bug that is not there.

## The environment recipe (non-obvious, cost real time)

The compose Postgres does **not** publish 5432, so tests need their own database.

```bash
docker run -d --rm --name bk-test-pg -p 127.0.0.1:55433:5432 \
  -e POSTGRES_DB=backyard -e POSTGRES_USER=backyard -e POSTGRES_PASSWORD=ci-not-a-secret \
  postgres:18-alpine

export DJANGO_SECRET_KEY=local-not-a-secret-deadbeef-cafe-1234567890 \
       POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55433 POSTGRES_PASSWORD=ci-not-a-secret

uv run ruff check src && uv run ruff format --check src && uv run mypy src && uv run pytest -q
uv run --with pyyaml python scripts/check_stories.py        # needs pyyaml, not in the venv
uv run --with pyyaml python scripts/check_digest_confinement.py
```

For a **live** instance (design work, live repro):

```bash
cd src
export MEDIA_ROOT=/tmp/by-media BACKYARD_BASE_URL=http://127.0.0.1:8765 \
       DJANGO_DEBUG=1 DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
../.venv/bin/python ../manage.py migrate
../.venv/bin/python ../manage.py shell < ../scripts/demo_seed.py   # prints the elder token
../.venv/bin/python ../manage.py runserver 127.0.0.1:8765 --noreload
```

Traps that each wasted a cycle:

- **`BACKYARD_BASE_URL` must point at the dev server.** Unset, invite links are minted for
  `localhost:8000` — where a *stale container* may answer, so links appear to 404 for
  mysterious reasons.
- **`MEDIA_ROOT` defaults to `/data/media`**, which is read-only outside the container.
- **Seeding after `migrate` leaves demo members unstamped**, so they see the S-906
  orientation. That is correct behaviour, not a bug.
- **allauth rate-limits logins per IP** (`30/5m`, and `10/1h` for *failures*). A sweep that
  logs in repeatedly will trip it. Do **not** probe the limit with wrong passwords — that
  burns the failure budget for an hour. Clear it with
  `docker exec bk-test-pg psql -U backyard -d backyard -c "TRUNCATE backyard_cache;"`.
- **Playwright: `form[action*='comment']` also matches the delete-comment forms.** Use
  `form[action$="/comment/"]`.
- **A yard-wide compose goes through the TM-3 widen-confirmation hop** — the click after
  Post lands on a confirm page, not the feed.
- **Count rendered elements on a FRESH page load.** Counting right after a submit reports
  stale numbers; this produced two phantom "rendering bugs" that the database disproved.

## Deploying (there is no automation)

```bash
tar czf - src | ssh -i ~/.ssh/backyard_vm ubuntu@$BACKYARD_HOST 'cd ~/backyard && tar xzf -'
ssh -i ~/.ssh/backyard_vm ubuntu@$BACKYARD_HOST \
  'cd ~/backyard && docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d web worker'
```

**Rebuild, never just restart** (the image ships `staticfiles`). `main` moving proves
nothing — verify by fetching a string only the new code serves. The manifest's
`background_color` is **no longer** a useful proof: the palette reverted, so it is the value
it always was.

Run a shell on production by piping a file, not with `-c`:

```bash
ssh -i ~/.ssh/backyard_vm ubuntu@$BACKYARD_HOST \
  'cd ~/backyard && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web \
     sh -c "DJANGO_SECRET_KEY=\$(cat /data/secret_key) python manage.py shell"' < local_script.py
```

## Accessibility verification

`scripts/axe_sweep.py` is committed now (it used to be rewritten every session). Fetch
`scripts/axe.min.js` first — it is not vendored:

```bash
curl -sSL -o scripts/axe.min.js https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js
uv run --with playwright python scripts/axe_sweep.py http://127.0.0.1:8765 /tmp/axe.json \
    <admin> <password> [elder-token] [mfa-user] [mfa-password]
```

It runs a **deliberate hover pass** and **names what it skipped**. Both exist because a
resting-only sweep reported 0 violations twice while every primary button was 3.92:1 in dark
mode while hovered.

## Method that kept paying off

- **Prove every new guard fires** by breaking the thing it guards, then restoring. Several
  guards written this session were vacuous until probed — including one where removing a
  URL from an on-origin check failed no test at all.
- **Assert behaviour, not prose.** Three separate tests broke on legitimate copy because
  they searched for a bare word (`"photo"`, `"posted"`, `"role-key"`) that the page says for
  good reasons. Anchor on the rule, or on the rendered element.
- **Comments ship.** A CSS comment quoting a removed tagline kept sending it to every
  client; another mentioning "manifest" broke a guard asserting that word was absent from a
  token surface.
- **Check the data before believing a measurement.** Four apparent defects this session were
  harness errors.

## Operator actions waiting, in priority order

**A decision first, because it gates nothing else and needs you: enforce admin 2FA.** T-ADMIN-1 claims "passkey or TOTP,
enforced in the wizard so a password-only admin never exists". Nothing enforces it: a
password-only superuser reaches every admin surface. It was deliberately left open by the
2026-07-30 security pass because switching it on can lock the only admin out of their own
instance, and `breakglass.py` already assumes the control exists. The safe order is enrol
first, then enforce — which is a rollout call.

The first three below are things a person must do on the box; the classifier in an agent
session refuses `compose exec ... manage.py shell`, so they cannot be done for you.

Both are blocked for an agent in this harness (the command classifier refuses
`docker compose exec … manage.py shell`), so they are copy-paste ready rather than done.
Set the host once — it is a placeholder rather than a literal so the box can be rebuilt without
editing repo history, and so a public repo is not also a target list:

```bash
export BACKYARD_HOST=<the instance IPv4 or hostname>
```

**1. Rotate the demo accounts on production.** `scripts/demo_seed.py` used to hardcode
a fixed password, and **that password still works on the live instance** until it is re-seeded.
It is deliberately not repeated here: it is still live, so writing it down again is a fresh
disclosure, in the one document that explains why not. It is in the git history of
`scripts/demo_seed.py` if you genuinely need it.
The repo no longer publishes it, which closes the disclosure half — this closes the rest. The
re-seed mints and prints a fresh password:

```bash
ssh -i ~/.ssh/backyard_vm ubuntu@$BACKYARD_HOST \
  'cd ~/backyard && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web \
     sh -c "DJANGO_SECRET_KEY=\$(cat /data/secret_key) python manage.py shell"' \
  < scripts/demo_seed.py
```

Keep the `DEMO_PASSWORD=` line it prints — it is the only copy. Or wipe instead, with
`manage.py wipe_demo_data --dry-run` then `--yes`, if you are done with the demo family.

**2. Set BACKYARD_BACKUP_PASSPHRASE on production.** It is unset, so the pre-flight dump
written on every boot is **plaintext** -- and there are three of them on the volume right
now, each the whole family database. The instance says so itself on every start since the
security pass:

```
WARNING: BACKYARD_BACKUP_PASSPHRASE is unset, so the pre-flight backup is PLAINTEXT at
/data/backups/preflight-*.dump -- that is the entire family database.
```

Add it to `~/backyard/.env` on the box, restart web, and confirm the next line reads
`Pre-flight backup written ENCRYPTED`. Record the passphrase on the succession sheet: there
is no key escrow, so losing it loses those archives. Then delete the plaintext dumps.

**3. Take a backup. Production has never had one**, and the weekly health email has been
saying so since it shipped. This is the largest real risk in the project: there is no backup,
so *restore has never been exercised against production data* either.

```bash
# `output` is POSITIONAL, not --output. And no passphrase is passed here at all: once
# action #2 is done, BACKYARD_BACKUP_PASSPHRASE is in the container's environment and the
# command reads it from there. backup_instance deliberately refuses a passphrase on argv so
# it cannot reach shell history or `ps`; inlining one would walk around the protection the
# command exists to provide.
ssh -i ~/.ssh/backyard_vm ubuntu@$BACKYARD_HOST \
  'cd ~/backyard && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web \
     sh -c "DJANGO_SECRET_KEY=\$(cat /data/secret_key) \
        python manage.py backup_instance /data/backup-$(date +%F).tar.enc"'
# then copy it OFF the box, and record the passphrase location on the succession sheet.
# DOUBLE quotes: single ones stop $BACKYARD_HOST expanding, so this used to try to reach a
# host literally named "$BACKYARD_HOST" and fail -- on the step that turns a backup sitting
# on the same disk into an actual backup. Double quotes still stop the LOCAL shell
# expanding the glob, which is what scp needs (the remote end expands it).
mkdir -p ~/backyard-backups
scp -i ~/.ssh/backyard_vm "ubuntu@$BACKYARD_HOST:/data/backup-*.tar.enc" ~/backyard-backups/
```

## Founder-owned, unchanged

1. The **90-minute QA walk** (`docs/runbooks/founder-qa.md`) — the gate.
2. **Post something to a whole side of the family BEFORE handing out elder links**, or a
   grandparent opens her link to an empty page and nobody can preview it for her.
3. **Wipe the demo family** (`manage.py wipe_demo_data --dry-run`, then `--yes`) before
   the first real invite. The old `BACKYARD_DEMO_WIPE=1` was unscoped and is removed.
4. The **S-601** decision: may an elder follow a link off her page? (Recommendation on
   record: keep the rule.)
5. The **go-public** decision (criterion 7).
