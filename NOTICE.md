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

**What was and was not missing, precisely.** OFL §2 requires each redistributed copy to carry
the copyright notice *and* the licence, and it explicitly accepts "machine-readable metadata
fields within text or binary files" as a location. Measured against the actual binaries:

| OpenType `name` field | | |
|---|---|---|
| nameID 0, copyright | **present** in all three faces | §2's copyright half already satisfied, on every copy, everywhere it travels |
| nameID 13, licence text | **absent** | the gap |
| nameID 14, licence URL | present | a pointer to the licence, not the licence |

So the fonts were never unattributed — the copyright line above was read out of the binaries
themselves. What is missing is the licence *text*, which a URL references rather than
includes. `OFL.txt` closes that, and sits beside the fonts so `collectstatic` ships it with
them into any container image rather than the obligation depending on someone remembering.

The font is not incidental: it was chosen for legibility on the elder path, where the whole
point is that someone with imperfect sight can read the page.

## Why this file exists

An all-angles exposure audit on 2026-08-01 first reported this as "three fonts with no licence
and no attribution — a straightforward violation." That was **wrong**, and its own verification
pass caught it: the copyright notice is embedded in every face and OFL §2 accepts exactly that
location. The real gap is the narrower one above.

Recording the correction rather than the original claim, because the overstated version is the
more quotable one and this project has been bitten before by a finding that was real with a
false mechanism.

The exposure grows rather than shrinks: publishing container images (roadmap Phase 5) turns
this from a source-tree omission into a **binary redistribution** with attribution duties, and
that is exactly the moment nobody re-reads the font licence.
