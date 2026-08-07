# Resume here — session state, 2026-08-06/07

Written to survive a context compaction. Read this, then
**[`docs/OUTSTANDING.md`](OUTSTANDING.md)** — the ranked backlog. Its **§7** is the record of
the 2026-08-06 session, and its **§6** is the only record of the 2026-08-01 readiness audit
(that audit has no separate document, which is why its findings had to be re-derived a week
later). Then `docs/PATH-TO-100.md`.

Verify with a primary check (`git log`, `gh pr list`, run the probe an item names) rather
than trusting anything written down — including this file. That instruction earned its keep
twice: OUTSTANDING.md called itself "the single list" and a re-measurement found ~30 items it
did not contain, and this header claimed the production exposures were closed while a third
one was still live.

## SESSION HANDOFF — 2026-08-07

**Read this block first, then verify every line of it with a primary check.** This file has
been wrong before, in this exact header, about exactly the kind of claim it makes.

### Where the code is

Every row is a command, not a fact. Four rounds of review on this table found the same defect
each time — a number, a date or a PR reference that was true when written and false when
read. So it states nothing that can go stale; it tells you what to run.

| question | run this |
|---|---|
| how far past `v0.1.1` is `main`? | `git rev-list --count v0.1.1..origin/main` |
| which PRs are in this release? | `git log --oneline v0.1.1..origin/main \| grep -oE '\(#[0-9]+\)$'` — contiguous from `#127` except `#138` and `#142`, closed unmerged (superseded by `#139`, `#143`) |
| is `v0.1.2` cut? | `git tag --list`. **It was not, as of this being written** — and `README.md`, `docs/runbooks/self-host.md` and `CHANGELOG.md` all name it, so cutting it is the next job |
| anything still open? | `gh pr list --state open` |
| is the tree green? | `gh run list --branch main --limit 1` then `gh run view <id> --json jobs` — CI is the authority, especially when Docker is down locally |

**The next two steps, in order.** Step 1 is several commands and they are deliberately
NOT chained — read each result:

```bash
cd ~/projects/backyard
git checkout main
git pull

# Preconditions: Docker up (Postgres is a container), and no other pytest running —
# the local lane shares one test database and a concurrent run produces false reds.
docker ps >/dev/null || echo "START DOCKER FIRST"
ps aux | grep "[p]ytest"          # must print nothing

# Step 1 — the full gate, ONE COMMAND AT A TIME. Read each result.
# Chaining these with && and reading the tail as evidence about the head is how
# "lint ok" got reported over a tree with nine lint findings.
uv run ruff check src scripts
uv run ruff format --check src scripts
uv run mypy src
uv run pytest -q
uv run pytest -q -m e2e
make gates

# Step 2 — tag, only once every line above was read and green.
git tag -a v0.1.2 -m "v0.1.2"
git push origin v0.1.2
```

Tagging turns the version gate back ON: `_release_in_flight` exempts the newest CHANGELOG
version only while it has no tag, so every `--branch v0.1.2` in `README.md` and `docs/runbooks/self-host.md`
starts being checked against a real tag the moment it exists.

### What is DONE

Every item from the original `OUTSTANDING` §7 audit. §7.8 is a closed-items table, §7.9 was
in flight and has landed, §7.10 is closed, §7.11 records what was found while closing it.
Nothing from the audit is open.

The defects that would have reached the family, each measured not reasoned:

* **The wipe's refusal was blind to `Collector.fast_deletes`** — including `Reaction`, a
  model named in the tuple it iterates. A real relative's reaction was deleted with no
  refusal, absent from the preview, and listed in the receipt afterwards.
* **The seed minted an `INSTANCE_ADMIN` on anyone else's box**, keyed to the literal
  username `james`, unmarked so no wipe removes it, with its password printed.
* **An ad-hoc pod froze permanently** when its owner left, was removed (S-702), or was
  deleted. A *departed* owner also kept control of a group they had walked out of.
* **A parent could not create their own child's account** — permission said yes, the only
  page said 403.
* **15 routes were unreachable** and the product had no sign-out link.
* **Six stories did not exist** while `PATH-TO-100` marked a phase complete citing them.

### What is NEXT — and which parts are the operator's

**Phase 10, the launch.** `docs/runbooks/founder-qa.md` has the sequence. The order matters:

1. Deploy. The deploy is `tar czf - src | ssh …` and ships **`src/` only**. Run the check in
   the "Deploying" section below first — this release's non-`src` delta is
   `caddy/Caddyfile.prod` and `scripts/`.
2. `mark_demo_data --dry-run` — production's demo family **predates the marker**, so
   `wipe_demo_data` correctly finds nothing until this is run. List the yards first; two
   seed scripts used different slugs (`moms-side`/`dads-side` vs `whitfield-side`/…).
3. **OPERATOR JUDGEMENT.** Read the *"Deliberately NOT marked"* list. It names real people.
   In rehearsal it correctly spared the founder, who was in a marked pod *and* their own
   household — a naive rule would have deleted him and locked him out of his own family.
   Confirming that list is a judgement about this family and must not be automated.
4. `wipe_demo_data --dry-run`, read the counts, then `--yes`.
5. Seed the founder's profile, a welcome post and photos **through the product**.
6. Create the real yards; promote uncle and sister to `yard_admin` — *not* instance admin.
7. Register the Resend inbound webhook.
8. **OPERATOR JUDGEMENT.** The founder QA walk (PATH-TO-100 criterion 4, still NOT DONE) and
   the S-721 delegate rehearsal — filed as `spec` today, deliberately not `passing`, because
   it has not been run. The retro is explicit that the founder must not role-play the
   delegate.

### Traps this session paid for

* **A count that includes the document stating it is wrong on arrival.** This handoff said
  "33 PRs"; merging it made 34. Same for "N commits past v0.1.1". Any self-including number
  in a repo document is stale the instant it lands — state the RULE and the command that
  derives the number, never the number.
* **The local test lane needs Docker running.** Postgres is the `backyard-testdb`
  container; with the daemon down, `pytest` returns hundreds of errors whose first line is
  `connection to server at "127.0.0.1", port 5432 failed: Connection refused`. Read that
  line before diagnosing — on 2026-08-07 I read a wall of `ProgrammingError` and concluded
  the test database was missing, when the daemon was simply not running. **CI is the
  authority when local cannot run**: `gh run list --branch main --limit 1` then
  `gh run view <id> --json jobs`.
* **The local pytest lane shares ONE database.** `uv run pytest -q` uses `test_backyard` on
  the shared `backyard-testdb` container, so a second process running pytest in this checkout
  — another session, or your own fanned-out subagents — drops it mid-run. Measured: three
  consecutive false reds (`column "seeded_by" ... does not exist`, `DeadlockDetected`,
  `AdminShutdown: terminating connection due to administrator command`) on a tree that was
  green. Before believing a red, run `ps aux | grep pytest`; to run concurrently, give each
  its own `POSTGRES_DB=<unique>`.

* **`git checkout -- <file>` discards uncommitted work.** It destroyed a template edit
  mid-probe. Back probes up to the scratchpad and restore from there.
* **Never edit a running bash script.** Bash reads it incrementally from a byte offset, so
  an edit can make it resume mid-line. A merge-train helper was edited eight times while
  live; harmless by luck, not by design. Whatever you rebuild, have it take its queue as
  ARGUMENTS rather than as a constant you edit in place. (The 2026-08-07 helper lived in the
  session scratchpad, which is wiped between sessions — it is gone, and that is the second
  lesson: session-scoped tooling does not survive, so anything worth keeping goes in the
  repo.)
* **`gh` reports an in-progress check as the empty STRING**, and jq's `//` defaults only on
  null — so `"" // "RUNNING"` is `""`. The train announced "all five green" over a running
  job because of it.
* **A `&&` chain with output to `/dev/null` will make you misread which command passed.** I
  reported "lint ok" when ruff had never run clean; the tree had 9 lint findings.
* **A probe that does not fire looks exactly like a probe that passed.** Several non-vacuity
  probes silently no-opped (wrong indent, a `-k` filter matching nothing, an equality check
  against a longer line). Assert the mutation applied before trusting the result.

> **Start here after a compaction.** Production is clean as of **2026-08-07 UTC**, and every
> item below was verified from OUTSIDE the box rather than from a command's exit code:
>
> * **The burned credential and the plaintext backups** were closed on the evening of
>   2026-08-01 US Central — **2026-08-02 UTC**, the date the box stamps on its own artefacts
>   (`backup-2026-08-02.bak`). Same moment; compare in UTC when matching a runbook entry to a
>   file on the box (OUTSTANDING §0).
> * **A third live exposure was closed on 2026-08-06**: a relative on the public instance
>   still carried the author's real surname. `b8b9813` had renamed her in the repo and added
>   a guard a week earlier — **the data was never migrated**. A rename in code does not
>   migrate rows. Fixed after an encrypted backup; confirmed by signing in over the public
>   internet and reading `/directory/`.
> * **The `worker` container was running 7-day-old code** — genuinely different images, so
>   every async path (digests, transcoding, link previews, `rollup_metrics`, `clearsessions`)
>   was stale. The deploy step restarts `web` only. Rebuilt; both now carry the same build
>   stamp.
> * **6 orphaned media files** removed, measured rather than estimated. Nothing in the
>   product would ever have removed them: every purge path needs the row.
>
> Secrets live in the **1Password `Backyard` vault**. The **server SSH key is stored as a
> DOCUMENT**, not an SSH Key item, so the 1Password SSH agent does not serve it — fetch with
> `op document get`. The box user is **`ubuntu`**, not `root`, and the box has **no `.git`**:
> it was deployed by file copy, so `git pull` is not the upgrade path there.
>
> There is **no key escrow** for `BACKYARD_BACKUP_PASSPHRASE`: if that item is lost, every
> backup taken with it is permanently unreadable.
>
> **`v0.1.0` is WITHDRAWN.** It carried the burned credential in three tracked files and the
> cross-yard disclosure fixed in #110. The credential is rotated and dead, so this is hygiene
> rather than a live exposure — but do not point anyone at the old tag.

**`v0.1.1` is the current TAG; `0.1.2` is written up in the CHANGELOG but not yet cut.**
Until that tag exists the README points at a version that cannot be cloned, which is the
in-flight window `test_documented_version_resolves` exempts — cut the tag as soon as the
release PRs are merged, because the exemption expires the moment it exists and that is what
turns the check back on. The README installs the tag, not `main`, and `CHANGELOG.md` lists what
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

**This ships `src/` and nothing else.** Most of what lives outside it — `docs/`,
`stories/`, `.github/`, `README.md`, `Makefile`, `.gitleaks.toml` — has no effect on the
running box. Seven paths do:

| path | why it matters at runtime |
|---|---|
| `pyproject.toml`, `uv.lock` | the dependency set `--build` installs |
| `Dockerfile` | how the image is built at all |
| `docker-compose.yml`, `docker-compose.prod.yml` | services, ports, env |
| `caddy/` | the edge config, including every security header |
| `scripts/` | the seed and the operational scripts you run on the box |

A `--build` after a `src`-only push rebuilds with the OLD dependencies, the OLD Caddyfile
and the OLD Dockerfile, silently and with a green-looking deploy. Check before pushing:

```bash
git diff --name-only <deployed-ref>..HEAD \
  -- pyproject.toml uv.lock Dockerfile 'docker-compose*.yml' caddy scripts
```

Empty output means the `src` tar is the whole deploy. Anything listed has to be copied too.

Run for `v0.1.1..main` while preparing `v0.1.2` it returned `pyproject.toml`, `uv.lock`,
`caddy/Caddyfile.prod` and three `scripts/`. Of those, only the caddy config and the seed
change behaviour — the pyproject/lock delta is `pytest`, a dev dependency — and production
already carried the current Caddyfile, verified from outside: no `Server`, no `Via`, and
`content-encoding: zstd` on the front page.

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
