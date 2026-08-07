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

from pathlib import Path

import pytest

_CI = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"

# Each entry: the literal that must appear, and why its removal would be invisible.
_LOAD_BEARING = {
    "fetch-tags: true": (
        "without it checkout fetches no tags, test_documented_version_resolves skips on "
        "every run, and the version gate becomes decorative — which it already was once"
    ),
    "uv run pytest": "the unit suite",
    "uv run mypy src": "the typecheck",
    "uv run ruff check src": "the lint",
    "pytest -m e2e": (
        "the browser lane. It is deselected by `addopts = -m 'not e2e'`, so if this step "
        "goes, nothing anywhere runs the tests that drive a real browser"
    ),
    "manage.py check --deploy": "the production-posture check (TS-DJ-10)",
    "docker build": "the image actually building",
    "gitleaks git": "the full-history secret scan",
    "pip-audit": "the dependency CVE scan",
    "bandit": "SAST over production code",
    "VACUOUS GATE": (
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
    assert fragment in _ci(), (
        f"`{fragment}` is no longer in .github/workflows/ci.yml — {why}.\n\n"
        "Removing it does not turn any context red: branch protection requires the JOB, and "
        "the job still succeeds with the step gone. That is why this test exists."
    )


@pytest.mark.parametrize("step", _SELF_TESTS)
def test_the_self_tests_that_prove_the_other_steps_are_not_vacuous_remain(step: str) -> None:
    """A scanner that runs and finds nothing is indistinguishable from a scanner that is
    misconfigured. These steps plant something that MUST be caught, and are the only reason
    to believe the scan above them does anything."""
    assert step in _ci(), (
        f"the `{step}` step is gone. The scan it guards still runs and still reports green, "
        "and nothing now distinguishes 'found nothing' from 'looking in the wrong place' — "
        "which is exactly how this repo's secret scanning reported clean while catching 1 "
        "realistic plant in 6."
    )
