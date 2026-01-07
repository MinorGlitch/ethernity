#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass

MANIFEST_VERSION = 5


@dataclass(frozen=True)
class ManifestFile:
    path: str
    size: int
    sha256: bytes
    mtime: int | None

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

    def to_cbor(self) -> list[object]:
        prefixes = _build_prefix_table([file.path for file in self.files])
        prefix_index = {prefix: idx for idx, prefix in enumerate(prefixes)}
        prefixes_sorted = sorted(prefixes[1:], key=len, reverse=True)
        files = []
        for file in self.files:
            prefix = _select_prefix(file.path, prefixes_sorted)
            idx = prefix_index[prefix]
            suffix = _strip_prefix(file.path, prefix)
            files.append([idx, suffix, file.size, file.sha256, file.mtime])
        return [
            self.format_version,
            self.created_at,
            self.sealed,
            self.signing_seed,
            prefixes,
            files,
        ]

    def to_dict(self) -> dict[str, object]:
        return {
            "format_version": self.format_version,
            "created_at": self.created_at,
            "sealed": self.sealed,
            "signing_seed": self.signing_seed,
            "files": [file.to_dict() for file in self.files],
        }

    @classmethod
    def from_cbor(cls, data: object) -> "EnvelopeManifest":
        if not isinstance(data, (list, tuple)) or len(data) < 6:
            raise ValueError("manifest must be a list")
        format_version = data[0]
        created_at = data[1]
        sealed = data[2]
        signing_seed = data[3]
        prefixes = data[4]
        files_raw = data[5]
        if not isinstance(format_version, int):
            raise ValueError("manifest format_version must be an int")
        if format_version != MANIFEST_VERSION:
            raise ValueError(f"unsupported manifest version: {format_version}")
        if not isinstance(created_at, (int, float)):
            raise ValueError("manifest created_at must be a number")
        if not isinstance(sealed, bool):
            raise ValueError("manifest sealed must be a boolean")
        if signing_seed is not None and not isinstance(signing_seed, (bytes, bytearray)):
            raise ValueError("manifest signing_seed must be bytes or null")
        if not isinstance(prefixes, list) or not prefixes:
            raise ValueError("manifest prefixes are required")
        if prefixes[0] != "":
            raise ValueError("manifest prefixes must start with empty string")
        for prefix in prefixes:
            if not isinstance(prefix, str):
                raise ValueError("manifest prefix must be a string")
        if not isinstance(files_raw, list) or not files_raw:
            raise ValueError("manifest files are required")
        files: list[ManifestFile] = []
        for entry in files_raw:
            if not isinstance(entry, (list, tuple)) or len(entry) < 5:
                raise ValueError("manifest file entry must be a list")
            prefix_idx, suffix, size, sha256, mtime = entry[:5]
            if not isinstance(prefix_idx, int):
                raise ValueError("manifest file prefix index must be an int")
            if prefix_idx < 0 or prefix_idx >= len(prefixes):
                raise ValueError("manifest file prefix index out of range")
            if not isinstance(suffix, str) or not suffix:
                raise ValueError("manifest file suffix must be a non-empty string")
            prefix = prefixes[prefix_idx]
            if prefix:
                path = f"{prefix}/{suffix}"
            else:
                path = suffix
            if not isinstance(path, str):
                raise ValueError("manifest file path must be a string")
            if not isinstance(size, int) or size < 0:
                raise ValueError("manifest file size must be a non-negative int")
            sha_bytes = _coerce_sha256(sha256)
            if sha_bytes is None:
                raise ValueError("manifest file sha256 must be 32 raw bytes or 64 hex chars")
            if mtime is not None and not isinstance(mtime, int):
                raise ValueError("manifest file mtime must be an int")
            files.append(
                ManifestFile(
                    path=path,
                    size=size,
                    sha256=sha_bytes,
                    mtime=int(mtime) if mtime is not None else None,
                )
            )
        return cls(
            format_version=format_version,
            created_at=float(created_at),
            sealed=sealed,
            signing_seed=bytes(signing_seed) if signing_seed is not None else None,
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
    if isinstance(value, str) and len(value) == 64:
        try:
            return bytes.fromhex(value)
        except ValueError:
            return None
    return None


def _build_prefix_table(paths: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    for path in paths:
        parts = path.split("/")
        prefix = ""
        for idx in range(len(parts) - 1):
            prefix = parts[idx] if idx == 0 else f"{prefix}/{parts[idx]}"
            counts[prefix] = counts.get(prefix, 0) + 1
    prefixes = [""] + sorted((p for p, count in counts.items() if count > 1), key=lambda p: (len(p), p))
    return prefixes


def _select_prefix(path: str, prefixes: list[str]) -> str:
    for prefix in prefixes:
        if path.startswith(f"{prefix}/"):
            return prefix
    return ""


def _strip_prefix(path: str, prefix: str) -> str:
    if not prefix:
        return path
    return path[len(prefix) + 1 :]
