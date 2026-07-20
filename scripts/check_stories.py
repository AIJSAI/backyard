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
VALID_STATUS = {"spec", "built", "tested", "passing"}
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
    for epic in epics:
        eid = str(epic.get("id", "?"))
        if not epic.get("title"):
            errors.append(f"{eid}: missing title")
        for story in epic.get("stories") or []:
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
            if status == "passing" and not story.get("evidence"):
                errors.append(f"{sid}: status is passing but no evidence")
            acceptance = story.get("acceptance")
            if not isinstance(acceptance, list) or not acceptance:
                errors.append(f"{sid}: acceptance must be a non-empty list")
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
                }
            ],
        }
    ]
}
BAD_CHECKLIST = "- [x] shipped something without a receipt\n"


def selftest() -> list[str]:
    errors: list[str] = []
    if not validate_stories(BAD_STORIES):
        errors.append("selftest: story guard accepted a known-bad fixture (vacuous gate)")
    if not validate_checklist(BAD_CHECKLIST, name="fixture"):
        errors.append("selftest: checklist guard accepted a known-bad fixture (vacuous gate)")
    return errors


def main() -> int:
    errors = selftest()
    stories_path = ROOT / "stories" / "stories.yaml"
    checklist_path = ROOT / "docs" / "PATH-TO-100.md"
    errors += validate_stories(yaml.safe_load(stories_path.read_text()))
    errors += validate_checklist(checklist_path.read_text())
    for err in errors:
        print(f"GATE FAIL: {err}")
    print(f"gates: {'FAIL' if errors else 'PASS'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
