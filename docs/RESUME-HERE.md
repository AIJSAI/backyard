# Resume here

A handoff note for whoever picks the work up next. It is in the open because the project is
built in the open; it is **not** documentation, and it is not a status board.

The rule this file is written under, which it learned by breaking: **state the rule and the
command that derives a number, never the number.** Any count written down here is stale the
moment somebody merges — including the count in a paragraph that merging this one changes.
So every row below is something to run.

Its predecessor grew to five hundred lines and ended up contradicting itself inside one
file, telling the operator both that the family database was encrypted and that it was
sitting in plaintext three copies deep. It is kept, unedited, at
[`docs/archive/2026-08-07-resume-here.md`](archive/2026-08-07-resume-here.md), because a
handoff that quietly loses its history stops being checkable — but nothing in it describes
the instance now.

---

## Where things are

| question | run this |
|---|---|
| what is `main`? | `git log --oneline -1 origin/main` |
| what is tagged? | `git tag --list` |
| anything open? | `gh pr list --state open` and `gh issue list --state open` |
| is the tree green? | `gh run list --branch main --limit 1`, then `gh run view <id> --json jobs` |
| what does the release say? | `CHANGELOG.md` — what does not work is as prominent as what does |

**Production** is one small Linux VM with a public IP, serving one domain over TLS from a
four-container compose stack (Caddy, the web app, a worker, Postgres). It is a **git
checkout**, so the deployed revision is a thing you can ask it for rather than infer. The
host, the provider and the credentials are not written down in a public repository: they are
on the succession sheet ([`runbooks/backup-recovery-sheet.md`](runbooks/backup-recovery-sheet.md))
and in the password manager it names.

Set the host once, as a placeholder, so nothing here is a target list:

```bash
export BACKYARD_HOST=<the instance IPv4 or hostname>
```

## Deploying (there is no automation)

There is no pipeline. A deploy is a tag checkout and a rebuild, run on the box:

```bash
ssh ubuntu@$BACKYARD_HOST 'cd ~/backyard && git fetch --tags && git checkout <tag>'
ssh ubuntu@$BACKYARD_HOST \
  'cd ~/backyard && docker compose -f docker-compose.yml -f docker-compose.prod.yml build --pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d'
```

**`build --pull`, and not `up --build`.** The app image installs `postgresql-client-18` and
`ffmpeg` in a layer above `python:3.13-slim`, and `up --build` reuses whatever base the box
has cached — so the client that takes your pre-flight backup and the decoder that reads
video somebody sent your family would stay at their first-build versions for the life of the
box. **Chained**, because a failed build must not be followed by an `up` that silently
restarts the image you already had. `self-host.md`'s Upgrades section says the same thing at
length, and `handover.md` §2 again; this is the one the live instance is redeployed from.

**Rebuild, never just restart** — the image ships `staticfiles`. And `up -d` with no service
named, so the **worker** moves too: a deploy that restarts `web` only leaves every async
path (digests, transcoding, link previews, metrics rollups, session cleanup) running
week-old code, which is a thing that happened and took a while to notice.

The earlier `tar czf - src | ssh …` deploy is gone with the file that described it. It
shipped `src/` only, so a rebuild silently used the old dependencies, the old Caddyfile and
the old seed, and keeping a list of "which non-`src` paths changed" up to date was a
permanent source of wrong numbers. A checkout has no such list.

Moving the instance to different hardware is its own procedure:
[`runbooks/move-to-a-new-server.md`](runbooks/move-to-a-new-server.md).

## Backups and restore

The instance backs itself up nightly to its own data volume and says so on the weekly health
email, on `/healthz`, and in the worker log when it cannot. That is **not** an off-box copy:
the copy job lives on the host, and the instance only knows how it went if the job writes
`.offbox-status.json` back. All of it, including the restore drill and what a restore does
to credentials people are holding, is in
[`runbooks/backup-restore.md`](runbooks/backup-restore.md).

Three things worth knowing before you need them:

- **There is no key escrow.** Lose `BACKYARD_BACKUP_PASSPHRASE` and every archive taken with
  it is unreadable by anyone, permanently.
- **A restore is a security event.** It kills every elder link, digest link, reply address
  and session the archive carried, and it brings back anybody removed since the backup.
- **A restore does not migrate.** Restart `web` and `worker` afterwards and require
  `manage.py migrate --check` to exit 0 before telling anyone the instance is up.

Running any management command on the box needs the persisted secret exported first — the
entrypoint exports it for gunicorn only, so a fresh `exec` has never had it:

```bash
ssh ubuntu@$BACKYARD_HOST \
  'cd ~/backyard && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web sh -c "export DJANGO_SECRET_KEY=\$(cat /data/secret_key); python manage.py check"'
```

A bare `exec web python manage.py …` exits with `DJANGO_SECRET_KEY is empty` before argparse
is reached, which reads like a broken command rather than a missing variable.

## Where the open work lives

**GitHub issues.** `gh issue list --state open` is the list; nothing in this repository is a
second copy of it, and a document claiming to be "the single list" is how thirty items went
missing once already.

Two documents remain and neither is a backlog:

- [`OUTSTANDING.md`](OUTSTANDING.md) — the security-pass record and the session records
  behind it. Findings are kept with their verdicts so the reasoning survives; anything still
  open carries its issue number.
- [`PATH-TO-100.md`](PATH-TO-100.md) — the v1.0 criteria. A box is checked only with an
  evidence link on the same line, and CI enforces it.

The gate before anything is shared with anybody is still the founder's own QA walk,
[`runbooks/founder-qa.md`](runbooks/founder-qa.md).

## The runbooks

[`self-host.md`](runbooks/self-host.md) (the install, and the honest limitations) ·
[`backup-restore.md`](runbooks/backup-restore.md) ·
[`backup-recovery-sheet.md`](runbooks/backup-recovery-sheet.md) (print it) ·
[`move-to-a-new-server.md`](runbooks/move-to-a-new-server.md) ·
[`founder-qa.md`](runbooks/founder-qa.md) ·
[`setting-up-your-side.md`](runbooks/setting-up-your-side.md) ·
[`handover.md`](runbooks/handover.md) · [`shutdown.md`](runbooks/shutdown.md) ·
[`live-repro.md`](runbooks/live-repro.md) ·
[`measure-transcode.md`](runbooks/measure-transcode.md)

[`docs/README.md`](README.md) is the map to everything else.

## The environment recipe (non-obvious, cost real time)

The compose Postgres does **not** publish 5432, so the tests need their own database. One
shared container, and a database name per checkout so two runs cannot drop each other's:

```bash
docker run -d --name backyard-testdb -p 127.0.0.1:5432:5432 \
  -e POSTGRES_DB=backyard -e POSTGRES_USER=backyard -e POSTGRES_PASSWORD=ci-not-a-secret \
  postgres:18-alpine

export POSTGRES_HOST=127.0.0.1 POSTGRES_PASSWORD=ci-not-a-secret
export POSTGRES_DB=test_backyard_<this checkout>
export DJANGO_SECRET_KEY=<50+ throwaway characters; settings refuses a short one>
```

Then the gate, **one command at a time**, reading each exit code. Chaining these with `&&`
and reading the tail as evidence about the head is how "lint ok" got reported over a tree
with nine lint findings:

```bash
uv run ruff check src scripts
uv run ruff format --check src scripts
uv run mypy src
uv run pytest -q
make gates
make secrets
```

`make e2e` is the browser lane; a plain `pytest` deselects it and still reads green.

Traps that each cost a cycle:

- **The local lane needs Docker running.** With the daemon down, `pytest` returns hundreds
  of errors whose *first* line is `connection to server at "127.0.0.1", port 5432 failed`.
  Read that line before diagnosing the wall of `ProgrammingError` under it.
- **Two pytest runs sharing one `POSTGRES_DB` drop each other's database mid-run**, and the
  false red looks like a real one (`column … does not exist`, `DeadlockDetected`,
  `AdminShutdown`). Give each checkout its own name, as above. Before believing a red, run
  `ps aux | grep [p]ytest`.
- **The `secrets` job scans every branch.** CI checks out with `fetch-depth: 0`, so
  `gitleaks git .` walks the whole commit graph: one credential-shaped literal on a single
  unmerged branch fails `secrets` on every open PR at once. `make secrets` reproduces it.
- **`BACKYARD_BASE_URL` must point at the dev server** for a local live instance, or invite
  links are minted for `localhost:8000` where a stale container may answer.
- **`MEDIA_ROOT` defaults to `/data/media`**, which is read-only outside the container.
- **allauth rate-limits logins per address** (`30/5m`, `10/1h` for *failures*), and so does
  the app's own link-surface throttle. Do not probe a limit with wrong passwords — that
  burns the failure budget for an hour. Clear it by truncating `backyard_cache`.

## Method that keeps paying off

- **Prove every new guard fires** by breaking the thing it guards, then restoring. Several
  guards in this repository were vacuous until somebody probed them.
- **Assert behaviour, not prose.** Three tests have broken on legitimate copy because they
  searched for a bare word the page says for good reasons.
- **Comments ship.** A CSS comment quoting a removed tagline kept sending it to every
  client; another broke a guard asserting a word was absent from a token surface.
- **Read the artifact before describing its state**, including your own last commit. Most of
  the corrections in this repository's history are a document describing a state that had
  stopped being true, found by opening the code instead of the neighbouring document.
