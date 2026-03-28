from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reject wheel/package tree drift by checking for both unexpected and missing entries."
        )
    )
    parser.add_argument("wheels", nargs="+", type=Path, help="Wheel files to inspect")
    parser.add_argument(
        "--package-root",
        type=Path,
        default=Path("src/ethernity"),
        help="Source package root used as the allowlist baseline",
    )
    return parser.parse_args()


def expected_source_entries(package_root: Path) -> set[str]:
    return {
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and not any(part.startswith(".") for part in path.relative_to(package_root).parts)
        and path.suffix not in {".pyc", ".pyo"}
    }


def wheel_package_entries(wheel_path: Path) -> set[str]:
    entries: set[str] = set()
    with zipfile.ZipFile(wheel_path) as archive:
        for name in archive.namelist():
            if not name.startswith("ethernity/") or name.endswith("/"):
                continue
            entries.add(name.removeprefix("ethernity/"))
    return entries


def main() -> int:
    args = parse_args()
    expected_entries = expected_source_entries(args.package_root)
    failures = False

    for wheel_path in args.wheels:
        wheel_entries = wheel_package_entries(wheel_path)
        unexpected = sorted(wheel_entries - expected_entries)
        missing = sorted(expected_entries - wheel_entries)
        if not unexpected and not missing:
            print(f"{wheel_path}: ok")
            continue
        failures = True
        print(f"{wheel_path}: wheel/package tree drift detected", file=sys.stderr)
        for entry in unexpected:
            print(f"  - unexpected: ethernity/{entry}", file=sys.stderr)
        for entry in missing:
            print(f"  - missing: ethernity/{entry}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
