"""Select CI jobs, allowing lightweight checks for documentation and README media."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

from tooling.release.github import output

HOMEBREW_INPUTS = (".github/", "tooling/release", "scripts/", "src/ethernity/resources/")
PACKAGE_FILES = {"pyproject.toml", "uv.lock", "MANIFEST.in", "ethernity.spec"}
README_MEDIA = {
    "images/ethernity-animated.gif",
    "images/ethernity-animated.png",
    "images/readme_logo.png",
    "images/banner.png",
}
MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".apng"}
FULL_JOBS = {
    "python-checks",
    "kit-lint",
    "render-visual",
    "portability",
    "test",
    "coverage",
    "e2e",
    "kit-bundles",
    "package",
    "native-packages",
    "homebrew-rehearsal",
    "kit-verify",
    "python-audit",
    "npm-audit",
}


def documentation_only(path: str) -> bool:
    # test_passphrases.py validates the recovery phrase example in this document.
    if path == "docs/format_rationale.md":
        return False
    file = PurePosixPath(path)
    if file.suffix == ".md":
        return (
            file.parent == PurePosixPath(".")
            or path.startswith("docs/")
            or path in {"images/ICONS.md", "tooling/demos/README.md"}
        )
    return path in README_MEDIA or (
        path.startswith("images/readme/") and file.suffix in MEDIA_EXTENSIONS
    )


def changed_paths(event: str, base: str) -> list[str] | None:
    """Compare the checked-out merge/push with its base; unknown changes require full CI."""
    if event not in {"pull_request", "push"} or not base or set(base) == {"0"}:
        return None
    try:
        changed = subprocess.check_output(
            ["git", "diff", "--name-only", "--no-renames", "-z", base, "HEAD", "--"],
            text=True,
        )
    except subprocess.CalledProcessError:
        print("Could not compare changes; running full CI.", file=sys.stderr)
        return None
    # Disabling rename detection includes both paths, including code renamed into docs/.
    return [path for path in changed.split("\0") if path]


def packaging_changes(paths: list[str]) -> tuple[bool, bool]:
    native = any(not documentation_only(path) for path in paths)
    homebrew = any(path in PACKAGE_FILES or path.startswith(HOMEBREW_INPUTS) for path in paths)
    return native, homebrew


def selection(paths: list[str] | None, *, event: str = "pull_request") -> dict[str, str]:
    if not paths:
        full, native, homebrew = True, True, True
    else:
        native, homebrew = packaging_changes(paths)
        full = native
        # Master pushes retain both packaging rehearsals for non-documentation changes.
        homebrew = homebrew or (full and event == "push")
    return {
        "full": json.dumps(full),
        "native": json.dumps(native),
        "homebrew": json.dumps(homebrew),
    }


def failures(needs: dict[str, Any]) -> list[str]:
    plan = needs.get("plan", {})
    flags = plan.get("outputs", {})
    valid = plan.get("result") == "success" and all(
        flags.get(flag) in {"true", "false"} for flag in ("full", "native", "homebrew")
    )
    allowed_skips: set[str] = set()
    if valid and flags["full"] == "false":
        valid = flags["native"] == flags["homebrew"] == "false"
        if valid:
            allowed_skips = FULL_JOBS
    elif valid:
        allowed_skips = {"documentation-checks"}
        for job, flag in (("native-packages", "native"), ("homebrew-rehearsal", "homebrew")):
            if flags[flag] == "false":
                allowed_skips.add(job)
    failed = {
        name
        for name, job in needs.items()
        if job.get("result") != "success"
        and not (name in allowed_skips and job.get("result") == "skipped")
    }
    failed.update((FULL_JOBS | {"plan", "documentation-checks"}) - needs.keys())
    if not valid:
        failed.add("plan")
    return sorted(failed)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "gate":
        failed = failures(json.loads(os.environ["NEEDS_CONTEXT"]))
        if failed:
            raise SystemExit(f"Required CI jobs did not succeed: {', '.join(failed)}")
        print("All required CI jobs succeeded.")
        return
    event = os.environ["GITHUB_EVENT_NAME"]
    paths = changed_paths(event, os.environ.get("BASE_SHA", ""))
    flags = selection(paths, event=event)
    version = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    output(tag=f"v{version}", **flags)
    print("Full CI selected." if flags["full"] == "true" else "Documentation-only checks selected.")


if __name__ == "__main__":
    main()
