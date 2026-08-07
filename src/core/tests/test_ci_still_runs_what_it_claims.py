"""Nothing in this repository read `ci.yml`, so deleting a CI step left the gate green.

Branch protection requires five CONTEXTS — `gates`, `code`, `e2e`, `secrets`, `deps`. A
context is a whole job. Delete the bandit step, or the gitleaks self-test, or the compose
live probe, or `fetch-tags: true`, and the job still succeeds and still reports its context
as green. Every one of those is load-bearing, and several exist because a defect got through
without them:

* `fetch-tags: true` — `actions/checkout` fetches shallowly WITHOUT tags, so
  `test_documented_version_resolves` hit `pytest.skip` on every run and had NEVER executed on
  a runner. A gate that silently skips is this repo's most-repeated failure mode.
* the gitleaks self-test — the previous one planted only the shape its rule already handled,
  so it could not observe a blind spot. It reported green over a config that caught 1 of 6
  realistic credential plants.
* the dep-scan and SAST self-tests — each plants something that MUST be caught, which is the
  only reason to believe those steps do anything at all.
* the compose live probe — the only place ADR-004's role split and first-run boot are
  exercised against real containers.

This is the meta-gate: the one that notices when the others are removed. It reads the
workflow as text on purpose. Parsing the YAML and asserting on structure would be prettier
and would not answer the question — the question is whether a specific, named, load-bearing
line is still there.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_CI = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
_NAME_KEY = re.compile(r"-?\s*name:")

# Each entry: the literal that must appear, and why its removal would be invisible.
#
# A fragment prefixed with `=` must equal a whole command line rather than appear inside
# one. That exists because `run: uv run pytest` is a strict PREFIX of
# `run: uv run pytest -m e2e -v`: no substring of the unit-lane line is absent from the
# e2e line, so as a substring rule the unit suite could be deleted entirely and this file
# would still pass. Every other entry is a plain substring.
_LOAD_BEARING = {
    "fetch-tags: true": (
        "without it checkout fetches no tags, test_documented_version_resolves skips on "
        "every run, and the version gate becomes decorative — which it already was once"
    ),
    "=run: uv run pytest": "the unit suite",
    "uv run mypy src": "the typecheck",
    "uv run ruff check src scripts": (
        "the lint, over BOTH directories. It covered `src` only while FOUR gates — "
        "check_stories, check_digest_confinement, check_compose_overlay and check_signoff — "
        "lived in `scripts/` and were never linted"
    ),
    "pytest -m e2e": (
        "the browser lane. It is deselected by `addopts = -m 'not e2e'`, so if this step "
        "goes, nothing anywhere runs the tests that drive a real browser"
    ),
    "manage.py check --deploy": "the production-posture check (TS-DJ-10)",
    "scripts/check_signoff.py": (
        "the DCO check on the commits a PR adds. CONTRIBUTING promises every commit is "
        "signed off, and 85 of the first 154 were not — the rule existed in prose and "
        "nowhere else"
    ),
    "scripts/check_compose_overlay.py": (
        "the guard on the gap between the stack CI boots and the stack README tells a "
        "stranger to boot. CI runs the BASE compose file; the install command uses the prod "
        "overlay, and no runner can publish :443 or get a real certificate. This keeps the "
        "untested delta to domain, TLS and ports"
    ),
    "docker build": "the image actually building",
    # The bare words `gitleaks git`, `pip-audit`, `bandit` and `VACUOUS GATE` were all
    # ambiguous: each also occurs in the SELF-TEST that proves the real step works, and in
    # prose. `bandit` appeared 12 times, 4 of them in comments. Deleting the real scan left
    # every one of them satisfied. These name the actual invocation.
    "gitleaks git --no-banner --redact -c .gitleaks.toml .": "the full-history secret scan",
    "pip-audit --progress-spinner off --ignore-vuln": "the dependency CVE scan",
    "uvx bandit==1.9.2 -r src --exclude src/core/tests": "SAST over production code",
    "VACUOUS GATE: pip-audit passed a known-vulnerable jinja2": (
        "the dep-scan self-test's failure marker: a planted vulnerable package MUST be "
        "caught, and this string is how the step proves it was"
    ),
}

# Steps whose entire purpose is to prove another step is not vacuous. Losing one of these
# leaves the step it guards running and unproven, which is the state this repo keeps finding.
_SELF_TESTS = (
    "Selftest, per-rule",
    "Dep-scan self-test",
    "SAST self-test",
)


def _ci() -> str:
    return _CI.read_text(encoding="utf-8")


def _command_lines() -> list[str]:
    """The lines that DO something, with commentary and step names removed.

    A guard that searches the whole file can be satisfied by a sentence describing the step
    it is meant to find. That is not hypothetical here: `bandit` occurred 12 times in this
    workflow, four of them inside comments explaining why the bandit step is configured the
    way it is — so deleting the scan and keeping the explanation kept this file green.

    Step names go too, for the same reason and one more: a name is a label a human chose,
    and renaming a step must not be able to satisfy an assertion about what it RUNS.
    """
    kept = []
    for line in _ci().splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or _NAME_KEY.match(stripped):
            continue
        kept.append(stripped)
    return kept


def _matches(fragment: str) -> list[str]:
    """Command lines this fragment identifies. `=` prefix means whole-line equality."""
    if fragment.startswith("="):
        wanted = fragment[1:]
        return [line for line in _command_lines() if line == wanted]
    return [line for line in _command_lines() if fragment in line]


def test_the_workflow_file_is_where_we_think() -> None:
    """Denominator. Every assertion below is a substring check against one file; if the path
    is wrong they all fail together for the wrong reason, and if the file were ever empty
    they would fail loudly rather than passing — but say so plainly either way."""
    assert _CI.is_file(), f"no workflow at {_CI}"
    body = _ci()
    assert len(body) > 2000, f"{_CI.name} is {len(body)} bytes; that is not this workflow"
    for job in ("gates:", "code:", "e2e:", "secrets:", "deps:"):
        assert f"\n  {job}" in body, (
            f"job `{job}` is gone from the workflow, but branch protection still requires a "
            "context by that name — a required context that no job produces blocks every "
            "merge, and one that is quietly renamed stops being required at all"
        )


@pytest.mark.parametrize(("fragment", "why"), sorted(_LOAD_BEARING.items()))
def test_a_load_bearing_ci_step_has_not_been_removed(fragment: str, why: str) -> None:
    assert _matches(fragment), (
        f"`{fragment}` is no longer a command in .github/workflows/ci.yml — {why}.\n\n"
        "Removing it does not turn any context red: branch protection requires the JOB, and "
        "the job still succeeds with the step gone. That is why this test exists."
    )


@pytest.mark.parametrize("fragment", sorted(_LOAD_BEARING))
def test_each_fragment_identifies_exactly_one_command(fragment: str) -> None:
    """A fragment matching twice cannot certify that either step survives.

    This is the rule, and the entries above are only its current output. Without it, the
    natural fix for "this fragment is too generic" is to pick a longer literal — which is
    the same bug one revision later, because nothing re-measures it. Here, a fragment that
    stops being distinctive fails the moment the workflow makes it ambiguous.

    Every ambiguity this rule has caught was a real hole: `gitleaks git` also matched the
    self-test probe; `pip-audit` and `bandit` also matched their own self-tests; the four
    `VACUOUS GATE` markers are indistinguishable from each other; and `uv run pytest` is a
    strict prefix of the e2e line, so the unit suite could have been deleted outright.
    """
    hits = _matches(fragment)
    assert len(hits) == 1, (
        f"`{fragment}` matches {len(hits)} command lines, so it cannot prove any one of them "
        f"is still there — deleting one leaves the others satisfying it:\n"
        + "\n".join(f"  {line}" for line in hits)
        + "\n\nMake the fragment name a single invocation (a `=` prefix requires the whole "
        "line, for the case where one command is a prefix of another)."
    )


@pytest.mark.parametrize("step", _SELF_TESTS)
def test_the_self_tests_that_prove_the_other_steps_are_not_vacuous_remain(step: str) -> None:
    """A scanner that runs and finds nothing is indistinguishable from a scanner that is
    misconfigured. These steps plant something that MUST be caught, and are the only reason
    to believe the scan above them does anything."""
    names = [
        line.strip()
        for line in _ci().splitlines()
        if _NAME_KEY.match(line.strip()) and not line.strip().startswith("#")
    ]
    assert sum(step in name for name in names) == 1, (
        f"the `{step}` step is gone. The scan it guards still runs and still reports green, "
        "and nothing now distinguishes 'found nothing' from 'looking in the wrong place' — "
        "which is exactly how this repo's secret scanning reported clean while catching 1 "
        "realistic plant in 6."
    )
