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
    require_list,
)
from ..encoding.cbor import dumps_canonical

MANIFEST_VERSION = 1
SIGNING_SEED_LEN = 32
PATH_ENCODING_DIRECT = "direct"
PATH_ENCODING_PREFIX_TABLE = "prefix_table"


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

        base_manifest: dict[str, object] = {
            "version": self.format_version,
            "created": self.created_at,
            "sealed": self.sealed,
            "seed": self.signing_seed,
            "input_origin": self.input_origin,
            "input_roots": list(normalized_roots),
        }

        direct_manifest = dict(base_manifest)
        direct_manifest["path_encoding"] = PATH_ENCODING_DIRECT
        direct_manifest["files"] = _encode_direct_files(self.files)

        path_prefixes = _build_prefix_table([entry.path for entry in self.files])
        prefix_manifest = dict(base_manifest)
        prefix_manifest["path_encoding"] = PATH_ENCODING_PREFIX_TABLE
        prefix_manifest["path_prefixes"] = list(path_prefixes)
        prefix_manifest["files"] = _encode_prefix_files(self.files, path_prefixes)

        encoded_direct = dumps_canonical(direct_manifest)
        encoded_prefix = dumps_canonical(prefix_manifest)
        if len(encoded_prefix) < len(encoded_direct):
            return prefix_manifest
        return direct_manifest

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
            (
                "version",
                "created",
                "sealed",
                "seed",
                "input_origin",
                "input_roots",
                "path_encoding",
                "files",
            ),
            label="manifest",
        )
        format_version = validated["version"]
        created_at = validated["created"]
        sealed = validated["sealed"]
        signing_seed = validated["seed"]
        input_origin = validated["input_origin"]
        input_roots = validated["input_roots"]
        path_encoding = validated["path_encoding"]
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
        if not isinstance(path_encoding, str):
            raise ValueError("manifest path_encoding must be a string")
        if path_encoding not in {PATH_ENCODING_DIRECT, PATH_ENCODING_PREFIX_TABLE}:
            raise ValueError("manifest path_encoding must be one of: direct, prefix_table")
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
        if path_encoding == PATH_ENCODING_DIRECT:
            files = _decode_direct_files(files_raw)
        else:
            if "path_prefixes" not in validated:
                raise ValueError("manifest path_prefixes is required for prefix_table encoding")
            path_prefixes = _validate_path_prefixes(validated["path_prefixes"])
            files = _decode_prefix_files(files_raw, path_prefixes)

        seen_paths: set[str] = set()
        for file_entry in files:
            if file_entry.path in seen_paths:
                raise ValueError(f"duplicate manifest file path: {file_entry.path}")
            seen_paths.add(file_entry.path)
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


def _build_prefix_table(paths: list[str]) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    for path in paths:
        parts = path.split("/")
        prefix = ""
        for idx in range(len(parts) - 1):
            prefix = parts[idx] if idx == 0 else f"{prefix}/{parts[idx]}"
            counts[prefix] = counts.get(prefix, 0) + 1
    shared_prefixes = sorted(
        (prefix for prefix, count in counts.items() if count > 1),
        key=lambda value: (len(value), value),
    )
    return ("", *shared_prefixes)


def _select_prefix(path: str, sorted_prefixes_desc: list[str]) -> str:
    for prefix in sorted_prefixes_desc:
        if path.startswith(f"{prefix}/"):
            return prefix
    return ""


def _strip_prefix(path: str, prefix: str) -> str:
    if not prefix:
        return path
    return path[len(prefix) + 1 :]


def _encode_direct_files(files: tuple[ManifestFile, ...]) -> list[list[object]]:
    encoded: list[list[object]] = []
    for entry in files:
        encoded.append([entry.path, entry.size, entry.sha256, entry.mtime])
    return encoded


def _encode_prefix_files(
    files: tuple[ManifestFile, ...],
    path_prefixes: tuple[str, ...],
) -> list[list[object]]:
    prefix_index = {prefix: idx for idx, prefix in enumerate(path_prefixes)}
    sorted_prefixes_desc = sorted(path_prefixes[1:], key=len, reverse=True)
    encoded: list[list[object]] = []
    for entry in files:
        prefix = _select_prefix(entry.path, sorted_prefixes_desc)
        suffix = _strip_prefix(entry.path, prefix)
        encoded.append(
            [
                prefix_index[prefix],
                suffix,
                entry.size,
                entry.sha256,
                entry.mtime,
            ]
        )
    return encoded


def _decode_direct_files(files_raw: list[object]) -> list[ManifestFile]:
    files: list[ManifestFile] = []
    for entry in files_raw:
        files.append(_decode_direct_file_entry(entry))
    return files


def _decode_prefix_files(
    files_raw: list[object],
    path_prefixes: tuple[str, ...],
) -> list[ManifestFile]:
    files: list[ManifestFile] = []
    for entry in files_raw:
        files.append(_decode_prefix_file_entry(entry, path_prefixes))
    return files


def _decode_direct_file_entry(entry: object) -> ManifestFile:
    if isinstance(entry, dict):
        raise ValueError("manifest file entry must use array encoding")
    values = require_list(entry, 4, label="manifest file entry")
    path = values[0]
    size = values[1]
    sha256 = values[2]
    mtime = values[3]
    return _build_manifest_file(path=path, size=size, sha256=sha256, mtime=mtime)


def _decode_prefix_file_entry(entry: object, path_prefixes: tuple[str, ...]) -> ManifestFile:
    if isinstance(entry, dict):
        raise ValueError("manifest file entry must use array encoding")
    values = require_list(entry, 5, label="manifest file entry")
    prefix_index = values[0]
    suffix = values[1]
    size = values[2]
    sha256 = values[3]
    mtime = values[4]
    if not isinstance(prefix_index, int):
        raise ValueError("manifest file prefix_index must be an int")
    if prefix_index < 0 or prefix_index >= len(path_prefixes):
        raise ValueError("manifest file prefix_index out of range")
    if not isinstance(suffix, str) or not suffix:
        raise ValueError("manifest file suffix must be a non-empty string")
    prefix = path_prefixes[prefix_index]
    path = f"{prefix}/{suffix}" if prefix else suffix
    return _build_manifest_file(path=path, size=size, sha256=sha256, mtime=mtime)


def _build_manifest_file(
    *,
    path: object,
    size: object,
    sha256: object,
    mtime: object,
) -> ManifestFile:
    if not isinstance(path, str) or not path:
        raise ValueError("manifest file path must be a non-empty string")
    if not isinstance(size, int) or size < 0:
        raise ValueError("manifest file size must be a non-negative int")
    sha_bytes = _coerce_sha256(sha256)
    if sha_bytes is None:
        raise ValueError("manifest file hash must be 32 raw bytes")
    if mtime is not None and not isinstance(mtime, int):
        raise ValueError("manifest file mtime must be an int")
    return ManifestFile(
        path=path,
        size=size,
        sha256=sha_bytes,
        mtime=int(mtime) if mtime is not None else None,
    )


def _validate_path_prefixes(value: object) -> tuple[str, ...]:
    raw_prefixes = require_list(value, 1, label="manifest path_prefixes")
    if raw_prefixes[0] != "":
        raise ValueError("manifest path_prefixes must start with empty string")
    normalized_prefixes: list[str] = []
    seen_prefixes: set[str] = set()
    for index, prefix in enumerate(raw_prefixes):
        if not isinstance(prefix, str):
            raise ValueError("manifest path_prefixes values must be strings")
        if index == 0:
            normalized = ""
        else:
            normalized = normalize_manifest_path(prefix, label="manifest path_prefix")
        if normalized in seen_prefixes:
            raise ValueError("manifest path_prefixes must be unique")
        seen_prefixes.add(normalized)
        normalized_prefixes.append(normalized)
    return tuple(normalized_prefixes)


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
