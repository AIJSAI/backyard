#!/usr/bin/env python3
"""Backyard CI gates: story tracker and checklist evidence guards.

Gates:
  1. stories/stories.yaml parses and every story is well-formed.
  2. Status "passing" requires a non-empty evidence field.
  3. docs/PATH-TO-100.md: every checked box carries an evidence link.
  4. Self-test: both guards must FAIL on known-bad fixtures, proving the
     gate is non-vacuous before it is trusted on real data.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
# "superseded" is a DECISION, not a stall: a story the founder has ruled out, or one
# that turned out to be already covered by shipped behaviour. It exists so a dropped
# story is recorded rather than deleted (the same rule PATH-TO-100 applies to its own
# items) and so it stops reading as pending work forever. It carries the same evidence
# burden as "passing": a claim that something need not be built has to say why.
VALID_STATUS = {"spec", "built", "tested", "passing", "superseded"}
NEEDS_EVIDENCE = {"passing", "superseded"}
REQUIRED_FIELDS = {"id", "epic", "persona", "story", "acceptance", "status"}
CHECKED_LINE = re.compile(r"^\s*-\s*\[[xX]\]\s")


def validate_stories(data: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["stories.yaml: top level must be a mapping"]
    epics = data.get("epics")
    if not isinstance(epics, list) or not epics:
        return ["stories.yaml: epics missing or empty"]
    seen_ids: set[str] = set()
    for index, epic in enumerate(epics):
        # Shape-check before reading. Review flagged the ID reader for crashing on malformed
        # input; measured, THIS function crashed too — `AttributeError` on a non-mapping epic
        # and on a non-list `stories`. Fixing only the function that was named would have
        # left the traceback exactly where it was, from one frame further down.
        if not isinstance(epic, dict):
            errors.append(f"epics[{index}]: must be a mapping, got {type(epic).__name__}")
            continue
        eid = str(epic.get("id", "?"))
        if not epic.get("title"):
            errors.append(f"{eid}: missing title")
        stories = epic.get("stories") or []
        if not isinstance(stories, list):
            errors.append(f"{eid}: stories must be a list, got {type(stories).__name__}")
            continue
        for story in stories:
            if not isinstance(story, dict):
                errors.append(f"{eid}: a story entry is {type(story).__name__}, not a mapping")
                continue
            sid = str(story.get("id", "?"))
            missing = REQUIRED_FIELDS - story.keys()
            if missing:
                errors.append(f"{sid}: missing fields {sorted(missing)}")
            if sid in seen_ids:
                errors.append(f"{sid}: duplicate story id")
            seen_ids.add(sid)
            status = story.get("status")
            if status not in VALID_STATUS:
                errors.append(f"{sid}: invalid status {status!r}")
            if status in NEEDS_EVIDENCE and not story.get("evidence"):
                errors.append(f"{sid}: status is {status} but no evidence")
            acceptance = story.get("acceptance")
            if not isinstance(acceptance, list) or not acceptance:
                errors.append(f"{sid}: acceptance must be a non-empty list")
            # The `epic:` field must match the epic the story is NESTED UNDER. Seven stories
            # were appended to the end of this file declaring `epic: E7` while landing inside
            # E8's list, and every check here passed: nothing compared the two. The epics are
            # not in numeric order either (E1..E7, then E9, then E8), so "insert before E8"
            # is not the same as "at the end of E7" — which is how the first correction put
            # them in E9.
            declared = story.get("epic")
            if declared != eid:
                errors.append(
                    f"{sid}: declares epic {declared!r} but is nested under {eid!r}. "
                    "Anything that renders by epic section will file it under the wrong "
                    "heading, and the tally that counts stories per epic will disagree "
                    "with the document that reads them."
                )
    return errors


def validate_checklist(text: str, name: str = "PATH-TO-100.md") -> list[str]:
    errors: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if CHECKED_LINE.match(line) and "evidence:" not in line:
            errors.append(f"{name}:{lineno}: checked box without an evidence link")
    return errors


# Known-bad fixtures: the guards must reject BOTH, or the gate itself fails.
BAD_STORIES: dict = {
    "epics": [
        {
            "id": "EX",
            "title": "fixture",
            "stories": [
                {
                    "id": "S-BAD",
                    "epic": "EX",
                    "persona": "fixture",
                    "story": "passing with no evidence must fail",
                    "acceptance": ["x"],
                    "status": "passing",
                },
                {
                    "id": "S-BAD-2",
                    "epic": "EX",
                    "persona": "fixture",
                    "story": "superseded with no evidence must fail too",
                    "acceptance": ["x"],
                    "status": "superseded",
                },
            ],
        }
    ]
}
BAD_CHECKLIST = "- [x] shipped something without a receipt\n"


def selftest() -> list[str]:
    errors: list[str] = []
    found = validate_stories(BAD_STORIES)
    if not found:
        errors.append("selftest: story guard accepted a known-bad fixture (vacuous gate)")
    # Both evidence-bearing statuses must be caught, not just the first. Widening
    # VALID_STATUS without widening the fixture is how a gate quietly stops enforcing.
    for bad_id in ("S-BAD", "S-BAD-2"):
        if not any(e.startswith(bad_id + ":") for e in found):
            errors.append(f"selftest: {bad_id} passed the story guard (evidence rule not enforced)")
    if not validate_checklist(BAD_CHECKLIST, name="fixture"):
        errors.append("selftest: checklist guard accepted a known-bad fixture (vacuous gate)")
    return errors


def filed_story_ids(data: object) -> set[str]:
    """Every story id in the file, walked the same way `validate_stories` walks it.

    Deliberately not a second traversal: two readers of one structure drift, and the one
    that drifts silently here would make the cross-reference check below blind rather than
    wrong — which is worse, because it keeps passing.
    """
    if not isinstance(data, dict):
        return set()
    epics = data.get("epics")
    if not isinstance(epics, list):
        # `validate_stories` has already reported this. Crashing here would replace its
        # actionable message with a traceback from a helper — the gate would fail for the
        # right reason and say the wrong thing.
        return set()
    found: set[str] = set()
    for epic in epics:
        if not isinstance(epic, dict):
            continue
        stories = epic.get("stories")
        if not isinstance(stories, list):
            continue
        for story in stories:
            if isinstance(story, dict) and story.get("id"):
                found.add(str(story["id"]))
    return found


def cited_but_unfiled(story_ids: set[str]) -> list[str]:
    """Story IDs a document commits to that `stories.yaml` has never heard of.

    S-721 is why this exists. A retro named it as a Definition-of-Done item, an audit quoted
    that retro, and `PATH-TO-100.md` marked the phase complete on a story tally — while
    `grep -n 'S-721' stories/stories.yaml` returned nothing. The story had never been
    created, so the tally counted a set that did not include it and the phase closed on the
    strength of a document referring to a thing that did not exist.

    Scoped to the documents that make COMMITMENTS. Receipts and audits are dated records:
    an audit is allowed — required, really — to say "S-721 does not exist", and a guard that
    failed on that sentence would push toward deleting the finding.
    """
    committing = [
        ROOT / "docs" / "PATH-TO-100.md",
        ROOT / "docs" / "OUTSTANDING.md",
        ROOT / "docs" / "README.md",
        ROOT / "README.md",
    ]
    errors: list[str] = []
    for path in committing:
        if not path.is_file():
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for cited in set(re.findall(r"\bS-\d{3}\b", line)):
                if cited not in story_ids:
                    errors.append(
                        f"{path.relative_to(ROOT)}:{lineno}: cites {cited}, which is not in "
                        "stories/stories.yaml. Either file the story or stop referring to it "
                        "— a document that names a story nobody wrote is how a phase gets "
                        "marked complete on a tally that never counted it."
                    )
    return errors


def main() -> int:
    errors = selftest()
    stories_path = ROOT / "stories" / "stories.yaml"
    checklist_path = ROOT / "docs" / "PATH-TO-100.md"
    stories = yaml.safe_load(stories_path.read_text())
    errors += validate_stories(stories)
    errors += validate_checklist(checklist_path.read_text())
    filed = filed_story_ids(stories)
    if not filed:
        errors.append("no story IDs parsed from stories.yaml; the cross-reference check is blind")
    else:
        errors += cited_but_unfiled(filed)
    for err in errors:
        print(f"GATE FAIL: {err}")
    print(f"gates: {'FAIL' if errors else 'PASS'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
