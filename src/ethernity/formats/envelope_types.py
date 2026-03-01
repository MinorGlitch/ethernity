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

"""Manifest dataclasses and encoding helpers for envelope payload metadata."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.bounds import MAX_DECOMPRESSED_PAYLOAD_BYTES, MAX_MANIFEST_FILES
from ..core.validation import (
    normalize_manifest_path,
    normalize_path,
    require_bool,
    require_bytes,
    require_dict,
    require_int,
    require_keys,
    require_length,
    require_list,
    require_non_empty_str,
    require_non_negative_int,
    require_str,
)
from ..encoding.cbor import dumps_canonical

MANIFEST_VERSION = 1
SIGNING_SEED_LEN = 32
PATH_ENCODING_DIRECT = "direct"
PATH_ENCODING_PREFIX_TABLE = "prefix_table"
PAYLOAD_CODEC_RAW = "raw"
PAYLOAD_CODEC_GZIP = "gzip"


@dataclass(frozen=True)
class ManifestFile:
    """One file entry stored in the envelope manifest."""

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
        """Return a debug-friendly dictionary form of the manifest entry."""

        return {
            "path": self.path,
            "size": self.size,
            "sha256": self.sha256,
            "mtime": self.mtime,
        }


@dataclass(frozen=True)
class EnvelopeManifest:
    """Envelope manifest metadata and file list."""

    format_version: int
    created_at: float
    sealed: bool
    signing_seed: bytes | None
    files: tuple[ManifestFile, ...]
    input_origin: str = "file"
    input_roots: tuple[str, ...] = ()
    payload_codec: str = PAYLOAD_CODEC_RAW
    payload_raw_len: int | None = None

    def to_cbor(self) -> dict[str, object]:
        """Build the canonical manifest CBOR map, selecting the shortest path encoding."""

        format_version = require_int(self.format_version, label="manifest version")
        if format_version != MANIFEST_VERSION:
            raise ValueError(f"unsupported manifest version: {format_version}")

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
        payload_codec = require_str(self.payload_codec, label="manifest payload_codec")
        if payload_codec not in {PAYLOAD_CODEC_RAW, PAYLOAD_CODEC_GZIP}:
            raise ValueError("manifest payload_codec must be one of: raw, gzip")
        expected_raw_len = sum(entry.size for entry in self.files)
        if payload_codec == PAYLOAD_CODEC_RAW:
            if self.payload_raw_len is not None:
                raise ValueError("manifest payload_raw_len must be null for raw payload_codec")
        else:
            if self.payload_raw_len is None:
                raise ValueError("manifest payload_raw_len is required for gzip payload_codec")
            raw_len = require_non_negative_int(
                self.payload_raw_len, label="manifest payload_raw_len"
            )
            if raw_len <= 0:
                raise ValueError("manifest payload_raw_len must be positive")
            if raw_len > MAX_DECOMPRESSED_PAYLOAD_BYTES:
                raise ValueError(
                    "manifest payload_raw_len exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES "
                    f"({MAX_DECOMPRESSED_PAYLOAD_BYTES}): {raw_len}"
                )
            if raw_len != expected_raw_len:
                raise ValueError("manifest payload_raw_len must match sum of manifest file sizes")

        seen_paths: set[str] = set()
        for entry in self.files:
            if entry.path in seen_paths:
                raise ValueError(f"duplicate manifest file path: {entry.path}")
            seen_paths.add(entry.path)

        base_manifest: dict[str, object] = {
            "version": format_version,
            "created": self.created_at,
            "sealed": self.sealed,
            "seed": self.signing_seed,
            "input_origin": self.input_origin,
            "input_roots": list(normalized_roots),
            "payload_codec": payload_codec,
        }
        if payload_codec == PAYLOAD_CODEC_GZIP:
            base_manifest["payload_raw_len"] = self.payload_raw_len

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
        """Return a debug-friendly dictionary form of the manifest."""

        return {
            "format_version": self.format_version,
            "created_at": self.created_at,
            "sealed": self.sealed,
            "signing_seed": self.signing_seed,
            "input_origin": self.input_origin,
            "input_roots": list(self.input_roots),
            "payload_codec": self.payload_codec,
            "payload_raw_len": self.payload_raw_len,
            "files": [file.to_dict() for file in self.files],
        }

    @classmethod
    def from_cbor(cls, data: object) -> "EnvelopeManifest":
        """Decode and validate a manifest object from parsed CBOR."""

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
                "payload_codec",
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
        payload_codec_raw = validated["payload_codec"]
        payload_raw_len_raw = validated.get("payload_raw_len")
        format_version = require_int(format_version, label="manifest version")
        if format_version != MANIFEST_VERSION:
            raise ValueError(f"unsupported manifest version: {format_version}")
        if not isinstance(created_at, (int, float)):
            raise ValueError("manifest created must be a number")
        sealed = require_bool(sealed, label="manifest sealed")
        input_origin = require_str(input_origin, label="manifest input_origin")
        if input_origin not in {"file", "directory", "mixed"}:
            raise ValueError("manifest input_origin must be one of: file, directory, mixed")
        if not isinstance(input_roots, (list, tuple)):
            raise ValueError("manifest input_roots must be a list")
        path_encoding = require_str(path_encoding, label="manifest path_encoding")
        if path_encoding not in {PATH_ENCODING_DIRECT, PATH_ENCODING_PREFIX_TABLE}:
            raise ValueError("manifest path_encoding must be one of: direct, prefix_table")
        payload_codec = require_str(payload_codec_raw, label="manifest payload_codec")
        if payload_codec not in {PAYLOAD_CODEC_RAW, PAYLOAD_CODEC_GZIP}:
            raise ValueError("manifest payload_codec must be one of: raw, gzip")
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
        expected_raw_len = sum(file_entry.size for file_entry in files)
        if payload_codec == PAYLOAD_CODEC_RAW:
            if payload_raw_len_raw is not None:
                raise ValueError("manifest payload_raw_len must be null for raw payload_codec")
            payload_raw_len = None
        else:
            if payload_raw_len_raw is None:
                raise ValueError("manifest payload_raw_len is required for gzip payload_codec")
            payload_raw_len = require_non_negative_int(
                payload_raw_len_raw, label="manifest payload_raw_len"
            )
            if payload_raw_len <= 0:
                raise ValueError("manifest payload_raw_len must be positive")
            if payload_raw_len > MAX_DECOMPRESSED_PAYLOAD_BYTES:
                raise ValueError(
                    "manifest payload_raw_len exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES "
                    f"({MAX_DECOMPRESSED_PAYLOAD_BYTES}): {payload_raw_len}"
                )
            if payload_raw_len != expected_raw_len:
                raise ValueError("manifest payload_raw_len must match sum of manifest file sizes")
        return cls(
            format_version=format_version,
            created_at=float(created_at),
            sealed=sealed,
            signing_seed=seed_bytes,
            input_origin=input_origin,
            input_roots=tuple(normalized_roots),
            payload_codec=payload_codec,
            payload_raw_len=payload_raw_len,
            files=tuple(files),
        )


@dataclass(frozen=True)
class PayloadPart:
    """Input payload part used to build an envelope manifest and payload bytes."""

    path: str
    data: bytes
    mtime: int | None


def _coerce_sha256(value: object) -> bytes | None:
    """Return a valid 32-byte hash or `None` for invalid values."""

    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if len(raw) == 32:
            return raw
        return None
    return None


def _build_prefix_table(paths: list[str]) -> tuple[str, ...]:
    """Build a shared-prefix table for prefix-table path encoding."""

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
    """Select the longest matching shared prefix for a path."""

    for prefix in sorted_prefixes_desc:
        if path.startswith(f"{prefix}/"):
            return prefix
    return ""


def _strip_prefix(path: str, prefix: str) -> str:
    """Strip a selected prefix from a path for prefix-table encoding."""

    if not prefix:
        return path
    return path[len(prefix) + 1 :]


def _encode_direct_files(files: tuple[ManifestFile, ...]) -> list[list[object]]:
    """Encode manifest files using direct path entries."""

    encoded: list[list[object]] = []
    for entry in files:
        encoded.append([entry.path, entry.size, entry.sha256, entry.mtime])
    return encoded


def _encode_prefix_files(
    files: tuple[ManifestFile, ...],
    path_prefixes: tuple[str, ...],
) -> list[list[object]]:
    """Encode manifest files using prefix-table path entries."""

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
    """Decode direct-encoding file entries."""

    files: list[ManifestFile] = []
    for entry in files_raw:
        files.append(_decode_direct_file_entry(entry))
    return files


def _decode_prefix_files(
    files_raw: list[object],
    path_prefixes: tuple[str, ...],
) -> list[ManifestFile]:
    """Decode prefix-table file entries."""

    files: list[ManifestFile] = []
    for entry in files_raw:
        files.append(_decode_prefix_file_entry(entry, path_prefixes))
    return files


def _decode_direct_file_entry(entry: object) -> ManifestFile:
    """Decode and validate one direct-encoding manifest file entry."""

    if isinstance(entry, dict):
        raise ValueError("manifest file entry must use array encoding")
    values = require_list(entry, 4, label="manifest file entry")
    path = values[0]
    size = values[1]
    sha256 = values[2]
    mtime = values[3]
    return _build_manifest_file(path=path, size=size, sha256=sha256, mtime=mtime)


def _decode_prefix_file_entry(entry: object, path_prefixes: tuple[str, ...]) -> ManifestFile:
    """Decode and validate one prefix-table manifest file entry."""

    if isinstance(entry, dict):
        raise ValueError("manifest file entry must use array encoding")
    values = require_list(entry, 5, label="manifest file entry")
    prefix_index = values[0]
    suffix = values[1]
    size = values[2]
    sha256 = values[3]
    mtime = values[4]
    prefix_index = require_int(prefix_index, label="manifest file prefix_index")
    if prefix_index < 0 or prefix_index >= len(path_prefixes):
        raise ValueError("manifest file prefix_index out of range")
    suffix = require_non_empty_str(suffix, label="manifest file suffix")
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
    """Validate manifest file fields and build a `ManifestFile`."""

    path = require_non_empty_str(path, label="manifest file path")
    size = require_non_negative_int(size, label="manifest file size")
    sha_bytes = _coerce_sha256(sha256)
    if sha_bytes is None:
        raise ValueError("manifest file hash must be 32 raw bytes")
    if mtime is not None:
        mtime = require_int(mtime, label="manifest file mtime")
    return ManifestFile(
        path=path,
        size=size,
        sha256=sha_bytes,
        mtime=int(mtime) if mtime is not None else None,
    )


def _validate_path_prefixes(value: object) -> tuple[str, ...]:
    """Validate and normalize manifest path prefix table values."""

    raw_prefixes = require_list(value, 1, label="manifest path_prefixes")
    if raw_prefixes[0] != "":
        raise ValueError("manifest path_prefixes must start with empty string")
    normalized_prefixes: list[str] = []
    seen_prefixes: set[str] = set()
    for index, prefix in enumerate(raw_prefixes):
        prefix = require_str(prefix, label="manifest path_prefixes values")
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
    """Normalize and validate a manifest input root label."""

    root = normalize_path(value, label="manifest input_root")
    root = root.strip()
    if not root:
        raise ValueError("manifest input_root must be a non-empty string")
    if "/" in root or "\\" in root:
        raise ValueError("manifest input_root must be a leaf label without path separators")
    return root


def _validate_input_origin_roots(input_origin: str, input_roots: tuple[str, ...]) -> None:
    """Validate `input_origin` and `input_roots` combinations."""

    if input_origin == "file":
        if input_roots:
            raise ValueError("manifest input_roots must be empty when input_origin is file")
        return
    if not input_roots:
        raise ValueError("manifest input_roots must be non-empty for directory or mixed input")
