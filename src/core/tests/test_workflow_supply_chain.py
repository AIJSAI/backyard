"""Every workflow's supply-chain and hygiene posture, asserted rather than remembered.

Three properties, each of which was wrong on this repository until 2026-09-19 and each of
which fails silently when it regresses:

1. **Actions are pinned to an immutable reference.** For an ordinary action that is a full
   commit SHA with the release tag in a trailing comment: `actions/checkout@v4` is a pointer
   its owner can move, and moving it is the entire tj-actions supply-chain attack. This
   repository is public, and the workflow the pin sits in runs `uv sync` and `docker build`.
   The comment is not decoration: Dependabot's `github-actions` ecosystem reads it and
   rewrites the SHA and the comment together, which is what stops a SHA pin freezing at
   whatever was current the day somebody pinned it. A pin with no comment is a pin nothing
   will ever update. For a `docker://` container action it is a registry digest instead,
   because what is pinned there is an image rather than a commit.
2. **Every job has `timeout-minutes`.** GitHub's default is six hours. A job that hangs on a
   `wait_for`, a health loop or a stalled TLS handshake holds a runner for six hours and
   reports nothing; on the monitor workflow that is the alarm going quiet on exactly the
   condition it exists to report.
3. **Every workflow declares `permissions`, and a pull-request workflow declares
   `concurrency`.** An undeclared `permissions` block inherits whatever the repository
   default is, which is a setting in a web UI rather than a fact in the tree.

The `concurrency` rule takes "no" for an answer, in writing: a workflow that records in a
comment why it must not cancel or queue is accepted. `monitor.yml` is the case that rule
exists for -- for an alarm, cancelling an in-flight run and queueing runs behind a hung one
are both ways of going silent -- and an exemption that has to be argued in the file is a
different thing from one nobody notices.

Read as text on purpose, the same reasoning `test_ci_still_runs_what_it_claims.py` records:
the question is whether specific, named, load-bearing lines are present, and PyYAML is not a
dependency of this test suite (the `gates` job installs it for the two scripts that need it).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW_DIR = _ROOT / ".github" / "workflows"
_DEPENDABOT = _ROOT / ".github" / "dependabot.yml"

# Whatever a `uses:` line names, and whatever follows it on the line. The reference is
# captured WHOLE rather than split on `@` here: a reference with no `@` at all
# (`uses: actions/checkout`, `uses: docker://vendor/action:latest`) is the most mutable
# form there is, and a pattern that required the `@` skipped those lines entirely instead
# of failing on them.
_USES = re.compile(r"^\s*-?\s*uses:\s*(?P<reference>\S+)\s*(?P<rest>.*)$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
# A container action pins an IMAGE, so its immutable form is a registry digest rather than a
# git commit: `uses: docker://image@sha256:<64 hex>`.
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
# The trailing comment Dependabot reads and rewrites: `# v7.0.1`, `# v10.1.0`.
_VERSION_COMMENT = re.compile(r"^#\s*v\d[\w.\-+]*\s*$")

_JOB = re.compile(r"^  (?P<name>[A-Za-z_][\w-]*):\s*$")
_JOB_KEY = re.compile(r"^    (?P<key>[A-Za-z_-]+):")

_CONCURRENCY_BLOCK = re.compile(r"^concurrency:[ \t]*$(?P<body>.*?)^\S", re.M | re.S)
_CANCEL_IN_PROGRESS = re.compile(r"^\s*cancel-in-progress:\s*(?P<value>.*?)\s*$", re.M)

# A workflow that says, in a comment, why it has no concurrency group. A phrase rather than a
# suppression marker, so the exemption costs a sentence a reader can disagree with.
_CONCURRENCY_WAIVER = "No `concurrency` group on purpose"

# The ecosystems `.github/dependabot.yml` must cover, and what goes stale without each. A
# SHA pin with nothing updating it is the failure mode this file's first rule creates.
_REQUIRED_ECOSYSTEMS = {
    "github-actions": "the SHA pins rule 1 requires would freeze forever",
    "uv": "uv.lock, which is what `deps` audits for CVEs",
    "docker": "the Dockerfile's base image",
    "docker-compose": "the postgres and caddy digest pins, which went two months unrefreshed",
}


def _workflows() -> list[Path]:
    return sorted(_WORKFLOW_DIR.glob("*.yml")) + sorted(_WORKFLOW_DIR.glob("*.yaml"))


def _jobs(text: str) -> dict[str, list[str]]:
    """Each job's name mapped to the lines of its block, `jobs:` onwards only.

    Bounded by indentation: a job is a two-space key under `jobs:`, and its block runs to the
    next two-space key or the end of the file. That is enough structure for "does this job
    declare a timeout", and it cannot be satisfied by a job-shaped string inside a `run:`
    script, which is indented far deeper.
    """
    lines = text.splitlines()
    try:
        start = lines.index("jobs:")
    except ValueError:
        return {}
    jobs: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[start + 1 :]:
        match = _JOB.match(line)
        if match:
            current = match.group("name")
            jobs[current] = []
            continue
        if line and not line.startswith(" ") and not line.startswith("#"):
            break  # a new top-level key: `jobs:` is over
        if current is not None:
            jobs[current].append(line)
    return jobs


def _third_party_uses(text: str) -> list[tuple[str, str]]:
    """(reference, trailing text) for every `uses:` naming something outside this repository.

    A local composite action (`uses: ./.github/actions/...`) is exempt: it has no SHA to pin
    because it IS this checkout, and the pull request that changes it is the review. There
    are none today, and the exception is what keeps adding one from failing for the wrong
    reason.

    Everything else is returned, container actions included. `docker://` used to be skipped
    beside the local-path case, which was wrong in the way this whole file is about: a
    `uses: docker://vendor/action:latest` is a MUTABLE third-party image executing in a job
    that holds a checkout and a database, and it would have passed a guard whose docstring
    claimed every third-party action was covered. The rule for it lives in the test, because
    an image pins a registry digest rather than a git commit.
    """
    found = []
    for line in text.splitlines():
        match = _USES.match(line)
        if not match:
            continue
        reference = match.group("reference")
        if reference.startswith("."):
            continue
        found.append((reference, match.group("rest").strip()))
    return found


def _cancels_superseded_runs(value: str) -> bool:
    """Whether a `cancel-in-progress:` value actually drops a superseded pull-request run.

    Checking that the KEY is present is not the same question, and the difference is the
    whole point of the setting: `cancel-in-progress: false` gives a concurrency group that
    QUEUES superseded runs instead of dropping them, which is slower than having no group at
    all, while satisfying a key-only check.

    A GitHub expression cannot be evaluated here, so the rule is that it must NAME the event
    it keys on. That accepts the `${{ github.event_name == 'pull_request' }}` form this
    repository uses, accepts a plain `true`, and rejects the three shapes that silently
    disarm the group: `false`, an empty value, and `${{ false }}`.
    """
    value = value.strip().strip('"').strip("'").strip()
    if not value:
        return False
    if value.lower() in {"true", "yes", "on"}:
        return True
    expression = re.fullmatch(r"\$\{\{(?P<body>.*)\}\}", value, re.S)
    if not expression:
        return False
    body = expression.group("body").strip().lower()
    if body in {"true", "1"}:
        return True
    if body in {"false", "0", "!true"}:
        return False
    return "pull_request" in body


def test_there_are_workflows_to_check() -> None:
    """Denominator. Every parametrised test below is generated from this list, so an empty
    or moved directory would make the whole file pass by collecting nothing."""
    found = _workflows()
    assert len(found) >= 3, (
        f"{len(found)} workflow(s) under {_WORKFLOW_DIR}; this repository has ci.yml, "
        "monitor.yml and measure-transcode.yml, so a smaller number means the glob is wrong "
        "or a workflow was deleted"
    )
    assert any(_third_party_uses(p.read_text(encoding="utf-8")) for p in found), (
        "no workflow uses a third-party action at all, so the pinning rule below would pass "
        "against nothing"
    )


@pytest.mark.parametrize("workflow", _workflows(), ids=lambda p: p.name)
def test_every_third_party_action_is_pinned_to_an_immutable_reference(workflow: Path) -> None:
    for reference, rest in _third_party_uses(workflow.read_text(encoding="utf-8")):
        name, at, ref = reference.rpartition("@")
        if reference.startswith("docker://"):
            # A container action names an image, so its immutable form is a registry digest.
            # No version comment is required of it: a digest has no release tag for
            # Dependabot to rewrite, and demanding one would push people back to a tag.
            assert at and _IMAGE_DIGEST.match(ref), (
                f"{workflow.name} uses `{reference}`, a third-party container image pinned by "
                "tag or by nothing at all. A tag is repointed by whoever owns the registry "
                "namespace, and this image would execute in a job holding a checkout and a "
                "database. Pin it as `docker://<image>@sha256:<64 hex>`."
            )
            continue
        assert at and _SHA.match(ref), (
            f"{workflow.name} uses `{reference}`. A tag is a mutable pointer the action's "
            "owner can move, which is the whole of the tj-actions supply-chain attack, and "
            "this workflow runs `uv sync` and `docker build` on a public repository. Pin the "
            "full commit SHA and put the release tag in a trailing comment."
        )
        assert _VERSION_COMMENT.match(rest), (
            f"{workflow.name} pins `{name}` to a SHA with no `# vX.Y.Z` comment "
            f"(found {rest!r}). Dependabot's github-actions ecosystem rewrites the SHA and "
            "that comment together; without it the pin is frozen at whatever was current the "
            "day it was written, and a human reading the line cannot tell which version it is."
        )


@pytest.mark.parametrize("workflow", _workflows(), ids=lambda p: p.name)
def test_every_job_bounds_its_own_runtime(workflow: Path) -> None:
    jobs = _jobs(workflow.read_text(encoding="utf-8"))
    assert jobs, f"{workflow.name} parsed to no jobs; the block reader looks in the wrong place"
    for name, block in jobs.items():
        keys = {match.group("key") for line in block if (match := _JOB_KEY.match(line))}
        assert "timeout-minutes" in keys, (
            f"job `{name}` in {workflow.name} has no `timeout-minutes`. GitHub's default is "
            "SIX HOURS, so a job that hangs on a health loop, a browser `wait_for` or a "
            "stalled TLS handshake holds a runner for a working day and says nothing."
        )


@pytest.mark.parametrize("workflow", _workflows(), ids=lambda p: p.name)
def test_every_workflow_declares_its_token_permissions(workflow: Path) -> None:
    text = workflow.read_text(encoding="utf-8")
    assert re.search(r"^permissions:\s*$", text, re.M), (
        f"{workflow.name} declares no top-level `permissions:`, so its GITHUB_TOKEN scope is "
        "whatever the repository default happens to be — a setting in a web UI rather than a "
        "fact in the tree, and one nobody reviews when it changes."
    )


@pytest.mark.parametrize("workflow", _workflows(), ids=lambda p: p.name)
def test_a_pull_request_workflow_cancels_superseded_runs_or_says_why_not(
    workflow: Path,
) -> None:
    text = workflow.read_text(encoding="utf-8")
    if not re.search(r"^\s{2}pull_request:?\s*$", text, re.M):
        return  # not triggered by pull requests; nothing to supersede
    if _CONCURRENCY_WAIVER in text:
        return
    concurrency = _CONCURRENCY_BLOCK.search(text + "\n\x00")
    assert concurrency, (
        f"{workflow.name} runs on pull requests with no `concurrency:` group, so every push "
        "to a branch leaves its predecessor running: minutes spent answering about a commit "
        f"nobody is merging. Add the group, or record why not with the words "
        f"{_CONCURRENCY_WAIVER!r}."
    )
    cancel = _CANCEL_IN_PROGRESS.search(concurrency.group("body"))
    assert cancel, (
        f"{workflow.name} has a concurrency group with no `cancel-in-progress:` key, which "
        "QUEUES superseded runs instead of dropping them — slower than no group at all. Set "
        f"it, or record why not with the words {_CONCURRENCY_WAIVER!r}."
    )
    assert _cancels_superseded_runs(cancel.group("value")), (
        f"{workflow.name} sets `cancel-in-progress: {cancel.group('value')}`, which does not "
        "cancel a superseded pull-request run. The key being present is not the question: "
        "`false` (and `${{ false }}`) leaves the group QUEUING superseded runs, which is "
        "slower than no group at all while satisfying anything that only looks for the key. "
        f"Use `true`, or an expression naming `pull_request`, or record why not with the "
        f"words {_CONCURRENCY_WAIVER!r}."
    )


def test_dependabot_covers_every_ecosystem_the_pins_depend_on() -> None:
    """Rule 1 creates a maintenance problem; this is the half that answers it.

    A repository full of SHA pins and no `github-actions` ecosystem is worse than tags: the
    versions stop moving and nobody can see that they have. The same holds one layer out --
    `uv.lock` is what the required `deps` job audits, and the compose digests went two months
    without a refresh because advancing one was somebody remembering to.
    """
    assert _DEPENDABOT.is_file(), (
        "no .github/dependabot.yml. Security updates run from a repository setting, but "
        "version updates need this file, and without it nothing opens a pull request for a "
        "stale action pin or a stale base-image digest."
    )
    config = _DEPENDABOT.read_text(encoding="utf-8")
    declared = set(re.findall(r'^\s*-?\s*package-ecosystem:\s*"([^"]+)"', config, re.M))
    for ecosystem, what_goes_stale in _REQUIRED_ECOSYSTEMS.items():
        assert ecosystem in declared, (
            f"dependabot.yml declares no `{ecosystem}` ecosystem, so {what_goes_stale}. "
            f"Declared: {sorted(declared)}"
        )


def test_the_pinning_rule_rejects_what_it_is_supposed_to_reject() -> None:
    """Non-vacuity. Each of these was the state of this repository before 2026-09-19, or is
    the shape somebody reaches for when a pin gets in the way."""
    assert not _SHA.match("v4"), "a bare major tag must not read as a pin"
    assert not _SHA.match("v7.0.1"), "a full version tag is still a tag"
    assert not _SHA.match("3d3c42e5aac5ba805825da76410c181273ba90b"), "39 hex is not a SHA"
    assert _SHA.match("3d3c42e5aac5ba805825da76410c181273ba90b1")

    assert not _VERSION_COMMENT.match(""), "a SHA with no comment must be rejected"
    assert not _VERSION_COMMENT.match("# pinned"), "a comment naming no version is not one"
    assert _VERSION_COMMENT.match("# v10.1.0")

    found = _third_party_uses("      - uses: actions/checkout@v4\n      - uses: ./.github/x\n")
    assert found == [("actions/checkout@v4", "")], (
        "the `uses:` reader must find a third-party action WHOLE (the `@ref` included, so a "
        "reference carrying none can still be judged) and skip a local one; "
        f"it returned {found}"
    )


def test_a_container_action_must_be_an_immutable_digest() -> None:
    """Non-vacuity for the `docker://` rule, which is the one with no example in the tree.

    A guard written for a case the repository does not contain yet is a guard nobody has
    watched fire, so the rejection is exercised against the real assertion rather than
    against the regex alone.
    """
    seen = _third_party_uses("      - uses: docker://vendor/action:latest\n")
    assert seen == [("docker://vendor/action:latest", "")], (
        "a container action must REACH the rule rather than be skipped beside the local-path "
        f"exception, which is how it passed before; the reader returned {seen}"
    )

    digest = "sha256:" + "ab" * 32
    assert _IMAGE_DIGEST.match(digest)
    assert not _IMAGE_DIGEST.match("latest"), "a tag is not a digest"
    assert not _IMAGE_DIGEST.match("sha256:" + "ab" * 31), "63 hex is not a digest"
    assert not _IMAGE_DIGEST.match("sha1:" + "ab" * 32), "only sha256 digests are immutable here"

    def check(line: str) -> None:
        """The rule above, over one `uses:` line. Kept in step with it by the real-file test
        next to it: if the two ever disagree, the workflows are what the repository runs."""
        for reference, rest in _third_party_uses(line):
            _, at, ref = reference.rpartition("@")
            if reference.startswith("docker://"):
                assert at and _IMAGE_DIGEST.match(ref), reference
                continue
            assert at and _SHA.match(ref), reference
            assert _VERSION_COMMENT.match(rest), reference

    check(f"      - uses: docker://vendor/action@{digest}\n")
    for rejected in (
        "      - uses: docker://vendor/action:latest\n",
        "      - uses: docker://vendor/action\n",
        f"      - uses: docker://vendor/action@sha256:{'ab' * 31}\n",
        "      - uses: actions/checkout\n",  # no ref at all: the most mutable form there is
    ):
        with pytest.raises(AssertionError):
            check(rejected)


def test_the_cancel_in_progress_rule_reads_the_value_not_the_key() -> None:
    """Non-vacuity. A key-only check passes `cancel-in-progress: false`, which leaves the
    group queueing superseded runs -- the setting doing the opposite of what it is there
    for, behind a guard reporting green."""
    for accepted in (
        "true",
        "${{ github.event_name == 'pull_request' }}",
        "${{ true }}",
    ):
        assert _cancels_superseded_runs(accepted), f"{accepted!r} does cancel and was rejected"
    for rejected in ("false", "", "   ", "${{ false }}", "${{ github.ref == 'refs/heads/main' }}"):
        assert not _cancels_superseded_runs(rejected), (
            f"{rejected!r} does not cancel a superseded pull-request run and was accepted"
        )

    body = "  group: x\n  cancel-in-progress: false\n"
    found = _CANCEL_IN_PROGRESS.search(body)
    assert found and found.group("value") == "false", (
        "the value reader must return what the key is set TO; it returned "
        f"{found.group('value') if found else None!r}"
    )


def test_the_job_and_timeout_readers_reject_a_job_without_one() -> None:
    """Non-vacuity for the block reader, which is the part most able to go quiet: a parser
    that found no jobs would make the timeout rule vacuous on every file at once."""
    sample = "\n".join(
        (
            "name: x",
            "",
            "jobs:",
            "  bounded:",
            "    runs-on: ubuntu-latest",
            "    timeout-minutes: 5",
            "    steps:",
            "      - run: echo hi",
            "  unbounded:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - run: |",
            "          # timeout-minutes: 5",
            "          echo hi",
        )
    )
    jobs = _jobs(sample)
    assert sorted(jobs) == ["bounded", "unbounded"], f"the block reader found {sorted(jobs)}"

    def keys(job: str) -> set[str]:
        return {m.group("key") for line in jobs[job] if (m := _JOB_KEY.match(line))}

    assert "timeout-minutes" in keys("bounded")
    assert "timeout-minutes" not in keys("unbounded"), (
        "a `timeout-minutes` written inside a `run:` script is not a job key, and reading it "
        "as one would let the rule be satisfied by a comment"
    )
