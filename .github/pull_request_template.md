<!--
Describe the net base→head diff, not the journey. If you tried three approaches, the PR is
about the one that landed.
-->

## What this changes

## Why

<!-- If it traces to a story in stories/stories.yaml, name it. If it has no story, say so and
     propose one — stories are the spec here. -->

## How it was verified

<!-- Not "tests pass" — what did you actually run, and what did it say? A live repro of the
     changed path beats a green suite when the two disagree.

     If you added a guard or a test, break the thing it guards and confirm it fails. A guard
     that has never failed is not known to work. Say which probes fired and which did not. -->

- [ ] `ruff check` + `ruff format --check` + `mypy` + `pytest` green locally
- [ ] Any new guard proven to fail when the thing it guards is broken
- [ ] Touches auth, media, tokens, external input, or an audience query → read
      [the threat model](../docs/security/threat-model.md) row it affects

## Anything you decided not to do

<!-- Scope you deliberately left out, and why. Worth more than it looks. -->
