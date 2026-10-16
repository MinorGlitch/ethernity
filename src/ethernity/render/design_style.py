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

"""Load validated template settings and document capabilities from style.json."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, ValidationError

from ethernity.config.paths import DESIGNS_RESOURCE_ROOT
from ethernity.page_sizes import PaperSize
from ethernity.render.designs import resolve_design_directory
from ethernity.render.template import DocumentArtwork, LayoutElement, Template, TemplateModel


class LayoutStyle(TemplateModel):
    """Reuse a design's type and color, with an optional physical font size."""

    source: str
    size_pt: float | None = Field(default=None, ge=6)


class CompactLayout(TemplateModel):
    source: str = Field(pattern=r"^[a-zA-Z0-9_-]+\.json$")
    below_width_mm: float = Field(gt=0)
    below_height_mm: float = Field(gt=0)
    styles: dict[str, LayoutStyle]
    components: dict[str, tuple[LayoutElement, ...]] = Field(default_factory=dict)
    documents: dict[str, DocumentArtwork] = Field(default_factory=dict)

    def applies_to(self, page: PaperSize) -> bool:
        return page.width_mm < self.below_width_mm or page.height_mm < self.below_height_mm


class DesignCapabilities(TemplateModel):
    recovery_first_page_single_section: bool = False
    recovery_kit_index_document: bool = False


class DesignStyle(TemplateModel):
    name: str = Field(min_length=1, pattern=r"\S")
    component_sources: tuple[Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]+\.json$")], ...] = ()
    capabilities: DesignCapabilities = Field(default_factory=DesignCapabilities)
    template: Template
    compact_layout: CompactLayout | None = None


def load_design_style(design: str | Path) -> DesignStyle:
    """Load a built-in name, template directory, or design definition path."""
    return _load_style_for_dir(resolve_design_directory(design))


def load_page_template(design: str | Path, page: PaperSize) -> Template:
    """Select composition once; all document builders use the same resolved template."""
    directory = resolve_design_directory(design)
    style = _load_style_for_dir(directory)
    if style.compact_layout is not None and style.compact_layout.applies_to(page):
        return _load_compact_template(directory)
    return style.template


@lru_cache(maxsize=32)
def _load_compact_template(directory: Path) -> Template:
    style = _load_style_for_dir(directory)
    layout = style.compact_layout
    assert layout is not None
    path = directory / layout.source
    if not path.is_file():
        path = DESIGNS_RESOURCE_ROOT / "_shared" / layout.source
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("layout must be an object")
        base_styles = {name: value.model_dump() for name, value in style.template.styles.items()}
        styles = dict(base_styles)
        for name, override in layout.styles.items():
            if override.source not in base_styles:
                raise ValueError(f"unknown style source: {override.source}")
            styles[name] = {**base_styles[override.source], "char_spacing_pt": 0}
            if override.size_pt is not None:
                styles[name]["size_pt"] = override.size_pt
        data["styles"] = {**data.get("styles", {}), **styles}
        data["components"] = {
            **{
                name: [e.model_dump() for e in elements]
                for name, elements in style.template.components.items()
            },
            **data.get("components", {}),
            **{
                name: [e.model_dump() for e in elements]
                for name, elements in layout.components.items()
            },
        }
        data["documents"] = {
            **data.get("documents", {}),
            **{name: doc.model_dump() for name, doc in layout.documents.items()},
        }
        return Template.model_validate_json(json.dumps(data))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"{path}: invalid compact layout: {exc}") from exc


@lru_cache(maxsize=32)
def _load_style_for_dir(design_dir: Path) -> DesignStyle:
    path = design_dir / "style.json"
    if not path.is_file():
        raise ValueError(f"missing design style file: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"unable to read design style file: {path}") from exc
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "component_sources" in data:
            imported = _library_components(design_dir, data["component_sources"])
            data["template"]["components"] = imported | data["template"].get("components", {})
        return DesignStyle.model_validate_json(json.dumps(data))
    except ValidationError as exc:
        error = exc.errors()[0]
        field = ".".join(str(part) for part in error["loc"]) or "style"
        raise ValueError(f"{path}: {field}: {error['msg']}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: Invalid JSON: {exc}") from exc
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"{path}: invalid component_sources: {exc}") from exc


class ComponentLibrary(TemplateModel):
    """Reusable artwork; the importing design supplies its styles and decorations."""

    components: dict[str, tuple[LayoutElement, ...]]


def _library_components(design_dir: Path, sources: object) -> dict[str, list[dict[str, object]]]:
    if not isinstance(sources, list):
        raise ValueError("component_sources must be a list of JSON filenames")
    imported = {}
    for source in sources:
        if not isinstance(source, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+\.json", source):
            raise ValueError("component_sources must contain JSON filenames")
        path = design_dir / source
        if not path.is_file():
            path = DESIGNS_RESOURCE_ROOT / "_shared" / source
        library = ComponentLibrary.model_validate_json(path.read_text(encoding="utf-8"))
        imported.update(
            {
                name: [element.model_dump() for element in elements]
                for name, elements in library.components.items()
            }
        )
    return imported


__all__ = ["DesignCapabilities", "DesignStyle", "load_design_style", "load_page_template"]
