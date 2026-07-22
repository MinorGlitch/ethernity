"""Measured fallback-text encoding, reflow, pagination, and proofs."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ethernity.core.bounds import MAX_FALLBACK_LINES
from ethernity.encoding.framing import Frame, encode_frame
from ethernity.encoding.zbase32 import ZBASE32_ALPHABET, encode_zbase32
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.text_measure import measured_grouped_line_length
from ethernity.render.direct_pdf.types import PdfRect, TextStyle
from ethernity.render.fallback_text import fallback_section_title, format_zbase32_lines
from ethernity.render.proofs import frame_digest
from ethernity.render.types import (
    FallbackSection,
    RenderFallbackProof,
    RenderInputs,
)


@dataclass(frozen=True)
class FallbackSectionLines:
    """Encoded fallback lines for one source frame."""

    section_index: int
    title: str | None
    lines: tuple[str, ...]
    frame: Frame


@dataclass(frozen=True)
class FallbackTitleEntry:
    """One fallback section title entry."""

    section_index: int
    title: str


@dataclass(frozen=True)
class FallbackLineEntry:
    """One numbered fallback line entry."""

    section_index: int
    line_number: int
    text: str


FallbackEntry = FallbackTitleEntry | FallbackLineEntry


@dataclass(frozen=True)
class FallbackPageEntry:
    """One fallback entry placed on a page row."""

    entry: FallbackEntry
    row_index: int
    display_line_number: int | None


@dataclass(frozen=True)
class FallbackPage:
    """One page of fallback entries."""

    page_number: int
    entries: tuple[FallbackPageEntry, ...]


@dataclass(frozen=True)
class ResponsiveFallbackSpec:
    """Geometry and typography used to measure recovery fallback rows."""

    group_size: int
    row_height_mm: float
    body_style: TextStyle
    number_style: TextStyle
    content_left_inset_mm: float
    content_right_inset_mm: float
    vertical_reserved_mm: float
    number_gap_mm: float
    number_minimum_width_mm: float = 0.0
    number_padding_mm: float = 0.0
    inline_number: bool = False
    safety_mm: float = 0.2


@dataclass(frozen=True)
class ResponsiveFallbackPageProfile:
    """One page class's measured fallback area and row typography."""

    area: PdfRect
    spec: ResponsiveFallbackSpec


@dataclass(frozen=True)
class ResponsiveFallbackPagination:
    """Fallback pages reflowed with independent first/continuation profiles."""

    sections: tuple[FallbackSectionLines, ...]
    pages: tuple[FallbackPage, ...]
    first_line_length: int
    continuation_line_length: int
    first_payload_width_mm: float
    continuation_payload_width_mm: float
    first_capacity: int
    continuation_capacity: int


@dataclass(frozen=True)
class _ResponsiveFallbackProfileMetrics:
    capacity: int
    payload_width_mm: float
    line_length: int


@dataclass(frozen=True)
class _EncodedFallbackSection:
    frame: Frame
    title: str | None
    encoded: str


def fallback_sections(
    sections: Sequence[FallbackSection],
    *,
    group_size: int,
    line_length: int,
) -> tuple[FallbackSectionLines, ...]:
    """Encode fallback sections into grouped z-base-32 text lines."""

    resolved: list[FallbackSectionLines] = []
    for index, section in enumerate(sections):
        encoded = encode_zbase32(encode_frame(section.frame))
        lines = format_zbase32_lines(
            encoded,
            group_size=group_size,
            line_length=line_length,
            line_count=MAX_FALLBACK_LINES,
        )
        resolved.append(
            FallbackSectionLines(
                section_index=index,
                title=fallback_section_title(section.label),
                lines=tuple(lines),
                frame=section.frame,
            )
        )
    return tuple(resolved)


def fallback_entries(sections: Sequence[FallbackSectionLines]) -> tuple[FallbackEntry, ...]:
    """Flatten fallback section titles and lines into page entries."""

    entries: list[FallbackEntry] = []
    for section in sections:
        if section.title:
            entries.append(
                FallbackTitleEntry(section_index=section.section_index, title=section.title)
            )
        for line_number, line in enumerate(section.lines, start=1):
            entries.append(
                FallbackLineEntry(
                    section_index=section.section_index,
                    line_number=line_number,
                    text=line,
                )
            )
    return tuple(entries)


def paginate_fallback_entries(
    entries: Sequence[FallbackEntry],
    *,
    capacity: int,
    continuation_capacity: int | None = None,
) -> tuple[FallbackPage, ...]:
    """Paginate preformatted entries with distinct first/continuation capacities."""

    if not entries:
        raise ValueError("direct renderer has no fallback entries to render")
    if capacity <= 0:
        raise ValueError("fallback first page must fit at least one entry")
    resolved_continuation_capacity = (
        capacity if continuation_capacity is None else continuation_capacity
    )
    if resolved_continuation_capacity <= 0:
        raise ValueError("fallback continuation page must fit at least one entry")
    pages: list[FallbackPage] = []
    remaining = tuple(entries)
    page_number = 1
    while remaining:
        page_capacity = capacity if page_number == 1 else resolved_continuation_capacity
        consumed = min(page_capacity, len(remaining))
        if (
            consumed < len(remaining)
            and isinstance(remaining[consumed - 1], FallbackTitleEntry)
            and isinstance(remaining[consumed], FallbackLineEntry)
        ):
            consumed -= 1
        if consumed <= 0:
            raise ValueError(
                "fallback page capacity cannot keep a section title with its first data line"
            )
        page_entries: list[FallbackPageEntry] = []
        display_line_number = 0
        for row_index, entry in enumerate(remaining[:consumed]):
            if isinstance(entry, FallbackTitleEntry):
                display_line_number = 0
                displayed = None
            else:
                display_line_number += 1
                displayed = display_line_number
            page_entries.append(
                FallbackPageEntry(
                    entry=entry,
                    row_index=row_index,
                    display_line_number=displayed,
                )
            )
        pages.append(FallbackPage(page_number=page_number, entries=tuple(page_entries)))
        remaining = remaining[consumed:]
        page_number += 1
    return tuple(pages)


def fallback_capacity(
    area: PdfRect,
    *,
    row_height_mm: float,
    reserved_height_mm: float = 6.0,
) -> int:
    """Return how many fallback rows fit inside an area."""

    if not math.isfinite(row_height_mm) or row_height_mm <= 0:
        raise ValueError("fallback row height must be finite and positive")
    if not math.isfinite(reserved_height_mm) or reserved_height_mm < 0:
        raise ValueError("fallback reserved height must be finite and non-negative")
    capacity = math.floor(max(0.0, area.height_mm - reserved_height_mm) / row_height_mm)
    if capacity <= 0:
        raise ValueError("fallback area must fit at least one row")
    return capacity


def resolve_responsive_fallback_pagination(
    surface: PdfSurface,
    sections: Sequence[FallbackSection],
    *,
    first_profile: ResponsiveFallbackPageProfile,
    continuation_profile: ResponsiveFallbackPageProfile,
) -> ResponsiveFallbackPagination:
    """Measure, reflow, and paginate each page class against its own geometry.

    A raw encoded cursor is retained for each section, so a wider continuation
    profile can consume longer lines without duplicating or dropping payload
    characters.
    """

    if not sections:
        raise ValueError("direct renderer has no fallback sections to render")
    if first_profile.spec.group_size != continuation_profile.spec.group_size:
        raise ValueError("fallback page profiles must use the same encoded group size")
    encoded_sections = tuple(
        _EncodedFallbackSection(
            frame=section.frame,
            title=fallback_section_title(section.label),
            encoded=encode_zbase32(encode_frame(section.frame)),
        )
        for section in sections
    )
    first_maximum_display_number = 0
    continuation_maximum_display_number = 0

    while True:
        first_metrics = _profile_metrics(
            surface,
            first_profile,
            maximum_display_number=first_maximum_display_number,
        )
        continuation_metrics = _profile_metrics(
            surface,
            continuation_profile,
            maximum_display_number=continuation_maximum_display_number,
        )
        resolved_sections, pages = _paginate_profiled_sections(
            encoded_sections,
            group_size=first_profile.spec.group_size,
            first_capacity=first_metrics.capacity,
            continuation_capacity=continuation_metrics.capacity,
            first_line_length=first_metrics.line_length,
            continuation_line_length=continuation_metrics.line_length,
        )
        next_first_maximum = max(
            first_maximum_display_number,
            _maximum_display_number(pages[:1]),
        )
        next_continuation_maximum = max(
            continuation_maximum_display_number,
            _maximum_display_number(pages[1:]),
        )
        next_first_metrics = _profile_metrics(
            surface,
            first_profile,
            maximum_display_number=next_first_maximum,
        )
        next_continuation_metrics = _profile_metrics(
            surface,
            continuation_profile,
            maximum_display_number=next_continuation_maximum,
        )
        if (
            next_first_metrics.line_length == first_metrics.line_length
            and next_continuation_metrics.line_length == continuation_metrics.line_length
        ):
            return ResponsiveFallbackPagination(
                sections=resolved_sections,
                pages=pages,
                first_line_length=next_first_metrics.line_length,
                continuation_line_length=next_continuation_metrics.line_length,
                first_payload_width_mm=next_first_metrics.payload_width_mm,
                continuation_payload_width_mm=next_continuation_metrics.payload_width_mm,
                first_capacity=next_first_metrics.capacity,
                continuation_capacity=next_continuation_metrics.capacity,
            )
        if (
            next_first_metrics.line_length > first_metrics.line_length
            or next_continuation_metrics.line_length > continuation_metrics.line_length
        ):
            raise RuntimeError("fallback profile reflow must converge monotonically")
        first_maximum_display_number = next_first_maximum
        continuation_maximum_display_number = next_continuation_maximum


def _profile_metrics(
    surface: PdfSurface,
    profile: ResponsiveFallbackPageProfile,
    *,
    maximum_display_number: int,
) -> _ResponsiveFallbackProfileMetrics:
    spec = profile.spec
    _validate_spec(spec)
    capacity = fallback_capacity(
        profile.area,
        row_height_mm=spec.row_height_mm,
        reserved_height_mm=spec.vertical_reserved_mm,
    )
    payload_width_mm = _payload_width(
        surface,
        area=profile.area,
        maximum_display_number=maximum_display_number,
        spec=spec,
    )
    if spec.safety_mm >= payload_width_mm:
        raise ValueError("fallback text safety must leave a positive payload width")
    line_length = measured_grouped_line_length(
        surface,
        style=spec.body_style,
        alphabet=ZBASE32_ALPHABET,
        group_size=spec.group_size,
        max_width_mm=payload_width_mm,
        safety_mm=spec.safety_mm,
    )
    return _ResponsiveFallbackProfileMetrics(
        capacity=capacity,
        payload_width_mm=payload_width_mm,
        line_length=line_length,
    )


def _paginate_profiled_sections(
    sections: Sequence[_EncodedFallbackSection],
    *,
    group_size: int,
    first_capacity: int,
    continuation_capacity: int,
    first_line_length: int,
    continuation_line_length: int,
) -> tuple[tuple[FallbackSectionLines, ...], tuple[FallbackPage, ...]]:
    emitted_lines: list[list[str]] = [[] for _ in sections]
    section_index = 0
    section_offset = 0
    section_line_number = 0
    section_started = False
    pages: list[FallbackPage] = []

    while section_index < len(sections):
        page_number = len(pages) + 1
        if page_number == 1:
            capacity = first_capacity
            line_length = first_line_length
        else:
            capacity = continuation_capacity
            line_length = continuation_line_length
        encoded_chars_per_line = _encoded_chars_per_grouped_line(
            group_size=group_size,
            line_length=line_length,
        )
        page_entries: list[FallbackPageEntry] = []
        display_line_number = 0

        while len(page_entries) < capacity and section_index < len(sections):
            if not section_started:
                display_line_number = 0
                title = sections[section_index].title
                if title:
                    if capacity - len(page_entries) < 2:
                        break
                    page_entries.append(
                        FallbackPageEntry(
                            entry=FallbackTitleEntry(
                                section_index=section_index,
                                title=title,
                            ),
                            row_index=len(page_entries),
                            display_line_number=None,
                        )
                    )
                section_started = True

            encoded = sections[section_index].encoded
            chunk = encoded[section_offset : section_offset + encoded_chars_per_line]
            if not chunk:
                raise ValueError("fallback section produced no encoded payload characters")
            if section_line_number >= MAX_FALLBACK_LINES:
                raise ValueError("fallback text exceeds line_count")
            text = " ".join(
                chunk[index : index + group_size] for index in range(0, len(chunk), group_size)
            )
            section_line_number += 1
            display_line_number += 1
            emitted_lines[section_index].append(text)
            page_entries.append(
                FallbackPageEntry(
                    entry=FallbackLineEntry(
                        section_index=section_index,
                        line_number=section_line_number,
                        text=text,
                    ),
                    row_index=len(page_entries),
                    display_line_number=display_line_number,
                )
            )
            section_offset += len(chunk)
            if section_offset >= len(encoded):
                section_index += 1
                section_offset = 0
                section_line_number = 0
                section_started = False

        if not page_entries:
            raise ValueError(
                "fallback page capacity cannot keep a section title with its first data line"
            )
        pages.append(FallbackPage(page_number=page_number, entries=tuple(page_entries)))

    resolved_sections = tuple(
        FallbackSectionLines(
            section_index=index,
            title=section.title,
            lines=tuple(emitted_lines[index]),
            frame=section.frame,
        )
        for index, section in enumerate(sections)
    )
    return resolved_sections, tuple(pages)


def _maximum_display_number(pages: Sequence[FallbackPage]) -> int:
    return max(
        (
            page_entry.display_line_number or 0
            for page in pages
            for page_entry in page.entries
            if isinstance(page_entry.entry, FallbackLineEntry)
        ),
        default=0,
    )


def _encoded_chars_per_grouped_line(*, group_size: int, line_length: int) -> int:
    group_count = (line_length + 1) // (group_size + 1)
    if group_count <= 0:
        raise ValueError("fallback line cannot fit one encoded group")
    return group_count * group_size


def _validate_spec(spec: ResponsiveFallbackSpec) -> None:
    if not isinstance(spec.group_size, int) or isinstance(spec.group_size, bool):
        raise ValueError("fallback group size must be an integer")
    if spec.group_size <= 0:
        raise ValueError("fallback group size must be positive")
    if not math.isfinite(spec.row_height_mm) or spec.row_height_mm <= 0:
        raise ValueError("fallback row height must be finite and positive")
    non_negative_values = {
        "left content inset": spec.content_left_inset_mm,
        "right content inset": spec.content_right_inset_mm,
        "reserved vertical space": spec.vertical_reserved_mm,
        "number gap": spec.number_gap_mm,
        "minimum number width": spec.number_minimum_width_mm,
        "number padding": spec.number_padding_mm,
        "text safety": spec.safety_mm,
    }
    for label, value in non_negative_values.items():
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"fallback {label} must be finite and non-negative")
    if not spec.inline_number and spec.number_minimum_width_mm <= 0:
        raise ValueError("fallback gutter number width must be positive")


def _payload_width(
    surface: PdfSurface,
    *,
    area: PdfRect,
    maximum_display_number: int,
    spec: ResponsiveFallbackSpec,
) -> float:
    number_label = f"{maximum_display_number:02d}."
    if spec.inline_number:
        number_width_mm = surface.measure_text_width(f"{number_label} ", spec.number_style)
    else:
        number_width_mm = max(
            spec.number_minimum_width_mm,
            surface.measure_text_width(number_label, spec.number_style) + spec.number_padding_mm,
        )
    payload_width_mm = (
        area.width_mm
        - spec.content_left_inset_mm
        - number_width_mm
        - spec.number_gap_mm
        - spec.content_right_inset_mm
    )
    if not math.isfinite(payload_width_mm) or payload_width_mm <= 0:
        raise ValueError("fallback row geometry leaves no encoded payload width")
    return payload_width_mm


def measured_fallback_number_width(
    surface: PdfSurface,
    fallback_page: FallbackPage,
    *,
    style: TextStyle,
    minimum_width_mm: float,
    padding_mm: float,
) -> float:
    """Measure a page-local number gutter from its widest displayed fallback label."""

    if not math.isfinite(minimum_width_mm) or minimum_width_mm <= 0:
        raise ValueError("minimum fallback number width must be finite and positive")
    if not math.isfinite(padding_mm) or padding_mm < 0:
        raise ValueError("fallback number padding must be finite and non-negative")
    maximum_display_number = max(
        (entry.display_line_number or 0 for entry in fallback_page.entries),
        default=0,
    )
    label = f"{maximum_display_number:02d}."
    return max(
        minimum_width_mm,
        surface.measure_text_width(label, style) + padding_mm,
    )


def build_fallback_proof(
    inputs: RenderInputs,
    sections: Sequence[FallbackSectionLines],
    pages: Sequence[FallbackPage],
) -> RenderFallbackProof:
    """Build a render fallback proof from placed fallback pages."""

    _validate_complete_fallback_pages(inputs, sections, pages)
    emitted_lines = tuple(
        page_entry.entry.text
        for page in pages
        for page_entry in page.entries
        if isinstance(page_entry.entry, FallbackLineEntry)
    )
    emitted_section_chunks = {
        (page.page_number, page_entry.entry.section_index)
        for page in pages
        for page_entry in page.entries
        if isinstance(page_entry.entry, FallbackLineEntry)
    }
    return RenderFallbackProof(
        section_frame_digests=tuple(
            frame_digest(section.frame) for section in inputs.fallback_sections or ()
        ),
        section_titles=tuple(section.title for section in sections if section.title),
        expected_section_count=len(sections),
        emitted_block_count=len(emitted_section_chunks),
        emitted_line_count=len(emitted_lines),
        consumed_section_count=len(sections),
        fully_consumed=True,
        emitted_fallback_lines=emitted_lines,
    )


def _validate_complete_fallback_pages(
    inputs: RenderInputs,
    sections: Sequence[FallbackSectionLines],
    pages: Sequence[FallbackPage],
) -> None:
    """Require proof inputs to exactly represent every source section and entry."""

    source_sections = tuple(inputs.fallback_sections or ())
    resolved_sections = tuple(sections)
    if not source_sections:
        raise ValueError("fallback proof requires at least one source section")
    if len(resolved_sections) != len(source_sections):
        raise ValueError("fallback proof section count does not match render inputs")

    for index, (resolved, source) in enumerate(
        zip(resolved_sections, source_sections, strict=True)
    ):
        if resolved.section_index != index:
            raise ValueError("fallback proof section indexes must be contiguous and ordered")
        if encode_frame(resolved.frame) != encode_frame(source.frame):
            raise ValueError(
                f"fallback proof section {index + 1} frame does not match render inputs"
            )
        if resolved.title != fallback_section_title(source.label):
            raise ValueError(
                f"fallback proof section {index + 1} title does not match render inputs"
            )
        emitted_encoded = "".join(
            character.lower()
            for line in resolved.lines
            for character in line
            if not character.isspace() and character != "-"
        )
        expected_encoded = encode_zbase32(encode_frame(source.frame))
        if emitted_encoded != expected_encoded:
            raise ValueError(
                f"fallback proof section {index + 1} lines do not encode its source frame"
            )

    resolved_pages = tuple(pages)
    if not resolved_pages:
        raise ValueError("fallback proof requires at least one populated page")
    if any(not page.entries for page in resolved_pages):
        raise ValueError("fallback proof pages cannot be empty")
    if tuple(page.page_number for page in resolved_pages) != tuple(
        range(1, len(resolved_pages) + 1)
    ):
        raise ValueError("fallback proof page numbers must be contiguous and ordered")

    expected_entries = fallback_entries(resolved_sections)
    emitted_entries = tuple(
        page_entry.entry for page in resolved_pages for page_entry in page.entries
    )
    if emitted_entries != expected_entries:
        raise ValueError("fallback proof pages do not exactly consume section entries")

    for page in resolved_pages:
        display_line_number = 0
        for page_entry in page.entries:
            if isinstance(page_entry.entry, FallbackTitleEntry):
                display_line_number = 0
                expected_display_number = None
            else:
                display_line_number += 1
                expected_display_number = display_line_number
            if page_entry.display_line_number != expected_display_number:
                raise ValueError("fallback proof page display numbers are not sequential")


__all__ = [
    "FallbackEntry",
    "FallbackLineEntry",
    "FallbackPage",
    "FallbackPageEntry",
    "FallbackSectionLines",
    "FallbackTitleEntry",
    "ResponsiveFallbackPageProfile",
    "ResponsiveFallbackPagination",
    "ResponsiveFallbackSpec",
    "build_fallback_proof",
    "fallback_capacity",
    "fallback_entries",
    "fallback_sections",
    "measured_fallback_number_width",
    "paginate_fallback_entries",
    "resolve_responsive_fallback_pagination",
]
