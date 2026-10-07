from __future__ import annotations

import argparse
import sys
import tarfile
import tomllib
import zipfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KIT_RESOURCE_PATH = "resources/kit"
MIN_BUNDLE_BYTES = 1000


def package_data_patterns() -> tuple[str, ...]:
    """Read the release resource inventory from the package metadata."""

    with (PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
        metadata = tomllib.load(handle)
    return tuple(metadata["tool"]["setuptools"]["package-data"]["ethernity"])


PACKAGE_DATA_PATTERNS = package_data_patterns()
REQUIRED_KIT_ENTRIES = frozenset(
    entry
    for entry in PACKAGE_DATA_PATTERNS
    if PurePosixPath(entry).parent == PurePosixPath(KIT_RESOURCE_PATH) and entry.endswith(".html")
)
if not REQUIRED_KIT_ENTRIES:
    raise ValueError("package metadata must list the release recovery-kit bundles")
REQUIRED_KIT_NAMES = frozenset(PurePosixPath(entry).name for entry in REQUIRED_KIT_ENTRIES)


def kit_bundle_issues(sizes: Mapping[str, int]) -> tuple[str, ...]:
    """Apply the same inventory and size checks to folders and archives."""

    issues = [f"missing kit bundle: {name}" for name in sorted(REQUIRED_KIT_NAMES - sizes.keys())]
    issues.extend(
        f"unexpected kit bundle: {name}" for name in sorted(sizes.keys() - REQUIRED_KIT_NAMES)
    )
    issues.extend(
        f"kit bundle too small: {name} ({sizes[name]} bytes; minimum {MIN_BUNDLE_BYTES})"
        for name in sorted(REQUIRED_KIT_NAMES & sizes.keys())
        if sizes[name] < MIN_BUNDLE_BYTES
    )
    return tuple(issues)


def require_kit_bundles(directory: Path) -> None:
    """Reject missing, extra, empty, or undersized generated bundles."""

    sizes = {
        path.name: path.stat().st_size if path.is_file() else 0 for path in directory.glob("*.html")
    }
    issues = kit_bundle_issues(sizes)
    if issues:
        raise ValueError(f"{directory}:\n" + "\n".join(f"  - {issue}" for issue in issues))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Verify generated recovery-kit bundles and wheel/sdist package contents.")
    )
    parser.add_argument("packages", nargs="*", type=Path, help="Wheel/sdist files to inspect")
    parser.add_argument("--kit-directory", type=Path, help="Generated bundle folder to inspect")
    parser.add_argument(
        "--package-root",
        type=Path,
        default=PROJECT_ROOT / "src" / "ethernity",
        help="Source package root used as the allowlist baseline",
    )
    args = parser.parse_args()
    if args.kit_directory is None and not args.packages:
        parser.error("provide --kit-directory or at least one package archive")
    return args


def expected_source_entries(package_root: Path) -> set[str]:
    python_entries = {
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and not any(part.startswith(".") for part in path.relative_to(package_root).parts)
        and path.suffix in {".py", ".pyi"}
    }
    resource_entries = {
        path.relative_to(package_root).as_posix()
        for pattern in PACKAGE_DATA_PATTERNS
        for path in package_root.glob(pattern)
        if path.is_file()
    }
    return python_entries | resource_entries | REQUIRED_KIT_ENTRIES


def _is_kit_html_entry(entry: str) -> bool:
    return PurePosixPath(entry).parent == PurePosixPath(KIT_RESOURCE_PATH) and entry.endswith(
        ".html"
    )


def wheel_package_sizes(wheel_path: Path) -> dict[str, int]:
    entries: dict[str, int] = {}
    with zipfile.ZipFile(wheel_path) as archive:
        for member in archive.infolist():
            name = member.filename
            if not name.startswith("ethernity/") or name.endswith("/"):
                continue
            entries[name.removeprefix("ethernity/")] = member.file_size
    return entries


def sdist_package_sizes(sdist_path: Path) -> dict[str, int]:
    entries: dict[str, int] = {}
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
                    entries[PurePosixPath(*relative_parts).as_posix()] = member.size
                break
    return entries


def package_sizes(package_path: Path) -> dict[str, int]:
    if package_path.suffix == ".whl":
        return wheel_package_sizes(package_path)
    if package_path.name.endswith(".tar.gz"):
        return sdist_package_sizes(package_path)
    raise ValueError(f"unsupported package type: {package_path}")


def _verify_package(package_path: Path, expected_entries: set[str]) -> bool:
    try:
        sizes = package_sizes(package_path)
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"{package_path}: {exc}", file=sys.stderr)
        return False
    actual_entries = sizes.keys()
    unexpected = sorted(
        entry for entry in actual_entries - expected_entries if not _is_kit_html_entry(entry)
    )
    missing = sorted(
        entry for entry in expected_entries - actual_entries if not _is_kit_html_entry(entry)
    )
    issues = [f"unexpected: ethernity/{entry}" for entry in unexpected]
    issues.extend(f"missing: ethernity/{entry}" for entry in missing)
    issues.extend(
        kit_bundle_issues(
            {
                PurePosixPath(entry).name: size
                for entry, size in sizes.items()
                if _is_kit_html_entry(entry)
            }
        )
    )
    if issues:
        print(f"{package_path}: package tree drift detected", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        return False
    print(f"{package_path}: ok")
    return True


def main() -> int:
    args = parse_args()
    failures = False
    if args.kit_directory is not None:
        try:
            require_kit_bundles(args.kit_directory)
        except (OSError, ValueError) as exc:
            failures = True
            print(exc, file=sys.stderr)
        else:
            print(f"{args.kit_directory}: ok")

    if args.packages:
        expected_entries = expected_source_entries(args.package_root)
        for package_path in args.packages:
            if not _verify_package(package_path, expected_entries):
                failures = True
    return int(failures)


if __name__ == "__main__":
    raise SystemExit(main())
