from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reject wheel entries that do not exist in the current src package tree."
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
    }


def unexpected_wheel_entries(wheel_path: Path, expected_entries: set[str]) -> list[str]:
    unexpected: list[str] = []
    with zipfile.ZipFile(wheel_path) as archive:
        for name in archive.namelist():
            if not name.startswith("ethernity/") or name.endswith("/"):
                continue
            relative_name = name.removeprefix("ethernity/")
            if relative_name not in expected_entries:
                unexpected.append(name)
    return unexpected


def main() -> int:
    args = parse_args()
    expected_entries = expected_source_entries(args.package_root)
    failures = False

    for wheel_path in args.wheels:
        unexpected = unexpected_wheel_entries(wheel_path, expected_entries)
        if not unexpected:
            print(f"{wheel_path}: ok")
            continue
        failures = True
        print(f"{wheel_path}: unexpected wheel entries detected", file=sys.stderr)
        for entry in unexpected:
            print(f"  - {entry}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
