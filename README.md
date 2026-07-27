# Backyard

**A private, self-hosted social network for your extended family.** Each household gets a pod. Each side of the family shares a backyard.

> Status: **pre-release, July 2026.** It runs, and it is not shared with anyone yet. The
> author's own family gets it first, after he has manually QA'd it end to end. Built in
> public, decisions first, code second — the honest ledger of what is and is not done
> lives in [PATH-TO-100.md](docs/PATH-TO-100.md) and the
> [self-audit](docs/audits/2026-07-26-honest-100-audit.md), which is deliberately unkind
> to this project.

**[→ Install it](docs/runbooks/self-host.md)** — one `docker compose` command on a fresh
Linux box, with TLS. Read the honest limitations there first, especially about email.

## Install

```bash
git clone https://github.com/AIJSAI/backyard.git && cd backyard
cp .env.example .env        # then set the three POSTGRES_* passwords
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Open your domain, and the first-run screen makes you the instance admin. The full guide —
DNS, TLS, email, backups, upgrades, and what genuinely does not work yet — is
**[docs/runbooks/self-host.md](docs/runbooks/self-host.md)**.

## Why this exists

It started with late-night texts. I kept finding things my family would love at 1am, and the options were "wake them up" or "forget it by morning." Group chats are interruptions. Big platforms treat your family as a growth channel. And I couldn't find a calm, private place where a family just posts things and everyone catches up whenever they want; the closest attempts are in the [OSS landscape](docs/research/2026-07-19-github-oss-landscape.md).

Then a family wedding made the second problem obvious: past your own household, you quietly lose track of everyone. Cousins grow up and nobody hears the small stuff.

Backyard is for both problems: an async feed for your household, and ambient awareness across the whole extended family.

## What v1 will be

- A calm feed of links, photos, and short updates. Chronological. It ends.
- **Pods and yards**: every household is a pod; each branch of the family is a yard with its own shared **backyard**. A household can belong to more than one yard, and nothing forces the sides together.
- An elder path that requires no account and no app store: tap a link and you're in. Reply by email if that's your thing. (Yes, a link that just works is a link that can be forwarded. That trade-off gets its own decision record before code.)
- Installable PWA (iPhone and Android, no gatekeepers), with an email digest in and out.
- Profiles that double as the family directory: the names the kids actually use, birthdays surfaced calmly, contact info you control the visibility of.
- A self-host deploy on your own server, with one command as the acceptance bar. Bring your own SMTP; email in and out is the hard part, and the docs will be honest about it.

## What it will never be

- No ads, no tracking, no engagement mechanics. No streaks, no like counts, no read receipts.
- Nothing is amplified. No algorithm decides what your family sees.
- No speech rules baked into the software. Families govern themselves; we ship rooms, not referees.
- No lock-in. Export everything, always.

Full list: [product principles](docs/principles.md) (draft).

## Receipts

This project runs on evidence, in public:

- [Research brief](docs/research/2026-07-19-research-brief.md): the market gap and the peer-reviewed deployment studies behind the design requirements.
- [OSS landscape](docs/research/2026-07-19-github-oss-landscape.md): what exists, what died, and why.
- [Decision records](docs/adr/): license, name, and every load-bearing call to come.
- [Path to 100%](docs/PATH-TO-100.md): the definition of done. A box only gets checked with an evidence link, and CI enforces it.
- [Devlog](docs/devlog/): the running story.

## License

[AGPL-3.0](LICENSE). Rationale in [ADR-000](docs/adr/ADR-000-license.md). Contributions require a DCO sign-off; see [CONTRIBUTING](CONTRIBUTING.md).
