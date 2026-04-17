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

"""Compatibility facade for extend validation helpers."""

from __future__ import annotations

from ethernity.cli.features.extend.fallback_validation import (
    extract_pdf_fallback_lines,
    extract_pdf_fallback_lines_from_pdf_impl as _extract_pdf_fallback_lines_from_pdf,
    fallback_extraction_score,
    is_qr_absent_scan_error,
    normalize_pdf_fallback_payload_fragment,
    normalized_fallback_payload_text,
    parse_pdf_fallback_payload_line,
    validate_fallback_recovery_document,
    validate_pdf_fallback_main_section,
)
from ethernity.cli.features.extend.main_carrier_validation import (
    expected_recovery_kit_index_component_ids,
    validate_single_main_carrier,
    validate_staged_main_carriers,
    validate_staged_recovery_kit_index_document,
)
from ethernity.cli.features.extend.shard_validation import (
    validate_rendered_shard_carrier,
    validate_staged_shard_carriers,
)

__all__ = [
    "_extract_pdf_fallback_lines_from_pdf",
    "expected_recovery_kit_index_component_ids",
    "extract_pdf_fallback_lines",
    "fallback_extraction_score",
    "is_qr_absent_scan_error",
    "normalize_pdf_fallback_payload_fragment",
    "normalized_fallback_payload_text",
    "parse_pdf_fallback_payload_line",
    "validate_fallback_recovery_document",
    "validate_pdf_fallback_main_section",
    "validate_rendered_shard_carrier",
    "validate_single_main_carrier",
    "validate_staged_main_carriers",
    "validate_staged_recovery_kit_index_document",
    "validate_staged_shard_carriers",
]
