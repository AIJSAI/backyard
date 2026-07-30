# Hardening the repo as a public artifact

An audit of Backyard *as a thing strangers find*, rather than as a codebase. The code was in
much better shape than its public face. One finding was live.

## 1. A working production password sat in the public repository

`scripts/demo_seed.py` carried:

```python
PW = "backyard-qa-2026"  # noqa: S105 - a disposable demo credential, wiped before any share
```

**That password signed in to `https://backyard.family` as a seeded member.** It was used to do
exactly that during the S-904 verification an hour before this audit — which is how it was
noticed. Anyone reading the public repo could have done the same.

The comment was doing the security work. *"Wiped before any share"* is a promise about a future
action, guarding a credential that worked at that moment on an internet-reachable host. Impact
was bounded today (demo content, no real family data), and would have become a stranger with a
session in the family's feed the moment real data landed or a wipe was partial.

### The gate was blind, and provably so

```
$ gitleaks detect -c .gitleaks.toml
287 commits scanned.
no leaks found
```

Not allowlisted — gitleaks simply does not match a human-chosen password assigned to `PW`. And
the CI selftest that proves the secrets job non-vacuous **plants an AWS-shaped key**, so it
proves the scanner catches high-entropy provider credentials, which is the class this was not.
The blindness is exactly aligned with the likeliest real mistake: a hobbyist self-hoster commits
a password a person chose, not an API key.

`docs/PATH-TO-100.md`'s "zero secrets in history" box is **qualified in place** rather than
silently left standing.

### The fix, and the guard

- `scripts/demo_seed.py` mints `secrets.token_urlsafe(12)` per run and prints
  `DEMO_PASSWORD=<16 url-safe random characters>` as its last line. Verified end to end: a fresh
  seed printed one, and the screenshots below were captured by signing in with it.
- **Two more copies of the same mistake**, which the audit's first pass missed and the guard
  found: `docs/design/tools/seed_demo.py` and `docs/design/tools/capture.py` each hid a literal
  inside `os.environ.get("BACKYARD_DEMO_PASSWORD", "local-demo-only-not-a-secret")`. A literal
  default is a committed credential wearing an env var's clothes, and my own manual AST sweep
  reported both as clean because the literal is an *argument*, not the assigned value.
- `src/core/tests/test_no_hardcoded_demo_credentials.py` is the enforcing mechanism. It uses
  `ast`, not a text search, so a comment beside the line cannot defeat it and reformatting
  cannot either. It catches both shapes, asserts it actually scanned files (an empty file list
  would pass while checking nothing), and stays quiet on ordinary strings.

**Probed:** restoring the plain literal fails it; restoring the env-fallback shape fails it;
removing the tab-keeping and non-credential cases each fail their own test.

**Still operator-owned:** the live instance's demo accounts still exist with the old password
until it is re-seeded or wiped. The repo no longer publishes it, which closes the disclosure;
rotating the live accounts is one command and is in the handoff.

### The same gate then caught me, an hour later

The first push of this very PR **failed the `secrets` job**. The cause was this receipt: the
line above originally quoted the real generated password as evidence that the fix worked.

```
rule:   generic-api-key
file:   docs/receipts/2026-07-29-public-repo-hardening.md line 44
match:  DEMO_PASSWORD=<the actual value>
```

Which is the whole finding in miniature. The scanner is blind to `PW = "backyard-qa-2026"` and
catches a 16-character url-safe random string on sight — **the fix moved the credential into the
class the gate can see.** It also means that had the fix been rolled out on production and the
output pasted anywhere in the repo, the gate would have stopped it.

Redacted, not allowlisted; an allowlist entry would have re-opened the hole for the shape that
now works. The value is gone from the branch's history too: force-push is deny-listed in this
environment and rewriting shared history is not worth doing for a throwaway local password, so
the branch was rebuilt from `main` with the redacted text from its first commit — which is also
why this PR has a lower number than the one it replaces.

## 2. The README told strangers to install a moving target

`git clone` of `main`, with **no tags, no changelog, no release** in 111 commits. So anyone
following the front page got whatever was pushed minutes earlier — possibly mid-refactor. For
software that holds a family's photographs, "clone HEAD" is not an install path.

- `CHANGELOG.md`, with a `v0.1.0` entry that lists **what does not work** as prominently as what
  does: the manual step reply-by-email needs, the unbuilt photo frame, no published images, one
  instance ever deployed, no independent security review.
- `pyproject` `0.1.0.dev0` → `0.1.0`; the README installs `--branch v0.1.0` and says why.
- `SECURITY.md` gains the supported-versions table it had been promising "once code ships" — and
  its acknowledgment window went from **72 hours to "about a week"**, because a solo maintainer
  promising 72 hours is a number nobody should believe.

## 3. Zero diagrams, in 339 tracked files

No mermaid, no SVG, nothing. The pod/yard model is the hardest idea in the product and existed
only as prose. `docs/README.md` now opens with four, as mermaid so they render on GitHub and
cannot rot into a stale PNG:

1. **Pods and yards** — the data model, including the bridging household and the fact that the
   two sides cannot learn the other exists.
2. **How a grandparent gets in without an account** — the token-to-cookie exchange, and what
   one Regenerate click kills.
3. **What happens to a photograph** — resize, strip, re-encode, derivatives, access-checked
   serve, and the one thing delete cannot recall.
4. **One audience query, five surfaces** — the structural rule that keeps the rest true.

### Verified by rendering them, not by "no error"

Parsed with the **real mermaid engine** in a browser (all four produce SVG), then **rendered to
PNG and looked at** — which is the only reason two of them are usable:

- **Diagram 1 was a mess.** It parsed fine and rendered 2125px tall with edge labels clipped and
  floating over the boxes, because I had drawn an edge from each pod *into its own enclosing
  subgraph* — containment and an edge saying the same thing. Rebuilt as a flat tree: **622px**,
  legible.
- **Diagram 3 was a 9-node horizontal strip 139px tall**, which GitHub would scale to container
  width and render unreadable, with the delete branch floating orphaned. Rotated to vertical and
  the branch attached to the volume it actually comes from.

"It renders without error" would have shipped both.

## 4. Altitude: 90 files in `docs/`, no index

| | count |
|---|---|
| receipts (internal work log) | 40 |
| research / design / retro / devlog / audits | 15 |
| runbooks (actual public docs) | 9 |
| decision records | 6 |

**~55 of 90 files are internal process artifacts** sitting at the same level as "how to install
this". `docs/README.md` now splits three doors — *run it* / *understand why* / *how it was
actually built* — and labels `RESUME-HERE.md` as the internal handoff note it is.

## 5. Doc rot: the repo claimed it was not built

A stranger reading it would have concluded this was vapourware, while 46 of 47 stories passed on
a live TLS domain:

| where | said | reality |
|---|---|---|
| README | "What v1 **will** be" | it does those things |
| README | "that trade-off gets its own decision record **before code**" | [ADR-003](../adr/ADR-003-token-links.md), nine days old |
| README | principles "(draft)" | ratified 2026-07-20 |
| README | ADRs are "every load-bearing call **to come**" | six exist |
| README | devlog is "the running story" | one entry, from day zero — now points at the 40 receipts, which are the running story |
| CONTRIBUTING | "code contributions become practical **once the architecture ADR lands**" | ADR-002 landed 2026-07-20 |
| SECURITY | "**once code ships**, this file gains a supported-versions table" | it shipped |

Also fixed: three committed design tools hardcoded `ROOT` to **one machine's per-session scratch
directory**, so they could not run for anybody else — including a later session on the same
machine.

Added: a PR template that asks for the base→head diff and whether new guards were proven to
fail, and issue templates including one for *"a claim in the threat model looks wrong"*, which is
the most useful thing an outsider can file against this repo.

## 6. Screenshots

The README had **none**, for a product whose pitch is that it feels calm. The four existing
images in `docs/design/reference/` are from 2026-07-22 — the design v2 run **the founder
rejected** — so linking them would have misrepresented the product. Captured fresh at v3.2:
feed on desktop, feed on a phone, and the elder path.

Captured honestly: the first attempt showed the S-906 newcomer orientation card filling the
frame with the posts below the fold, so it was re-taken with the card dismissed. The images in
the demo post are the seed's **generated fixtures, not photographs** — the README says so,
because no real family content goes in this repository and that rule has no exceptions.

The elder capture also re-confirmed diagram 2's claim as a side effect: opening
`/t/<token>/` lands on `/e/` — the credential is out of the URL after the first request.

## Gate

ruff + format + mypy(168) clean · **pytest 777 passed / 2 skipped** (771 before, +6 here) ·
4 mermaid diagrams parsed by the real engine and inspected as images · fresh seed verified to
mint and print a password · gitleaks re-run.
