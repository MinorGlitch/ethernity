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

"""Internal direct-render design manifest loading."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from ethernity.config.paths import TEMPLATES_RESOURCE_ROOT
from ethernity.render.doc_types import DOC_TYPES

DESIGN_MANIFEST_FILENAME = "design.json"
DESIGN_STYLE_FILENAME = "style.json"
_DESIGN_MANIFEST_KEYS = frozenset({"schema_version", "name", "style", "documents"})


@dataclass(frozen=True)
class DesignManifest:
    """Parsed direct-render design manifest."""

    name: str
    directory: Path
    style_path: Path
    documents: frozenset[str]

    def supports_doc_type(self, doc_type: str) -> bool:
        """Return whether this design declares support for a normalized document type."""

        return doc_type.strip().lower() in self.documents


class _DesignManifestData(BaseModel):
    """Pydantic boundary model for raw `design.json` content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int
    name: str
    style: str
    documents: tuple[str, ...]

    @field_validator("name", "style", mode="before")
    @classmethod
    def _require_non_empty_string(cls, value: object) -> str:
        if isinstance(value, str) and value.strip():
            return value
        raise ValueError("must be a non-empty string")

    @field_validator("documents", mode="before")
    @classmethod
    def _require_document_list(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, list):
            raise ValueError("must be a list")
        values: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("items must be non-empty strings")
            values.append(item)
        return tuple(values)


def list_design_manifests(root: Path = TEMPLATES_RESOURCE_ROOT) -> dict[str, DesignManifest]:
    """List packaged direct-render design manifests by design name."""

    if not root.exists():
        return {}

    manifests: dict[str, DesignManifest] = {}
    for entry in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if entry.name.startswith(".") or not entry.is_dir() or entry.name == "_shared":
            continue
        manifest_path = entry / DESIGN_MANIFEST_FILENAME
        if not manifest_path.is_file():
            continue
        manifest = load_design_manifest(entry)
        manifests[manifest.name] = manifest
    return manifests


def load_design_manifest_by_name(name: str) -> DesignManifest:
    """Load a packaged direct-render design manifest by design name."""

    normalized = _normalize_design_name(name)
    manifest = list_design_manifests().get(normalized)
    if manifest is not None:
        return manifest
    raise ValueError(f"unknown renderer design: {name}")


def design_manifest_path(name: str) -> Path:
    """Return the packaged manifest path for a design name."""

    return load_design_manifest_by_name(name).directory / DESIGN_MANIFEST_FILENAME


def resolve_design_directory(value: str | Path) -> Path:
    """Resolve a design name, design directory, or design manifest path."""

    if isinstance(value, str):
        stripped = value.strip()
        if stripped and "/" not in stripped and "\\" not in stripped and "." not in stripped:
            return load_design_manifest_by_name(stripped).directory
        candidate = Path(stripped)
    else:
        candidate = value

    path = candidate.expanduser()
    if path.is_dir():
        return path.resolve()
    if path.name == DESIGN_MANIFEST_FILENAME:
        return path.parent.resolve()
    raise ValueError(
        "renderer design must be a supported style name, design directory, "
        f"or {DESIGN_MANIFEST_FILENAME} path: {value}"
    )


def load_design_manifest(path: str | Path) -> DesignManifest:
    """Load a direct-render design manifest from a directory or manifest path."""

    directory = resolve_design_directory(path)
    return _load_design_manifest_for_dir(directory)


@lru_cache(maxsize=32)
def _load_design_manifest_for_dir(directory: Path) -> DesignManifest:
    manifest_path = directory / DESIGN_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ValueError(f"missing design manifest: {manifest_path}")

    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"unable to read design manifest: {manifest_path}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in design manifest: {manifest_path}") from exc

    manifest_data = _load_design_manifest_data(data, path=manifest_path)
    if manifest_data.schema_version != 1:
        raise ValueError(f"unsupported design manifest schema_version in {manifest_path}")

    documents = frozenset(_normalize_doc_types(manifest_data.documents, path=manifest_path))
    if not documents:
        raise ValueError(f"design manifest documents cannot be empty: {manifest_path}")

    style_path = (directory / manifest_data.style).resolve()
    if not style_path.is_file():
        raise ValueError(f"missing design style file: {style_path}")

    return DesignManifest(
        name=_normalize_design_name(manifest_data.name),
        directory=directory,
        style_path=style_path,
        documents=documents,
    )


def _load_design_manifest_data(data: object, *, path: Path) -> _DesignManifestData:
    if not isinstance(data, dict):
        raise ValueError(f"design manifest must be a JSON object: {path}")
    _reject_unknown_keys(
        data,
        allowed_keys=_DESIGN_MANIFEST_KEYS,
        section="design manifest",
        path=path,
    )
    try:
        return _DesignManifestData.model_validate(data)
    except ValidationError as exc:
        raise ValueError(_design_manifest_validation_message(exc, path=path)) from exc


def _design_manifest_validation_message(exc: ValidationError, *, path: Path) -> str:
    error = exc.errors()[0]
    context_error = error.get("ctx", {}).get("error")
    if isinstance(context_error, ValueError):
        loc = tuple(error.get("loc", ()))
        if loc and loc[0] in {"name", "style"}:
            return f"missing or invalid '{loc[0]}' string in {path}"
        if loc and loc[0] == "documents":
            message = str(context_error)
            if message == "items must be non-empty strings":
                return f"invalid 'documents' string item in {path}"
            return f"missing or invalid 'documents' list in {path}"

    loc = tuple(error.get("loc", ()))
    if loc and loc[0] in {"name", "style"}:
        return f"missing or invalid '{loc[0]}' string in {path}"
    if loc and loc[0] == "documents":
        return f"missing or invalid 'documents' list in {path}"
    return f"unsupported design manifest schema_version in {path}"


def _normalize_doc_types(values: tuple[str, ...], *, path: Path) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        doc_type = value.strip().lower()
        if doc_type not in DOC_TYPES:
            raise ValueError(f"unknown document type '{value}' in {path}")
        normalized.append(doc_type)
    return tuple(normalized)


def _normalize_design_name(value: str) -> str:
    name = value.strip().lower()
    if not name:
        raise ValueError("renderer design cannot be empty")
    return name


def _reject_unknown_keys(
    data: dict[str, object],
    *,
    allowed_keys: frozenset[str],
    section: str,
    path: Path,
) -> None:
    unknown = sorted(set(data) - allowed_keys)
    if unknown:
        unknown_text = ", ".join(unknown)
        raise ValueError(f"unknown {section} key(s) in {path}: {unknown_text}")


__all__ = [
    "DESIGN_MANIFEST_FILENAME",
    "DESIGN_STYLE_FILENAME",
    "DesignManifest",
    "design_manifest_path",
    "list_design_manifests",
    "load_design_manifest",
    "load_design_manifest_by_name",
    "resolve_design_directory",
]
