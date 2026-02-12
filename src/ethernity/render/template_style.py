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

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .doc_types import DOC_TYPES


@dataclass(frozen=True)
class HeaderStyle:
    meta_row_gap_mm: float
    stack_gap_mm: float
    divider_thickness_mm: float


@dataclass(frozen=True)
class ContentOffsetStyle:
    divider_gap_extra_mm: float
    doc_types: frozenset[str]


@dataclass(frozen=True)
class TemplateCapabilities:
    repeat_primary_qr_on_shard_continuation: bool = False
    advanced_fallback_layout: bool = False
    wide_recovery_fallback_lines: bool = False
    extra_main_first_page_qr_slot: bool = False
    uniform_main_qr_capacity: bool = False
    main_qr_grid_size_mm: float | None = None
    main_qr_grid_max_cols: int | None = None
    shard_first_page_bonus_lines: int = 0
    signing_key_shard_first_page_bonus_lines: int = 0


@dataclass(frozen=True)
class TemplateStyle:
    name: str
    header: HeaderStyle
    content_offset: ContentOffsetStyle
    capabilities: TemplateCapabilities


DEFAULT_TEMPLATE_STYLE = TemplateStyle(
    name="ledger",
    header=HeaderStyle(meta_row_gap_mm=1.2, stack_gap_mm=0.0, divider_thickness_mm=0.6),
    content_offset=ContentOffsetStyle(divider_gap_extra_mm=0.0, doc_types=frozenset()),
    capabilities=TemplateCapabilities(),
)


def load_template_style(template_path: str | Path) -> TemplateStyle:
    template_dir = Path(template_path).parent.resolve()
    return _load_style_for_dir(template_dir)


@lru_cache(maxsize=32)
def _load_style_for_dir(template_dir: Path) -> TemplateStyle:
    style_path = template_dir / "style.json"
    if not style_path.is_file():
        return DEFAULT_TEMPLATE_STYLE

    try:
        raw = style_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"unable to read template style file: {style_path}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in template style file: {style_path}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"template style must be a JSON object: {style_path}")
    _reject_unknown_keys(
        data,
        allowed_keys=frozenset({"name", "header", "content_offset", "capabilities"}),
        section="template style",
        path=style_path,
    )

    name = _require_str(data, "name", path=style_path)
    header_data = _require_dict(data, "header", path=style_path)
    _reject_unknown_keys(
        header_data,
        allowed_keys=frozenset({"meta_row_gap_mm", "stack_gap_mm", "divider_thickness_mm"}),
        section="header",
        path=style_path,
    )
    header = HeaderStyle(
        meta_row_gap_mm=_require_number(header_data, "meta_row_gap_mm", path=style_path),
        stack_gap_mm=_require_number(header_data, "stack_gap_mm", path=style_path),
        divider_thickness_mm=_require_number(header_data, "divider_thickness_mm", path=style_path),
    )

    offset_data = _require_dict(data, "content_offset", path=style_path)
    _reject_unknown_keys(
        offset_data,
        allowed_keys=frozenset({"divider_gap_extra_mm", "doc_types"}),
        section="content_offset",
        path=style_path,
    )
    divider_gap_extra_mm = _require_number(offset_data, "divider_gap_extra_mm", path=style_path)
    doc_types_list = _require_list_of_str(offset_data, "doc_types", path=style_path)
    normalized_doc_types: list[str] = []
    for doc_type in doc_types_list:
        normalized = doc_type.strip().lower()
        if normalized not in DOC_TYPES:
            raise ValueError(f"unknown doc type '{doc_type}' in {style_path}")
        normalized_doc_types.append(normalized)
    capabilities = _parse_capabilities(data.get("capabilities"), style_name=name, path=style_path)

    return TemplateStyle(
        name=name,
        header=header,
        content_offset=ContentOffsetStyle(
            divider_gap_extra_mm=divider_gap_extra_mm,
            doc_types=frozenset(normalized_doc_types),
        ),
        capabilities=capabilities,
    )


def _parse_capabilities(value: object, *, style_name: str, path: Path) -> TemplateCapabilities:
    if value is None:
        return TemplateCapabilities(
            extra_main_first_page_qr_slot=style_name.strip().lower() == "sentinel"
        )
    if not isinstance(value, dict):
        raise ValueError(f"invalid 'capabilities' object in {path}")
    _reject_unknown_keys(
        value,
        allowed_keys=frozenset(
            {
                "repeat_primary_qr_on_shard_continuation",
                "advanced_fallback_layout",
                "wide_recovery_fallback_lines",
                "extra_main_first_page_qr_slot",
                "uniform_main_qr_capacity",
                "main_qr_grid_size_mm",
                "main_qr_grid_max_cols",
                "shard_first_page_bonus_lines",
                "signing_key_shard_first_page_bonus_lines",
            }
        ),
        section="capabilities",
        path=path,
    )
    normalized_style_name = style_name.strip().lower()
    return TemplateCapabilities(
        repeat_primary_qr_on_shard_continuation=_optional_bool(
            value,
            "repeat_primary_qr_on_shard_continuation",
            default=False,
            path=path,
        ),
        advanced_fallback_layout=_optional_bool(
            value,
            "advanced_fallback_layout",
            default=False,
            path=path,
        ),
        wide_recovery_fallback_lines=_optional_bool(
            value,
            "wide_recovery_fallback_lines",
            default=False,
            path=path,
        ),
        extra_main_first_page_qr_slot=_optional_bool(
            value,
            "extra_main_first_page_qr_slot",
            default=normalized_style_name == "sentinel",
            path=path,
        ),
        uniform_main_qr_capacity=_optional_bool(
            value,
            "uniform_main_qr_capacity",
            default=False,
            path=path,
        ),
        main_qr_grid_size_mm=_optional_positive_number(
            value,
            "main_qr_grid_size_mm",
            default=None,
            path=path,
        ),
        main_qr_grid_max_cols=_optional_positive_int(
            value,
            "main_qr_grid_max_cols",
            default=None,
            path=path,
        ),
        shard_first_page_bonus_lines=_optional_non_negative_int(
            value,
            "shard_first_page_bonus_lines",
            default=0,
            path=path,
        ),
        signing_key_shard_first_page_bonus_lines=_optional_non_negative_int(
            value,
            "signing_key_shard_first_page_bonus_lines",
            default=0,
            path=path,
        ),
    )


def _require_dict(data: dict[str, object], key: str, *, path: Path) -> dict[str, object]:
    value = data.get(key)
    if isinstance(value, dict):
        return value
    raise ValueError(f"missing or invalid '{key}' object in {path}")


def _require_str(data: dict[str, object], key: str, *, path: Path) -> str:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value
    raise ValueError(f"missing or invalid '{key}' string in {path}")


def _require_number(data: dict[str, object], key: str, *, path: Path) -> float:
    value = data.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    raise ValueError(f"missing or invalid '{key}' number in {path}")


def _require_list_of_str(data: dict[str, object], key: str, *, path: Path) -> list[str]:
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"'{key}' must be a list in {path}")
    for idx, entry in enumerate(value):
        if not isinstance(entry, str):
            raise ValueError(f"'{key}[{idx}]' must be a string in {path}")
    return [str(entry) for entry in value]


def _optional_bool(
    data: dict[str, object],
    key: str,
    *,
    default: bool,
    path: Path,
) -> bool:
    if key not in data:
        return default
    value = data.get(key)
    if isinstance(value, bool):
        return value
    raise ValueError(f"missing or invalid '{key}' boolean in {path}")


def _optional_non_negative_int(
    data: dict[str, object],
    key: str,
    *,
    default: int,
    path: Path,
) -> int:
    if key not in data:
        return default
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"missing or invalid '{key}' non-negative integer in {path}")
    return value


def _optional_positive_int(
    data: dict[str, object],
    key: str,
    *,
    default: int | None,
    path: Path,
) -> int | None:
    if key not in data:
        return default
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"missing or invalid '{key}' positive integer in {path}")
    return value


def _optional_positive_number(
    data: dict[str, object],
    key: str,
    *,
    default: float | None,
    path: Path,
) -> float | None:
    if key not in data:
        return default
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"missing or invalid '{key}' positive number in {path}")
    return float(value)


def _reject_unknown_keys(
    data: dict[str, object],
    *,
    allowed_keys: frozenset[str],
    section: str,
    path: Path,
) -> None:
    unknown = sorted(key for key in data if key not in allowed_keys)
    if unknown:
        unknown_text = ", ".join(unknown)
        raise ValueError(f"unknown key(s) in {section} ({unknown_text}) in {path}")


__all__ = [
    "DEFAULT_TEMPLATE_STYLE",
    "TemplateCapabilities",
    "TemplateStyle",
    "load_template_style",
]
