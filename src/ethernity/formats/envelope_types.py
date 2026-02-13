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

from __future__ import annotations

from dataclasses import dataclass

from ..core.bounds import MAX_MANIFEST_FILES
from ..core.validation import (
    normalize_manifest_path,
    normalize_path,
    require_bytes,
    require_dict,
    require_keys,
    require_length,
)

MANIFEST_VERSION = 1
SIGNING_SEED_LEN = 32


@dataclass(frozen=True)
class ManifestFile:
    path: str
    size: int
    sha256: bytes
    mtime: int | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "path",
            normalize_manifest_path(self.path, label="manifest file path"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "size": self.size,
            "sha256": self.sha256,
            "mtime": self.mtime,
        }


@dataclass(frozen=True)
class EnvelopeManifest:
    format_version: int
    created_at: float
    sealed: bool
    signing_seed: bytes | None
    files: tuple[ManifestFile, ...]
    input_origin: str = "file"
    input_roots: tuple[str, ...] = ()

    def to_cbor(self) -> dict[str, object]:
        if not self.files:
            raise ValueError("manifest files are required")
        if len(self.files) > MAX_MANIFEST_FILES:
            raise ValueError(
                f"manifest files exceed MAX_MANIFEST_FILES ({MAX_MANIFEST_FILES}): "
                f"{len(self.files)} entries"
            )

        if self.sealed:
            if self.signing_seed is not None:
                raise ValueError("sealed manifests must not include seed")
        else:
            if self.signing_seed is None:
                raise ValueError("unsealed manifests must include seed")
            require_length(self.signing_seed, SIGNING_SEED_LEN, label="seed")
        if self.input_origin not in {"file", "directory", "mixed"}:
            raise ValueError("manifest input_origin must be one of: file, directory, mixed")
        normalized_roots = tuple(_normalize_root_label(root) for root in self.input_roots)
        _validate_input_origin_roots(self.input_origin, normalized_roots)

        seen_paths: set[str] = set()
        for entry in self.files:
            if entry.path in seen_paths:
                raise ValueError(f"duplicate manifest file path: {entry.path}")
            seen_paths.add(entry.path)

        files = []
        for file in self.files:
            files.append(
                {
                    "path": file.path,
                    "size": file.size,
                    "hash": file.sha256,
                    "mtime": file.mtime,
                }
            )
        return {
            "version": self.format_version,
            "created": self.created_at,
            "sealed": self.sealed,
            "seed": self.signing_seed,
            "input_origin": self.input_origin,
            "input_roots": list(normalized_roots),
            "files": files,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "format_version": self.format_version,
            "created_at": self.created_at,
            "sealed": self.sealed,
            "signing_seed": self.signing_seed,
            "input_origin": self.input_origin,
            "input_roots": list(self.input_roots),
            "files": [file.to_dict() for file in self.files],
        }

    @classmethod
    def from_cbor(cls, data: object) -> "EnvelopeManifest":
        validated = require_dict(data, label="manifest")
        require_keys(
            validated,
            ("version", "created", "sealed", "seed", "input_origin", "input_roots", "files"),
            label="manifest",
        )
        format_version = validated["version"]
        created_at = validated["created"]
        sealed = validated["sealed"]
        signing_seed = validated["seed"]
        input_origin = validated["input_origin"]
        input_roots = validated["input_roots"]
        files_raw = validated["files"]
        if not isinstance(format_version, int):
            raise ValueError("manifest version must be an int")
        if format_version != MANIFEST_VERSION:
            raise ValueError(f"unsupported manifest version: {format_version}")
        if not isinstance(created_at, (int, float)):
            raise ValueError("manifest created must be a number")
        if not isinstance(sealed, bool):
            raise ValueError("manifest sealed must be a boolean")
        if not isinstance(input_origin, str):
            raise ValueError("manifest input_origin must be a string")
        if input_origin not in {"file", "directory", "mixed"}:
            raise ValueError("manifest input_origin must be one of: file, directory, mixed")
        if not isinstance(input_roots, (list, tuple)):
            raise ValueError("manifest input_roots must be a list")
        normalized_roots: list[str] = []
        for root in input_roots:
            normalized_roots.append(_normalize_root_label(root))
        _validate_input_origin_roots(input_origin, tuple(normalized_roots))
        if sealed:
            if signing_seed is not None:
                raise ValueError("manifest seed must be null for sealed manifests")
            seed_bytes = None
        else:
            seed_bytes = require_bytes(
                signing_seed,
                SIGNING_SEED_LEN,
                label="seed",
                prefix="manifest ",
            )
        if not isinstance(files_raw, list) or not files_raw:
            raise ValueError("manifest files are required")
        if len(files_raw) > MAX_MANIFEST_FILES:
            raise ValueError(
                f"manifest files exceed MAX_MANIFEST_FILES ({MAX_MANIFEST_FILES}): "
                f"{len(files_raw)} entries"
            )
        files: list[ManifestFile] = []
        seen_paths: set[str] = set()
        for entry in files_raw:
            validated_entry = require_dict(entry, label="manifest file entry")
            require_keys(
                validated_entry,
                ("path", "size", "hash", "mtime"),
                label="manifest file entry",
            )
            path = validated_entry["path"]
            size = validated_entry["size"]
            sha256 = validated_entry["hash"]
            mtime = validated_entry["mtime"]
            if not isinstance(path, str) or not path:
                raise ValueError("manifest file path must be a non-empty string")
            if not isinstance(size, int) or size < 0:
                raise ValueError("manifest file size must be a non-negative int")
            sha_bytes = _coerce_sha256(sha256)
            if sha_bytes is None:
                raise ValueError("manifest file hash must be 32 raw bytes")
            if mtime is not None and not isinstance(mtime, int):
                raise ValueError("manifest file mtime must be an int")
            file_entry = ManifestFile(
                path=path,
                size=size,
                sha256=sha_bytes,
                mtime=int(mtime) if mtime is not None else None,
            )
            if file_entry.path in seen_paths:
                raise ValueError(f"duplicate manifest file path: {file_entry.path}")
            seen_paths.add(file_entry.path)
            files.append(file_entry)
        return cls(
            format_version=format_version,
            created_at=float(created_at),
            sealed=sealed,
            signing_seed=seed_bytes,
            input_origin=input_origin,
            input_roots=tuple(normalized_roots),
            files=tuple(files),
        )


@dataclass(frozen=True)
class PayloadPart:
    path: str
    data: bytes
    mtime: int | None


def _coerce_sha256(value: object) -> bytes | None:
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if len(raw) == 32:
            return raw
        return None
    return None


def _normalize_root_label(value: object) -> str:
    root = normalize_path(value, label="manifest input_root")
    root = root.strip()
    if not root:
        raise ValueError("manifest input_root must be a non-empty string")
    if "/" in root or "\\" in root:
        raise ValueError("manifest input_root must be a leaf label without path separators")
    return root


def _validate_input_origin_roots(input_origin: str, input_roots: tuple[str, ...]) -> None:
    if input_origin == "file":
        if input_roots:
            raise ValueError("manifest input_roots must be empty when input_origin is file")
        return
    if not input_roots:
        raise ValueError("manifest input_roots must be non-empty for directory or mixed input")
