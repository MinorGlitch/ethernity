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

"""Staging-directory validation and atomic promotion helpers for extensions."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from ethernity.artifacts.publish import (
    ArtifactSnapshot,
    promote_staged_artifact_dir,
    snapshot_artifact_dir,
)
from ethernity.extensions.discovery import EXTENSIONS_DIR_NAME
from ethernity.extensions.layout import (
    build_extension_main_filename,
    build_extension_shard_filename,
    build_staging_dir_name,
    canonical_extension_dir_name,
    is_staging_dir_name,
    parse_extension_main_filename,
    parse_extension_shard_filename,
)

EXTENSION_CHAIN_LOCK_DIR_NAME = ".chain.lock"
DirectoryIdentity = tuple[int, int]
StagedExtensionSnapshot = ArtifactSnapshot


@dataclass(frozen=True)
class ExtensionPublishPolicy:
    require_recovery_kit_index: bool = False
    passphrase_shard_count: int = 0
    signing_key_shard_count: int = 0

    def __post_init__(self) -> None:
        for label, value in (
            ("passphrase_shard_count", self.passphrase_shard_count),
            ("signing_key_shard_count", self.signing_key_shard_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{label} must be a non-negative integer")


@dataclass(frozen=True)
class ValidatedStagedExtension:
    staging_dir: Path
    final_dir_name: str
    doc_id_hex: str
    expected_index: int
    publish_policy: ExtensionPublishPolicy
    staging_dir_identity: DirectoryIdentity
    staging_snapshot: StagedExtensionSnapshot
    root_dir_identity: DirectoryIdentity
    extensions_dir_identity: DirectoryIdentity


@dataclass(frozen=True)
class PlannedStagedExtensionArtifacts:
    staging_dir: Path
    final_dir: Path
    root_dir_identity: DirectoryIdentity
    extensions_dir_identity: DirectoryIdentity
    qr_document_path: Path
    recovery_document_path: Path
    recovery_kit_index_path: Path | None
    shard_paths: tuple[Path, ...]
    signing_key_shard_paths: tuple[Path, ...]


def create_extension_staging_dir(root_dir: str | Path, *, index: int, nonce: str) -> Path:
    """Create and return a non-canonical staging directory under the extensions root."""

    root_path = Path(root_dir).expanduser()
    _require_existing_directory_no_symlink(
        root_path,
        label="root backup directory",
        display_path=root_dir,
    )
    extensions_dir = root_path / EXTENSIONS_DIR_NAME
    if extensions_dir.is_symlink():
        raise ValueError("extensions path must not be a symlink")
    extensions_dir.mkdir(mode=0o700, parents=False, exist_ok=True)
    _require_existing_directory_no_symlink(extensions_dir, label="extensions path")
    staging_dir = extensions_dir / build_staging_dir_name(index, nonce)
    staging_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    _require_existing_directory_no_symlink(staging_dir, label="staging directory")
    staging_dir.chmod(0o700)
    _require_existing_directory_no_symlink(staging_dir, label="staging directory")
    return staging_dir


def _require_existing_directory_no_symlink(
    path: Path,
    *,
    label: str,
    display_path: str | Path | None = None,
) -> None:
    _directory_identity(path, label=label, display_path=display_path)


def _directory_identity(
    path: Path,
    *,
    label: str,
    display_path: str | Path | None = None,
) -> DirectoryIdentity:
    path_label = path if display_path is None else display_path
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError(f"{label} not found: {path_label}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"{label} must not be a symlink")
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{label} must be a directory: {path_label}")
    return metadata.st_dev, metadata.st_ino


def _require_directory_identity(
    path: Path,
    *,
    expected: DirectoryIdentity,
    label: str,
) -> None:
    actual = _directory_identity(path, label=label)
    if actual != expected:
        raise ValueError(f"{label} changed before promotion")


def _require_publish_directory_identities(validated: ValidatedStagedExtension) -> None:
    extensions_dir = validated.staging_dir.parent
    root_dir = extensions_dir.parent
    _require_directory_identity(
        root_dir,
        expected=validated.root_dir_identity,
        label="root backup directory",
    )
    _require_directory_identity(
        extensions_dir,
        expected=validated.extensions_dir_identity,
        label="extensions directory",
    )


def _require_staging_directory_identity(validated: ValidatedStagedExtension) -> None:
    _require_directory_identity(
        validated.staging_dir,
        expected=validated.staging_dir_identity,
        label="staging directory",
    )


def preflight_extension_publish_target(root_dir: str | Path, *, index: int) -> None:
    """Validate extension publish target paths without creating files or directories."""

    if isinstance(index, bool) or not isinstance(index, int) or index <= 0:
        raise ValueError("extension index must be a positive integer")
    root_path = Path(root_dir).expanduser()
    if root_path.is_symlink():
        raise ValueError("root backup directory must not be a symlink")
    if not root_path.exists():
        raise ValueError(f"root backup directory not found: {root_dir}")
    if not root_path.is_dir():
        raise ValueError(f"root backup directory must be a directory: {root_dir}")
    extensions_dir = root_path / EXTENSIONS_DIR_NAME
    if extensions_dir.is_symlink():
        raise ValueError("extensions path must not be a symlink")
    if extensions_dir.exists() and not extensions_dir.is_dir():
        raise ValueError("extensions path must be a directory")
    writable_dir = extensions_dir if extensions_dir.exists() else root_path
    if not os.access(writable_dir, os.W_OK | os.X_OK):
        raise ValueError(f"extension publish target is not writable: {writable_dir}")
    final_dir = extensions_dir / canonical_extension_dir_name(index)
    if final_dir.exists() or final_dir.is_symlink():
        raise ValueError(f"canonical extension directory already exists: {final_dir.name}")
    lock_dir = extensions_dir / f".{final_dir.name}.lock"
    if lock_dir.exists() or lock_dir.is_symlink():
        raise ValueError(
            f"canonical extension directory is already being promoted: {final_dir.name}"
        )
    chain_lock_dir = extensions_dir / EXTENSION_CHAIN_LOCK_DIR_NAME
    if chain_lock_dir.exists() or chain_lock_dir.is_symlink():
        raise ValueError("extension chain is already being promoted")


def create_staged_extension_artifact_plan(
    root_dir: str | Path,
    *,
    index: int,
    doc_id_hex: str,
    nonce: str,
    publish_policy: ExtensionPublishPolicy,
) -> PlannedStagedExtensionArtifacts:
    """Create a staging directory and return the exact artifact paths to populate."""

    staging_dir = create_extension_staging_dir(root_dir, index=index, nonce=nonce)
    final_dir = staging_dir.parent / canonical_extension_dir_name(index)
    root_dir_identity, extensions_dir_identity = _publish_directory_identities(staging_dir)
    qr_document_path = staging_dir / build_extension_main_filename("qr_document", index, doc_id_hex)
    recovery_document_path = staging_dir / build_extension_main_filename(
        "recovery_document",
        index,
        doc_id_hex,
    )
    recovery_kit_index_path = (
        staging_dir / build_extension_main_filename("recovery_kit_index", index, doc_id_hex)
        if publish_policy.require_recovery_kit_index
        else None
    )
    shard_paths = tuple(
        staging_dir
        / build_extension_shard_filename(
            "shard",
            index,
            doc_id_hex,
            share_index=share_index,
            share_count=publish_policy.passphrase_shard_count,
        )
        for share_index in range(1, publish_policy.passphrase_shard_count + 1)
    )
    signing_key_shard_paths = tuple(
        staging_dir
        / build_extension_shard_filename(
            "signing-key-shard",
            index,
            doc_id_hex,
            share_index=share_index,
            share_count=publish_policy.signing_key_shard_count,
        )
        for share_index in range(1, publish_policy.signing_key_shard_count + 1)
    )
    return PlannedStagedExtensionArtifacts(
        staging_dir=staging_dir,
        final_dir=final_dir,
        root_dir_identity=root_dir_identity,
        extensions_dir_identity=extensions_dir_identity,
        qr_document_path=qr_document_path,
        recovery_document_path=recovery_document_path,
        recovery_kit_index_path=recovery_kit_index_path,
        shard_paths=shard_paths,
        signing_key_shard_paths=signing_key_shard_paths,
    )


def validate_staged_extension_dir(
    staging_dir: str | Path,
    *,
    expected_index: int,
    publish_policy: ExtensionPublishPolicy,
    expected_root_dir_identity: DirectoryIdentity | None = None,
    expected_extensions_dir_identity: DirectoryIdentity | None = None,
) -> ValidatedStagedExtension:
    """Validate a staged extension artifact set before atomic promotion."""

    path = Path(staging_dir).expanduser()
    if path.is_symlink():
        raise ValueError("staging_dir must not be a symlink")
    if not path.exists() or not path.is_dir():
        raise ValueError("staging_dir must be an existing directory")
    if not is_staging_dir_name(path.name):
        raise ValueError("staging_dir must use a non-canonical .staging-* name")
    root_dir_identity, extensions_dir_identity = _publish_directory_identities(path)
    staging_dir_identity = _directory_identity(path, label="staging directory")
    if expected_root_dir_identity is not None and root_dir_identity != expected_root_dir_identity:
        raise ValueError("root backup directory changed before promotion")
    if (
        expected_extensions_dir_identity is not None
        and extensions_dir_identity != expected_extensions_dir_identity
    ):
        raise ValueError("extensions directory changed before promotion")

    main_doc_ids: dict[str, str] = {}
    passphrase_shares: dict[int, tuple[int, str]] = {}
    signing_key_shares: dict[int, tuple[int, str]] = {}

    for entry in sorted(path.iterdir(), key=lambda item: item.name):
        if entry.is_symlink():
            raise ValueError(f"staged extension contains symlinked artifact: {entry.name}")
        if not entry.is_file():
            raise ValueError(f"staged extension contains unexpected non-file entry: {entry.name}")
        if entry.name.startswith(("qr_document-", "recovery_document-", "recovery_kit_index-")):
            parsed_main = parse_extension_main_filename(entry.name)
            _require_index_match(
                entry=entry,
                actual_index=parsed_main.index,
                expected_index=expected_index,
            )
            if parsed_main.doc_type in main_doc_ids:
                raise ValueError(f"duplicate staged MAIN artifact: {parsed_main.doc_type}")
            main_doc_ids[parsed_main.doc_type] = parsed_main.doc_id_hex
            continue
        if entry.name.startswith(("shard-", "signing-key-shard-")):
            parsed_shard = parse_extension_shard_filename(entry.name)
            _require_index_match(
                entry=entry,
                actual_index=parsed_shard.index,
                expected_index=expected_index,
            )
            share_map = (
                passphrase_shares if parsed_shard.doc_type == "shard" else signing_key_shares
            )
            if parsed_shard.share_index in share_map:
                raise ValueError(
                    "duplicate staged shard artifact: "
                    f"{parsed_shard.doc_type} {parsed_shard.share_index}-of-"
                    f"{parsed_shard.share_count}"
                )
            share_map[parsed_shard.share_index] = (
                parsed_shard.share_count,
                parsed_shard.doc_id_hex,
            )
            continue
        raise ValueError(f"staged extension contains unexpected artifact: {entry.name}")

    _require_main_artifacts(main_doc_ids, publish_policy)
    doc_id_hex = _require_single_doc_id(
        main_doc_ids,
        passphrase_shares,
        signing_key_shares,
        path=path,
    )
    _require_complete_shards(
        doc_type="shard",
        shares=passphrase_shares,
        expected_count=publish_policy.passphrase_shard_count,
    )
    _require_complete_shards(
        doc_type="signing-key-shard",
        shares=signing_key_shares,
        expected_count=publish_policy.signing_key_shard_count,
    )
    staging_snapshot = snapshot_artifact_dir(path)

    return ValidatedStagedExtension(
        staging_dir=path,
        final_dir_name=canonical_extension_dir_name(expected_index),
        doc_id_hex=doc_id_hex,
        expected_index=expected_index,
        publish_policy=publish_policy,
        staging_dir_identity=staging_dir_identity,
        staging_snapshot=staging_snapshot,
        root_dir_identity=root_dir_identity,
        extensions_dir_identity=extensions_dir_identity,
    )


def promote_staged_extension_dir(validated: ValidatedStagedExtension) -> Path:
    """Atomically promote a validated staged extension into its canonical directory."""

    staging_dir = validated.staging_dir
    if staging_dir.is_symlink():
        raise ValueError("validated staging_dir must not be a symlink")
    _require_publish_directory_identities(validated)
    if not staging_dir.exists() or not staging_dir.is_dir():
        raise ValueError("validated staging_dir no longer exists")
    _require_staging_directory_identity(validated)
    expected_final_dir_name = canonical_extension_dir_name(validated.expected_index)
    final_dir = staging_dir.parent / expected_final_dir_name

    def _validate_for_promotion(path: Path) -> None:
        _require_publish_directory_identities(validated)
        _require_staging_directory_identity(validated)
        revalidated = validate_staged_extension_dir(
            path,
            expected_index=validated.expected_index,
            publish_policy=validated.publish_policy,
        )
        if revalidated.doc_id_hex != validated.doc_id_hex:
            raise ValueError("validated staging_dir doc_id changed before promotion")

    try:
        return promote_staged_artifact_dir(
            staging_dir,
            final_dir,
            expected_snapshot=validated.staging_snapshot,
            validate_staging=_validate_for_promotion,
            lock_dir=staging_dir.parent / f".{expected_final_dir_name}.lock",
        )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("final artifact directory already exists"):
            raise ValueError(
                f"canonical extension directory already exists: {final_dir.name}"
            ) from exc
        if message.startswith("final artifact directory is already being promoted"):
            raise ValueError(
                f"canonical extension directory is already being promoted: {final_dir.name}"
            ) from exc
        raise


def snapshot_staged_extension_dir(staging_dir: str | Path) -> StagedExtensionSnapshot:
    """Return a content fingerprint for all regular files in a staged extension directory."""

    return snapshot_artifact_dir(staging_dir)


def _publish_directory_identities(staging_dir: Path) -> tuple[DirectoryIdentity, DirectoryIdentity]:
    extensions_dir = staging_dir.parent
    root_dir = extensions_dir.parent
    root_dir_identity = _directory_identity(root_dir, label="root backup directory")
    extensions_dir_identity = _directory_identity(extensions_dir, label="extensions directory")
    return root_dir_identity, extensions_dir_identity


def _require_index_match(*, entry: Path, actual_index: int, expected_index: int) -> None:
    if actual_index != expected_index:
        raise ValueError(
            f"staged artifact {entry.name} index {actual_index} does not match expected index "
            f"{expected_index}"
        )


def _require_main_artifacts(
    main_doc_ids: dict[str, str],
    publish_policy: ExtensionPublishPolicy,
) -> None:
    required = {"qr_document", "recovery_document"}
    if publish_policy.require_recovery_kit_index:
        required.add("recovery_kit_index")
    elif "recovery_kit_index" in main_doc_ids:
        raise ValueError("staged extension unexpectedly includes recovery_kit_index MAIN artifact")
    missing = sorted(required.difference(main_doc_ids))
    if missing:
        raise ValueError(
            f"staged extension is missing required MAIN artifacts: {', '.join(missing)}"
        )


def _require_single_doc_id(
    main_doc_ids: dict[str, str],
    passphrase_shares: dict[int, tuple[int, str]],
    signing_key_shares: dict[int, tuple[int, str]],
    *,
    path: Path,
) -> str:
    doc_ids = set(main_doc_ids.values())
    if len(doc_ids) != 1:
        raise ValueError(f"staged extension {path.name} has conflicting MAIN artifact doc_ids")
    doc_id_hex = next(iter(doc_ids))
    for shares in (passphrase_shares, signing_key_shares):
        for _share_index, (_share_count, shard_doc_id_hex) in shares.items():
            if shard_doc_id_hex != doc_id_hex:
                raise ValueError(
                    f"staged extension {path.name} shard artifact doc_id "
                    "does not match MAIN artifacts"
                )
    return doc_id_hex


def _require_complete_shards(
    *,
    doc_type: str,
    shares: dict[int, tuple[int, str]],
    expected_count: int,
) -> None:
    if expected_count == 0:
        if shares:
            raise ValueError(f"staged extension unexpectedly includes {doc_type} artifacts")
        return
    if not shares:
        raise ValueError(f"staged extension is missing required {doc_type} artifacts")
    if set(shares) != set(range(1, expected_count + 1)):
        raise ValueError(
            f"staged extension {doc_type} artifacts must include shares 1 through {expected_count}"
        )
    counts = {share_count for share_count, _doc_id_hex in shares.values()}
    if counts != {expected_count}:
        raise ValueError(
            f"staged extension {doc_type} artifacts must all declare share_count={expected_count}"
        )
