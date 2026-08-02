# Third-party notices

Backyard itself is licensed under [AGPL-3.0-or-later](LICENSE).

This file covers material **redistributed inside this repository and served by a running
instance** — the things whose licences travel with the copy rather than being satisfied by a
dependency manifest. Python dependencies are resolved at install time from `pyproject.toml`
and `uv.lock` and are not vendored here.

## Fonts

**Atkinson Hyperlegible**
Copyright 2020 Braille Institute of America, Inc., with Reserved Font Name
"Atkinson Hyperlegible".
Licensed under the **SIL Open Font License, Version 1.1**.

- Files: `src/core/static/backyard/fonts/atkinson-hyperlegible-{regular,bold,italic}.woff2`
- Full licence text: [`src/core/static/backyard/fonts/OFL.txt`](src/core/static/backyard/fonts/OFL.txt)
- Upstream: <https://www.brailleinstitute.org/freefont>

The copyright line above was read out of the font binary's own `name` table (nameID 0), not
copied from a third-party summary.

OFL §2 requires that **every** redistributed copy carry the copyright notice and the licence.
That includes this repository, the static files a running instance serves, and any container
image built from it — the licence file sits beside the fonts so it is collected and shipped by
the same `collectstatic` step, rather than depending on someone remembering.

The font is not incidental: it was chosen for legibility on the elder path, where the whole
point is that someone with imperfect sight can read the page.

## Why this file exists

It did not, and the fonts were redistributed without their licence for the project's life — a
straightforward OFL violation, in a public repository, under a project whose own README makes
a point of its licensing rigour. It was found by an all-angles exposure audit on 2026-08-01,
not by anyone reading the licence.

The exposure grows rather than shrinks: publishing container images (roadmap Phase 5) turns
this from a source-tree omission into a **binary redistribution** with attribution duties, and
that is exactly the moment nobody re-reads the font licence.
