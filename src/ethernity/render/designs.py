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

"""Internal direct-render design definition loading."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from ethernity.config.paths import DESIGNS_RESOURCE_ROOT
from ethernity.page_sizes import PAPER_SIZES, PaperSize, PaperSizeName, resolve_paper_size
from ethernity.render.doc_types import DOC_TYPES

DESIGN_DEFINITION_FILENAME = "design.json"
DESIGN_STYLE_FILENAME = "style.json"
_DESIGN_DEFINITION_KEYS = frozenset(
    {"schema_version", "name", "style", "documents", "page_support"}
)


@dataclass(frozen=True)
class PageGeometrySupport:
    """Minimum portrait dimensions supported for one design/document renderer."""

    minimum_width_mm: float
    minimum_height_mm: float

    def __post_init__(self) -> None:
        for field_name, value in (
            ("minimum_width_mm", self.minimum_width_mm),
            ("minimum_height_mm", self.minimum_height_mm),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{field_name} must be finite and positive")

    def supports(self, page_size: PaperSize) -> bool:
        """Return whether the page meets this renderer's minimum page dimensions."""

        return (
            page_size.width_mm >= self.minimum_width_mm
            and page_size.height_mm >= self.minimum_height_mm
        )

    def require(self, page_size: PaperSize, *, design_name: str, doc_type: str) -> None:
        """Reject page geometry outside the supported page dimensions."""

        if self.supports(page_size):
            return
        raise ValueError(
            "page size is outside the supported dimensions: "
            f"design={design_name!r}, doc_type={doc_type!r}, "
            f"page={page_size.name} ({page_size.width_mm:.3f}x"
            f"{page_size.height_mm:.3f} mm), minimum="
            f"{self.minimum_width_mm:.3f}x{self.minimum_height_mm:.3f} mm"
        )


@dataclass(frozen=True)
class DesignDefinition:
    """Parsed direct-render design definition."""

    name: str
    directory: Path
    style_path: Path
    documents: frozenset[str]
    page_support: Mapping[str, PageGeometrySupport]

    def supports_doc_type(self, doc_type: str) -> bool:
        """Return whether this design declares support for a normalized document type."""

        return doc_type.strip().lower() in self.documents

    def page_support_for(self, doc_type: str) -> PageGeometrySupport:
        """Return the minimum page dimensions for a supported document type."""

        normalized = doc_type.strip().lower()
        support = self.page_support.get(normalized)
        if support is None:
            raise ValueError(f"design {self.name!r} has no page support entry for {doc_type!r}")
        return support

    def supports_page_size(self, doc_type: str, page_size: PaperSize) -> bool:
        """Return whether this design/document advertises the physical page size."""

        return self.page_support_for(doc_type).supports(page_size)

    def require_page_size(self, doc_type: str, page_size: PaperSize) -> None:
        """Fail before rendering when page geometry is outside the supported dimensions."""

        normalized = doc_type.strip().lower()
        self.page_support_for(normalized).require(
            page_size,
            design_name=self.name,
            doc_type=normalized,
        )


class _PageGeometrySupportData(BaseModel):
    """Parsed physical page limits for one document type."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum_width_mm: float
    minimum_height_mm: float

    @field_validator("minimum_width_mm", "minimum_height_mm", mode="before")
    @classmethod
    def _require_positive_finite_number(cls, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("must be a number")
        resolved = float(value)
        if not math.isfinite(resolved) or resolved <= 0:
            raise ValueError("must be finite and positive")
        return resolved

    def to_public(self) -> PageGeometrySupport:
        return PageGeometrySupport(
            minimum_width_mm=self.minimum_width_mm,
            minimum_height_mm=self.minimum_height_mm,
        )


class _DesignDefinitionData(BaseModel):
    """Parsed and validated `design.json` content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int
    name: str
    style: str
    documents: tuple[str, ...]
    page_support: dict[str, _PageGeometrySupportData]

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

    @field_validator("page_support", mode="before")
    @classmethod
    def _require_page_support_object(cls, value: object) -> object:
        if not isinstance(value, dict):
            raise ValueError("must be an object")
        return value


def list_design_definitions(root: Path = DESIGNS_RESOURCE_ROOT) -> dict[str, DesignDefinition]:
    """List packaged direct-render design definitions by design name."""

    if not root.exists():
        return {}

    definitions: dict[str, DesignDefinition] = {}
    for entry in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if entry.name.startswith(".") or not entry.is_dir() or entry.name == "_shared":
            continue
        definition_path = entry / DESIGN_DEFINITION_FILENAME
        if not definition_path.is_file():
            continue
        definition = load_design_definition(entry)
        definitions[definition.name] = definition
    return definitions


def load_design_definition_by_name(name: str) -> DesignDefinition:
    """Load a packaged direct-render design definition by design name."""

    normalized = _normalize_design_name(name)
    definition = list_design_definitions().get(normalized)
    if definition is not None:
        return definition
    raise ValueError(f"unknown renderer design: {name}")


def design_definition_path(name: str) -> Path:
    """Return the packaged definition path for a design name."""

    return load_design_definition_by_name(name).directory / DESIGN_DEFINITION_FILENAME


def supported_paper_size_names(
    design_name: str,
    *,
    doc_types: frozenset[str] | None = None,
) -> tuple[PaperSizeName, ...]:
    """Return registered sizes supported for every selected document renderer."""

    definition = load_design_definition_by_name(design_name)
    selected_doc_types = definition.documents if doc_types is None else doc_types
    if not selected_doc_types:
        raise ValueError("doc_types must be non-empty")
    normalized_doc_types = frozenset(doc_type.strip().lower() for doc_type in selected_doc_types)
    unknown = normalized_doc_types - definition.documents
    if unknown:
        raise ValueError(
            f"design {definition.name!r} does not advertise document type(s): "
            f"{', '.join(sorted(unknown))}"
        )
    return tuple(
        paper.name
        for paper in PAPER_SIZES.values()
        if all(definition.supports_page_size(doc_type, paper) for doc_type in normalized_doc_types)
    )


def require_supported_paper_size(
    design_name: str,
    paper_size: str,
    *,
    doc_types: frozenset[str] | None = None,
) -> PaperSize:
    """Resolve and preflight a registered size for a design/workflow document set."""

    definition = load_design_definition_by_name(design_name)
    resolved = resolve_paper_size(paper_size)
    selected_doc_types = definition.documents if doc_types is None else doc_types
    if not selected_doc_types:
        raise ValueError("doc_types must be non-empty")
    for doc_type in selected_doc_types:
        definition.require_page_size(doc_type, resolved)
    return resolved


def resolve_design_directory(value: str | Path) -> Path:
    """Resolve a design name, design directory, or design definition path."""

    if isinstance(value, str):
        stripped = value.strip()
        if stripped and "/" not in stripped and "\\" not in stripped and "." not in stripped:
            return load_design_definition_by_name(stripped).directory
        candidate = Path(stripped)
    else:
        candidate = value

    path = candidate.expanduser()
    if path.is_dir():
        return path.resolve()
    if path.name == DESIGN_DEFINITION_FILENAME:
        return path.parent.resolve()
    raise ValueError(
        "renderer design must be a supported style name, design directory, "
        f"or {DESIGN_DEFINITION_FILENAME} path: {value}"
    )


def load_design_definition(path: str | Path) -> DesignDefinition:
    """Load a direct-render design definition from a directory or definition path."""

    directory = resolve_design_directory(path)
    return _load_design_definition_for_dir(directory)


@lru_cache(maxsize=32)
def _load_design_definition_for_dir(directory: Path) -> DesignDefinition:
    definition_path = directory / DESIGN_DEFINITION_FILENAME
    if not definition_path.is_file():
        raise ValueError(f"missing design definition: {definition_path}")

    try:
        raw = definition_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"unable to read design definition: {definition_path}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in design definition: {definition_path}") from exc

    definition_data = _load_design_definition_data(data, path=definition_path)
    if definition_data.schema_version != 2:
        raise ValueError(f"unsupported design definition schema_version in {definition_path}")

    documents = frozenset(_normalize_doc_types(definition_data.documents, path=definition_path))
    if not documents:
        raise ValueError(f"design definition documents cannot be empty: {definition_path}")
    page_support = _normalize_page_support(
        definition_data.page_support,
        documents=documents,
        path=definition_path,
    )

    style_path = (directory / definition_data.style).resolve()
    if not style_path.is_file():
        raise ValueError(f"missing design style file: {style_path}")

    return DesignDefinition(
        name=_normalize_design_name(definition_data.name),
        directory=directory,
        style_path=style_path,
        documents=documents,
        page_support=page_support,
    )


def _load_design_definition_data(data: object, *, path: Path) -> _DesignDefinitionData:
    if not isinstance(data, dict):
        raise ValueError(f"design definition must be a JSON object: {path}")
    _reject_unknown_keys(
        data,
        allowed_keys=_DESIGN_DEFINITION_KEYS,
        section="design definition",
        path=path,
    )
    try:
        return _DesignDefinitionData.model_validate(data)
    except ValidationError as exc:
        raise ValueError(_design_definition_validation_message(exc, path=path)) from exc


def _design_definition_validation_message(exc: ValidationError, *, path: Path) -> str:
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
    if loc and loc[0] == "page_support":
        return f"missing or invalid 'page_support' object in {path}"
    return f"unsupported design definition schema_version in {path}"


def _normalize_doc_types(values: tuple[str, ...], *, path: Path) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        doc_type = value.strip().lower()
        if doc_type not in DOC_TYPES:
            raise ValueError(f"unknown document type '{value}' in {path}")
        normalized.append(doc_type)
    return tuple(normalized)


def _normalize_page_support(
    values: dict[str, _PageGeometrySupportData],
    *,
    documents: frozenset[str],
    path: Path,
) -> Mapping[str, PageGeometrySupport]:
    normalized: dict[str, PageGeometrySupport] = {}
    for raw_doc_type, support in values.items():
        doc_type = raw_doc_type.strip().lower()
        if doc_type not in DOC_TYPES:
            raise ValueError(f"unknown page_support document type '{raw_doc_type}' in {path}")
        if doc_type in normalized:
            raise ValueError(f"duplicate page_support document type '{raw_doc_type}' in {path}")
        normalized[doc_type] = support.to_public()

    support_doc_types = frozenset(normalized)
    if support_doc_types != documents:
        missing = sorted(documents - support_doc_types)
        extra = sorted(support_doc_types - documents)
        details: list[str] = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if extra:
            details.append(f"extra={','.join(extra)}")
        raise ValueError(
            f"page_support must match advertised documents in {path}: {'; '.join(details)}"
        )
    return MappingProxyType(normalized)


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
    "DESIGN_DEFINITION_FILENAME",
    "DESIGN_STYLE_FILENAME",
    "DesignDefinition",
    "PageGeometrySupport",
    "design_definition_path",
    "list_design_definitions",
    "load_design_definition",
    "load_design_definition_by_name",
    "require_supported_paper_size",
    "resolve_design_directory",
    "supported_paper_size_names",
]
