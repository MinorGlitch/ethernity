from __future__ import annotations

import argparse
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reject wheel/package tree drift by checking for both unexpected and missing entries."
        )
    )
    parser.add_argument("packages", nargs="+", type=Path, help="Wheel/sdist files to inspect")
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


def sdist_package_entries(sdist_path: Path) -> set[str]:
    entries: set[str] = set()
    with tarfile.open(sdist_path, "r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            parts = PurePosixPath(member.name).parts
            for index in range(len(parts) - 1):
                if parts[index : index + 2] != ("src", "ethernity"):
                    continue
                relative_parts = parts[index + 2 :]
                if relative_parts:
                    entries.add(PurePosixPath(*relative_parts).as_posix())
                break
    return entries


def package_entries(package_path: Path) -> set[str]:
    if package_path.suffix == ".whl":
        return wheel_package_entries(package_path)
    if package_path.name.endswith(".tar.gz"):
        return sdist_package_entries(package_path)
    raise ValueError(f"unsupported package type: {package_path}")


def main() -> int:
    args = parse_args()
    expected_entries = expected_source_entries(args.package_root)
    failures = False

    for package_path in args.packages:
        actual_entries = package_entries(package_path)
        unexpected = sorted(actual_entries - expected_entries)
        missing = sorted(expected_entries - actual_entries)
        if not unexpected and not missing:
            print(f"{package_path}: ok")
            continue
        failures = True
        print(f"{package_path}: package tree drift detected", file=sys.stderr)
        for entry in unexpected:
            print(f"  - unexpected: ethernity/{entry}", file=sys.stderr)
        for entry in missing:
            print(f"  - missing: ethernity/{entry}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
