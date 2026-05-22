#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

"""Filesystem discovery helpers for extension directories and carrier filenames."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ethernity.extensions.layout import (
    ExtensionMainArtifactName,
    ExtensionShardArtifactName,
    canonical_extension_dir_name,
    is_canonical_extension_dir_name,
    is_staging_dir_name,
    parse_extension_dir_name,
    parse_extension_main_filename,
    parse_extension_shard_filename,
)

EXTENSIONS_DIR_NAME = "extensions"
_MAIN_FILENAME_PREFIXES = ("qr_document-", "recovery_document-", "recovery_kit_index-")
_SHARD_FILENAME_PREFIXES = ("shard-", "signing-key-shard-")
_RECOGNIZED_FILENAME_PREFIXES = (*_MAIN_FILENAME_PREFIXES, *_SHARD_FILENAME_PREFIXES)
_PAYLOAD_MAIN_DOC_TYPES = frozenset({"qr_document"})
_REQUIRED_MAIN_DOC_TYPES = frozenset({"qr_document", "recovery_document"})


@dataclass(frozen=True)
class DiscoveredExtensionMainCarrier:
    doc_type: str
    path: Path
    filename: str
    doc_id_hex: str


@dataclass(frozen=True)
class DiscoveredExtensionShardCarrier:
    doc_type: str
    path: Path
    filename: str
    doc_id_hex: str
    share_index: int
    share_count: int


@dataclass(frozen=True)
class DiscoveredExtensionDirectory:
    index: int
    dir_name: str
    path: Path
    doc_id_hex: str
    main_carriers: tuple[DiscoveredExtensionMainCarrier, ...]
    shard_carriers: tuple[DiscoveredExtensionShardCarrier, ...]
    recovery_kit_index_carrier: DiscoveredExtensionMainCarrier | None = None


@dataclass(frozen=True)
class ValidatedExtensionDiscovery:
    directories: tuple[DiscoveredExtensionDirectory, ...]
    first_invalid_dir_name: str | None = None
    first_invalid_message: str | None = None


def extension_root_dir(root_dir: str | Path) -> Path:
    """Return the canonical extensions directory path for a backup root."""

    return Path(root_dir).expanduser() / EXTENSIONS_DIR_NAME


def require_backup_root_dir(root_dir: str | Path) -> Path:
    """Return a validated backup root directory path."""

    path = Path(root_dir).expanduser()
    if path.is_symlink():
        raise ValueError("root backup directory must not be a symlink")
    if not path.exists():
        raise ValueError(f"root backup directory not found: {root_dir}")
    if not path.is_dir():
        raise ValueError(f"root backup directory must be a directory: {root_dir}")
    return path


def payload_main_carriers(
    carriers: tuple[DiscoveredExtensionMainCarrier, ...] | list[DiscoveredExtensionMainCarrier],
) -> tuple[DiscoveredExtensionMainCarrier, ...]:
    """Return only machine-readable payload-bearing extension documents."""

    return tuple(carrier for carrier in carriers if carrier.doc_type in _PAYLOAD_MAIN_DOC_TYPES)


def discover_extension_directories(
    root_dir: str | Path,
) -> tuple[DiscoveredExtensionDirectory, ...]:
    """Return the discovered canonical extension inventory for a backup root."""

    discovery = discover_validated_extension_directories(root_dir)
    if discovery.first_invalid_message is not None:
        raise ValueError(discovery.first_invalid_message)
    return discovery.directories


def discover_validated_extension_directories(
    root_dir: str | Path,
) -> ValidatedExtensionDiscovery:
    """Return the longest validated canonical extension prefix for a backup root."""

    extensions_dir = extension_root_dir(root_dir)
    if extensions_dir.is_symlink():
        return ValidatedExtensionDiscovery(
            directories=(),
            first_invalid_dir_name=extensions_dir.name,
            first_invalid_message="extensions path must not be a symlink",
        )
    if not extensions_dir.exists():
        return ValidatedExtensionDiscovery(directories=())
    if not extensions_dir.is_dir():
        return ValidatedExtensionDiscovery(
            directories=(),
            first_invalid_message="extensions path must be a directory",
        )

    candidate_dirs: dict[int, Path] = {}
    invalid_decimal_dirs: dict[int, str] = {}
    invalid_reserved_entries: dict[int, tuple[str, str]] = {}
    unexpected_extension_like_entries: set[str] = set()
    for entry in extensions_dir.iterdir():
        if entry.is_symlink():
            if (
                is_staging_dir_name(entry.name)
                or entry.name.isdecimal()
                or is_canonical_extension_dir_name(entry.name)
            ):
                if is_staging_dir_name(entry.name):
                    return ValidatedExtensionDiscovery(
                        directories=(),
                        first_invalid_dir_name=entry.name,
                        first_invalid_message=(
                            f"extension directory must not be a symlink: {entry.name}"
                        ),
                    )
                index = int(entry.name, 10)
                invalid_reserved_entries.setdefault(
                    index,
                    (
                        entry.name,
                        f"extension directory must not be a symlink: {entry.name}",
                    ),
                )
            elif _is_extension_like_top_level_entry(entry.name):
                unexpected_extension_like_entries.add(entry.name)
            continue
        if not entry.is_dir():
            if (
                is_staging_dir_name(entry.name)
                or entry.name.isdecimal()
                or is_canonical_extension_dir_name(entry.name)
            ):
                if is_staging_dir_name(entry.name):
                    return ValidatedExtensionDiscovery(
                        directories=(),
                        first_invalid_dir_name=entry.name,
                        first_invalid_message=(
                            f"extension directory must be a directory: {entry.name}"
                        ),
                    )
                if entry.name.isdecimal():
                    index = int(entry.name, 10)
                    if not is_canonical_extension_dir_name(entry.name):
                        invalid_decimal_dirs.setdefault(index, entry.name)
                        continue
                else:
                    index = parse_extension_dir_name(entry.name)
                invalid_reserved_entries.setdefault(
                    index,
                    (
                        entry.name,
                        f"extension directory must be a directory: {entry.name}",
                    ),
                )
            elif _is_extension_like_top_level_entry(entry.name):
                unexpected_extension_like_entries.add(entry.name)
            continue
        if is_staging_dir_name(entry.name):
            continue
        if entry.name.isdecimal():
            index = int(entry.name, 10)
            if not is_canonical_extension_dir_name(entry.name):
                invalid_decimal_dirs.setdefault(index, entry.name)
                continue
            candidate_dirs[index] = entry
            continue
        if not is_canonical_extension_dir_name(entry.name):
            if _is_extension_like_top_level_entry(entry.name):
                unexpected_extension_like_entries.add(entry.name)
            continue
        candidate_dirs[parse_extension_dir_name(entry.name)] = entry

    if invalid_decimal_dirs:
        first_invalid_index = min(invalid_decimal_dirs)
        if first_invalid_index <= 0:
            invalid_name = invalid_decimal_dirs[first_invalid_index]
            return ValidatedExtensionDiscovery(
                directories=(),
                first_invalid_dir_name=invalid_name,
                first_invalid_message=(
                    f"invalid non-canonical extension directory name: {invalid_name}"
                ),
            )

    all_indexes = sorted({*candidate_dirs, *invalid_decimal_dirs, *invalid_reserved_entries})
    validated: list[DiscoveredExtensionDirectory] = []
    expected_index = 1
    for discovered_index in all_indexes:
        invalid_name_for_expected = invalid_decimal_dirs.get(expected_index)
        if invalid_name_for_expected is not None:
            return ValidatedExtensionDiscovery(
                directories=tuple(validated),
                first_invalid_dir_name=invalid_name_for_expected,
                first_invalid_message=(
                    f"invalid non-canonical extension directory name: {invalid_name_for_expected}"
                ),
            )
        invalid_entry_for_expected = invalid_reserved_entries.get(expected_index)
        if invalid_entry_for_expected is not None:
            invalid_name, invalid_message = invalid_entry_for_expected
            return ValidatedExtensionDiscovery(
                directories=tuple(validated),
                first_invalid_dir_name=invalid_name,
                first_invalid_message=invalid_message,
            )
        if discovered_index != expected_index:
            invalid_name_for_discovered = invalid_decimal_dirs.get(discovered_index)
            if invalid_name_for_discovered is not None:
                return ValidatedExtensionDiscovery(
                    directories=tuple(validated),
                    first_invalid_dir_name=invalid_name_for_discovered,
                    first_invalid_message=(
                        "invalid non-canonical extension directory name: "
                        f"{invalid_name_for_discovered}"
                    ),
                )
            invalid_entry_for_discovered = invalid_reserved_entries.get(discovered_index)
            if invalid_entry_for_discovered is not None:
                invalid_name, invalid_message = invalid_entry_for_discovered
                return ValidatedExtensionDiscovery(
                    directories=tuple(validated),
                    first_invalid_dir_name=invalid_name,
                    first_invalid_message=invalid_message,
                )
            return ValidatedExtensionDiscovery(
                directories=tuple(validated),
                first_invalid_dir_name=canonical_extension_dir_name(discovered_index),
                first_invalid_message=(
                    "extension directories must be sequential with no gaps; "
                    f"expected {canonical_extension_dir_name(expected_index)} but found "
                    f"{canonical_extension_dir_name(discovered_index)}"
                ),
            )
        path = candidate_dirs[expected_index]
        try:
            discovered = _discover_extension_directory(index=expected_index, path=path)
        except ValueError as exc:
            return ValidatedExtensionDiscovery(
                directories=tuple(validated),
                first_invalid_dir_name=path.name,
                first_invalid_message=str(exc),
            )
        validated.append(discovered)
        expected_index += 1

    if expected_index in invalid_decimal_dirs:
        invalid_name = invalid_decimal_dirs[expected_index]
        return ValidatedExtensionDiscovery(
            directories=tuple(validated),
            first_invalid_dir_name=invalid_name,
            first_invalid_message=f"invalid non-canonical extension directory name: {invalid_name}",
        )
    if unexpected_extension_like_entries:
        invalid_name = sorted(unexpected_extension_like_entries)[0]
        return ValidatedExtensionDiscovery(
            directories=tuple(validated),
            first_invalid_dir_name=invalid_name,
            first_invalid_message=(
                "extensions directory contains unexpected extension-like top-level entry: "
                f"{invalid_name}"
            ),
        )

    return ValidatedExtensionDiscovery(directories=tuple(validated))


def _is_extension_like_top_level_entry(name: str) -> bool:
    return name.startswith(("extension-", "extension_")) or name.startswith(
        _RECOGNIZED_FILENAME_PREFIXES
    )


def _discover_extension_directory(*, index: int, path: Path) -> DiscoveredExtensionDirectory:
    if path.is_symlink():
        raise ValueError(f"extension directory {path.name} must not be a symlink")
    main_carriers: list[DiscoveredExtensionMainCarrier] = []
    shard_carriers: list[DiscoveredExtensionShardCarrier] = []
    main_types: set[str] = set()
    shard_keys: set[tuple[str, int]] = set()

    for entry in sorted(path.iterdir(), key=lambda item: item.name):
        if entry.is_symlink():
            raise ValueError(
                "extension directory "
                f"{path.name} must not contain symlinked artifacts: {entry.name}"
            )
        if not entry.is_file():
            raise ValueError(
                f"extension directory {path.name} contains unexpected non-file entry: {entry.name}"
            )
        if not _is_recognized_extension_filename(entry.name):
            raise ValueError(
                f"extension directory {path.name} contains unexpected artifact: {entry.name}"
            )
        _collect_extension_artifact(
            entry=entry,
            expected_index=index,
            main_carriers=main_carriers,
            shard_carriers=shard_carriers,
            main_types=main_types,
            shard_keys=shard_keys,
        )

    required_main_carriers = tuple(
        carrier for carrier in main_carriers if carrier.doc_type in _REQUIRED_MAIN_DOC_TYPES
    )
    if not required_main_carriers:
        raise ValueError(
            f"extension directory {path.name} must contain required MAIN documents: "
            "qr_document, recovery_document"
        )
    required_types = {carrier.doc_type for carrier in required_main_carriers}
    if required_types != _REQUIRED_MAIN_DOC_TYPES:
        missing = sorted(_REQUIRED_MAIN_DOC_TYPES.difference(required_types))
        raise ValueError(
            f"extension directory {path.name} is missing required MAIN documents: "
            f"{', '.join(missing)}"
        )

    doc_ids = {carrier.doc_id_hex for carrier in main_carriers}
    if len(doc_ids) != 1:
        raise ValueError(f"extension directory {path.name} has conflicting MAIN carrier doc_ids")
    doc_id_hex = next(iter(doc_ids))

    for carrier in shard_carriers:
        if carrier.doc_id_hex != doc_id_hex:
            raise ValueError(
                f"extension directory {path.name} shard carrier doc_id does not match MAIN carriers"
            )

    return DiscoveredExtensionDirectory(
        index=index,
        dir_name=path.name,
        path=path,
        doc_id_hex=doc_id_hex,
        main_carriers=required_main_carriers,
        shard_carriers=tuple(shard_carriers),
        recovery_kit_index_carrier=next(
            (carrier for carrier in main_carriers if carrier.doc_type == "recovery_kit_index"),
            None,
        ),
    )


def _collect_extension_artifact(
    *,
    entry: Path,
    expected_index: int,
    main_carriers: list[DiscoveredExtensionMainCarrier],
    shard_carriers: list[DiscoveredExtensionShardCarrier],
    main_types: set[str],
    shard_keys: set[tuple[str, int]],
) -> None:
    if entry.name.startswith(_MAIN_FILENAME_PREFIXES):
        parsed_main = _parse_main_carrier(entry=entry, expected_index=expected_index)
        if parsed_main.doc_type in main_types:
            raise ValueError(
                f"extension directory {entry.parent.name} contains duplicate MAIN carrier "
                f"{parsed_main.doc_type}"
            )
        main_types.add(parsed_main.doc_type)
        main_carriers.append(parsed_main)
        return

    parsed_shard = _parse_shard_carrier(entry=entry, expected_index=expected_index)
    shard_key = (parsed_shard.doc_type, parsed_shard.share_index)
    if shard_key in shard_keys:
        raise ValueError(
            f"extension directory {entry.parent.name} contains duplicate shard carrier "
            f"{parsed_shard.doc_type} {parsed_shard.share_index}-of-{parsed_shard.share_count}"
        )
    shard_keys.add(shard_key)
    shard_carriers.append(parsed_shard)


def _parse_main_carrier(*, entry: Path, expected_index: int) -> DiscoveredExtensionMainCarrier:
    try:
        parsed = parse_extension_main_filename(entry.name)
    except ValueError as exc:
        raise ValueError(f"invalid extension MAIN carrier filename: {entry.name}") from exc
    _require_matching_index(
        parsed=parsed,
        expected_index=expected_index,
        entry=entry,
    )
    return DiscoveredExtensionMainCarrier(
        doc_type=parsed.doc_type,
        path=entry,
        filename=entry.name,
        doc_id_hex=parsed.doc_id_hex,
    )


def _parse_shard_carrier(*, entry: Path, expected_index: int) -> DiscoveredExtensionShardCarrier:
    try:
        parsed = parse_extension_shard_filename(entry.name)
    except ValueError as exc:
        raise ValueError(f"invalid extension shard carrier filename: {entry.name}") from exc
    _require_matching_index(
        parsed=parsed,
        expected_index=expected_index,
        entry=entry,
    )
    return DiscoveredExtensionShardCarrier(
        doc_type=parsed.doc_type,
        path=entry,
        filename=entry.name,
        doc_id_hex=parsed.doc_id_hex,
        share_index=parsed.share_index,
        share_count=parsed.share_count,
    )


def _require_matching_index(
    *,
    parsed: ExtensionMainArtifactName | ExtensionShardArtifactName,
    expected_index: int,
    entry: Path,
) -> None:
    if parsed.index != expected_index:
        raise ValueError(
            f"extension artifact {entry.name} index {parsed.index} does not match directory "
            f"{entry.parent.name}"
        )


def _is_recognized_extension_filename(filename: str) -> bool:
    return filename.startswith(_RECOGNIZED_FILENAME_PREFIXES)
