"""Summarize pytest JUnit timings without running tests again."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

_GROUPS = (
    ("tests.ui.components.", "UI components"),
    ("tests.ui.workflows.", "UI workflows"),
    ("tests.rendering.", "PDF rendering"),
    ("tests.integration.", "Integration"),
    ("tests.visual.", "Terminal visuals"),
    ("tests.e2e.", "End-to-end and compatibility"),
    ("tests.unit.", "Core unit tests"),
)


def summarize(paths: list[Path]) -> str:
    groups: dict[str, list[float]] = defaultdict(list)
    tests: list[tuple[float, str]] = []
    skipped = 0
    failed = 0
    for path in paths:
        for case in ET.parse(path).iter("testcase"):
            classname = case.get("classname", "")
            group = next(
                (name for prefix, name in _GROUPS if classname.startswith(prefix)), "Other"
            )
            seconds = float(case.get("time", "0"))
            groups[group].append(seconds)
            tests.append((seconds, f"{classname}.{case.get('name', '')}"))
            skipped += case.find("skipped") is not None
            failed += case.find("failure") is not None or case.find("error") is not None

    if not tests:
        return "No test timings were produced.\n"
    total = sum(seconds for seconds, _ in tests)
    lines = [
        "## Test timings",
        "",
        f"{len(tests)} cases, {failed} failures/errors, {skipped} skipped.",
        "Times include setup, execution and teardown. They are summed across workers,",
        "so they can exceed the job's elapsed time.",
        "",
        "| Area | Cases | Test seconds | Share |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, durations in sorted(groups.items(), key=lambda item: -sum(item[1])):
        seconds = sum(durations)
        share = seconds / total * 100 if total else 0
        lines.append(f"| {name} | {len(durations)} | {seconds:.1f} | {share:.1f}% |")
    lines.extend(("", "### Slowest cases", "", "| Test | Seconds |", "| --- | ---: |"))
    for seconds, name in sorted(tests, reverse=True)[:15]:
        name = name.replace("|", "&#124;").replace("\n", " ").replace("`", "'")
        lines.append(f"| `{name}` | {seconds:.2f} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Directory containing JUnit XML files")
    args = parser.parse_args()
    print(summarize(sorted(args.directory.glob("*.xml"))), end="")


if __name__ == "__main__":
    main()
