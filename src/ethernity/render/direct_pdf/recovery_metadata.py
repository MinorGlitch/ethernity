"""Lossless measured pagination for printable recovery passphrases."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace

from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy, fit_text_to_width
from ethernity.render.direct_pdf.types import TextStyle
from ethernity.render.recovery_meta import (
    PASSPHRASE_JSON_PARTS_LABEL,
    PASSPHRASE_PRINT_MODE_JSON_PARTS,
    PASSPHRASE_PRINT_MODE_LITERAL,
    RecoveryMeta,
    decode_printed_passphrase,
)

PASSPHRASE_PARTS_INSTRUCTIONS = (
    "JSON-decode each quoted part, then concatenate the decoded values in numeric order. "
    "Never concatenate the quoted or escaped source text."
)
PASSPHRASE_LITERAL_INSTRUCTIONS = (
    "Join every printed passphrase line with one ASCII space, in page and line order."
)
_PART_NUMBER_RESERVE = "999999/999999 "
_MAX_PART_COUNT = 999_999


@dataclass(frozen=True)
class RecoveryPassphrasePart:
    """One independently decodable, ordered JSON string part."""

    part_number: int
    total_parts: int
    encoded_json: str

    @property
    def line_text(self) -> str:
        digits = max(2, len(str(self.total_parts)))
        return f"{self.part_number:0{digits}d}/{self.total_parts:0{digits}d} {self.encoded_json}"

    @property
    def decoded_value(self) -> str:
        decoded = json.loads(self.encoded_json)
        if not isinstance(decoded, str):
            raise ValueError("recovery passphrase JSON part must decode to a string")
        return decoded


@dataclass(frozen=True)
class RecoveryPassphraseContinuationPage:
    """Passphrase parts assigned to one metadata continuation page."""

    page_index: int
    total_pages: int
    print_mode: str
    literal_lines: tuple[str, ...] = ()
    parts: tuple[RecoveryPassphrasePart, ...] = ()

    @property
    def lines(self) -> tuple[str, ...]:
        if self.print_mode == PASSPHRASE_PRINT_MODE_JSON_PARTS:
            return tuple(part.line_text for part in self.parts)
        return self.literal_lines

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def instructions(self) -> str:
        if self.print_mode == PASSPHRASE_PRINT_MODE_JSON_PARTS:
            return PASSPHRASE_PARTS_INSTRUCTIONS
        return PASSPHRASE_LITERAL_INSTRUCTIONS


@dataclass(frozen=True)
class RecoveryPassphrasePagination:
    """Inline metadata plus any overflow pages, with a lossless round-trip proof."""

    inline_meta: RecoveryMeta
    inline_parts: tuple[RecoveryPassphrasePart, ...] = ()
    continuation_pages: tuple[RecoveryPassphraseContinuationPage, ...] = ()

    @property
    def uses_json_parts(self) -> bool:
        return bool(self.inline_parts) or any(
            page.print_mode == PASSPHRASE_PRINT_MODE_JSON_PARTS for page in self.continuation_pages
        )

    @property
    def uses_literal_continuation(self) -> bool:
        return any(
            page.print_mode == PASSPHRASE_PRINT_MODE_LITERAL for page in self.continuation_pages
        )

    @property
    def all_parts(self) -> tuple[RecoveryPassphrasePart, ...]:
        return self.inline_parts + tuple(
            part for page in self.continuation_pages for part in page.parts
        )

    @property
    def printed_lines(self) -> tuple[str, ...]:
        if self.uses_json_parts:
            return tuple(part.line_text for part in self.all_parts)
        if self.uses_literal_continuation:
            return self.inline_meta.passphrase_lines + tuple(
                line for page in self.continuation_pages for line in page.literal_lines
            )
        return self.inline_meta.passphrase_lines

    def decoded_passphrase(self) -> str | None:
        if self.inline_meta.passphrase is None and not self.inline_meta.passphrase_lines:
            return None
        if self.uses_json_parts:
            return decode_printed_passphrase(
                tuple(part.line_text for part in self.all_parts),
                print_mode=PASSPHRASE_PRINT_MODE_JSON_PARTS,
            )
        if self.uses_literal_continuation:
            return " ".join(self.printed_lines)
        return decode_printed_passphrase(
            self.inline_meta.passphrase_lines,
            print_mode=self.inline_meta.passphrase_print_mode,
        )


def paginate_recovery_passphrase(
    surface: PdfSurface,
    meta: RecoveryMeta,
    *,
    style: TextStyle,
    guidance_style: TextStyle | None = None,
    max_width_mm: float,
    continuation_width_mm: float | None = None,
    inline_height_mm: float,
    continuation_height_mm: float,
    line_height_multiplier: float = 1.15,
    guidance_line_height_multiplier: float = 1.15,
    guidance_value_gap_mm: float = 1.0,
) -> RecoveryPassphrasePagination:
    """Keep fitting metadata inline and paginate overflow into lossless JSON parts.

    The supplied heights are text-only capacities after the template has reserved labels,
    padding, and page chrome. A passphrase with zero line capacity fails immediately instead of
    entering a non-progressing pagination loop.
    """

    if max_width_mm <= 0:
        raise ValueError("recovery passphrase printable width must be positive")
    resolved_continuation_width_mm = (
        max_width_mm if continuation_width_mm is None else continuation_width_mm
    )
    if resolved_continuation_width_mm <= 0:
        raise ValueError("recovery passphrase continuation width must be positive")
    if inline_height_mm <= 0:
        raise ValueError("recovery passphrase inline height must be positive")
    if continuation_height_mm <= 0:
        raise ValueError("recovery passphrase continuation height must be positive")
    if guidance_value_gap_mm < 0:
        raise ValueError("recovery passphrase guidance gap must be non-negative")

    if meta.passphrase is None and not meta.passphrase_lines:
        return RecoveryPassphrasePagination(inline_meta=meta)

    line_height_mm = surface.line_height(style, multiplier=line_height_multiplier)
    continuation_capacity = math.floor((continuation_height_mm + 1e-9) / line_height_mm)
    if math.floor((inline_height_mm + 1e-9) / line_height_mm) < 1:
        raise ValueError("recovery passphrase inline area has zero printable line capacity")
    if continuation_capacity < 1:
        raise ValueError("recovery passphrase continuation area has zero printable line capacity")

    resolved_guidance_style = style if guidance_style is None else guidance_style
    existing_inline_capacity = _inline_value_capacity(
        surface,
        guidance=meta.passphrase_instructions,
        guidance_style=resolved_guidance_style,
        value_line_height_mm=line_height_mm,
        inline_height_mm=inline_height_mm,
        max_width_mm=max_width_mm,
        guidance_line_height_multiplier=guidance_line_height_multiplier,
        guidance_value_gap_mm=guidance_value_gap_mm,
    )
    if existing_inline_capacity < 1:
        raise ValueError("recovery passphrase inline guidance leaves zero value-line capacity")

    raw_passphrase = _raw_passphrase(meta)
    existing_lines = meta.passphrase_lines or ((meta.passphrase or ""),)
    if meta.passphrase_print_mode == PASSPHRASE_PRINT_MODE_LITERAL:
        literal_tokens_fit = all(
            surface.measure_text_width(token, style) <= max_width_mm
            for token in raw_passphrase.split(" ")
        )
        if literal_tokens_fit:
            wrapped_literal_lines = fit_text_to_width(
                surface,
                "\n".join(existing_lines),
                style,
                max_width_mm=max_width_mm,
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=line_height_multiplier,
            ).lines
            if " ".join(wrapped_literal_lines) != raw_passphrase:
                raise ValueError("literal passphrase wrapping failed its lossless round-trip proof")
            if len(wrapped_literal_lines) <= existing_inline_capacity:
                inline_meta = (
                    meta
                    if wrapped_literal_lines == existing_lines
                    else replace(meta, passphrase_lines=wrapped_literal_lines)
                )
                return RecoveryPassphrasePagination(inline_meta=inline_meta)
            inline_line_count = _inline_value_capacity(
                surface,
                guidance=PASSPHRASE_LITERAL_INSTRUCTIONS,
                guidance_style=resolved_guidance_style,
                value_line_height_mm=line_height_mm,
                inline_height_mm=inline_height_mm,
                max_width_mm=max_width_mm,
                guidance_line_height_multiplier=guidance_line_height_multiplier,
                guidance_value_gap_mm=guidance_value_gap_mm,
            )
            if inline_line_count < 1:
                raise ValueError(
                    "recovery passphrase inline area must fit guidance and one value line"
                )
            inline_lines = wrapped_literal_lines[:inline_line_count]
            consumed_token_count = sum(len(line.split(" ")) for line in inline_lines)
            remaining_text = " ".join(raw_passphrase.split(" ")[consumed_token_count:])
            overflow_lines = fit_text_to_width(
                surface,
                remaining_text,
                style,
                max_width_mm=resolved_continuation_width_mm,
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=line_height_multiplier,
            ).lines
            page_lines = tuple(
                overflow_lines[index : index + continuation_capacity]
                for index in range(0, len(overflow_lines), continuation_capacity)
            )
            continuation_pages = tuple(
                RecoveryPassphraseContinuationPage(
                    page_index=index,
                    total_pages=len(page_lines),
                    print_mode=PASSPHRASE_PRINT_MODE_LITERAL,
                    literal_lines=chunk,
                )
                for index, chunk in enumerate(page_lines, start=1)
            )
            pagination = RecoveryPassphrasePagination(
                inline_meta=replace(
                    meta,
                    passphrase_lines=inline_lines,
                    passphrase_instructions=PASSPHRASE_LITERAL_INSTRUCTIONS,
                ),
                continuation_pages=continuation_pages,
            )
            if pagination.decoded_passphrase() != raw_passphrase:
                raise ValueError(
                    "literal recovery passphrase pagination failed its lossless round-trip proof"
                )
            return pagination

    existing_fits = len(existing_lines) <= existing_inline_capacity and all(
        surface.measure_text_width(line, style) <= max_width_mm for line in existing_lines
    )
    if existing_fits:
        return RecoveryPassphrasePagination(inline_meta=meta)

    json_parts_inline_capacity = _inline_value_capacity(
        surface,
        guidance=PASSPHRASE_PARTS_INSTRUCTIONS,
        guidance_style=resolved_guidance_style,
        value_line_height_mm=line_height_mm,
        inline_height_mm=inline_height_mm,
        max_width_mm=max_width_mm,
        guidance_line_height_multiplier=guidance_line_height_multiplier,
        guidance_value_gap_mm=guidance_value_gap_mm,
    )
    if json_parts_inline_capacity < 1:
        raise ValueError("recovery passphrase inline area must fit guidance and one value line")

    encoded_fragments, inline_fragment_count = _split_json_fragments(
        surface,
        raw_passphrase,
        style=style,
        inline_width_mm=max_width_mm,
        continuation_width_mm=resolved_continuation_width_mm,
        inline_fragment_capacity=json_parts_inline_capacity,
    )
    total_parts = len(encoded_fragments)
    parts = tuple(
        RecoveryPassphrasePart(
            part_number=index,
            total_parts=total_parts,
            encoded_json=encoded,
        )
        for index, encoded in enumerate(encoded_fragments, start=1)
    )
    inline_parts = parts[:inline_fragment_count]
    overflow_parts = parts[inline_fragment_count:]
    if any(
        surface.measure_text_width(part.line_text, style) > max_width_mm for part in inline_parts
    ):
        raise ValueError("numbered inline recovery passphrase part exceeds the printable width")
    if any(
        surface.measure_text_width(part.line_text, style) > resolved_continuation_width_mm
        for part in overflow_parts
    ):
        raise ValueError("numbered recovery passphrase continuation part exceeds printable width")
    page_parts = tuple(
        overflow_parts[index : index + continuation_capacity]
        for index in range(0, len(overflow_parts), continuation_capacity)
    )
    continuation_pages = tuple(
        RecoveryPassphraseContinuationPage(
            page_index=index,
            total_pages=len(page_parts),
            print_mode=PASSPHRASE_PRINT_MODE_JSON_PARTS,
            parts=chunk,
        )
        for index, chunk in enumerate(page_parts, start=1)
    )
    inline_meta = replace(
        meta,
        passphrase_lines=tuple(part.line_text for part in inline_parts),
        passphrase_label=PASSPHRASE_JSON_PARTS_LABEL,
        passphrase_print_mode=PASSPHRASE_PRINT_MODE_JSON_PARTS,
        passphrase_instructions=PASSPHRASE_PARTS_INSTRUCTIONS,
    )
    pagination = RecoveryPassphrasePagination(
        inline_meta=inline_meta,
        inline_parts=inline_parts,
        continuation_pages=continuation_pages,
    )
    if pagination.decoded_passphrase() != raw_passphrase:
        raise ValueError("recovery passphrase pagination failed its lossless round-trip proof")
    return pagination


def _raw_passphrase(meta: RecoveryMeta) -> str:
    if meta.passphrase is not None:
        return meta.passphrase
    return decode_printed_passphrase(
        meta.passphrase_lines,
        print_mode=meta.passphrase_print_mode,
    )


def _inline_value_capacity(
    surface: PdfSurface,
    *,
    guidance: str,
    guidance_style: TextStyle,
    value_line_height_mm: float,
    inline_height_mm: float,
    max_width_mm: float,
    guidance_line_height_multiplier: float,
    guidance_value_gap_mm: float,
) -> int:
    guidance_height_mm = 0.0
    if guidance:
        guidance_height_mm = fit_text_to_width(
            surface,
            guidance,
            guidance_style,
            max_width_mm=max_width_mm,
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=guidance_line_height_multiplier,
        ).height_mm
        guidance_height_mm += guidance_value_gap_mm
    available_height_mm = inline_height_mm - guidance_height_mm
    return math.floor((available_height_mm + 1e-9) / value_line_height_mm)


def _split_json_fragments(
    surface: PdfSurface,
    passphrase: str,
    *,
    style: TextStyle,
    inline_width_mm: float,
    continuation_width_mm: float,
    inline_fragment_capacity: int,
) -> tuple[tuple[str, ...], int]:
    if not passphrase:
        return (json.dumps("", ensure_ascii=True),), 1

    fragments: list[str] = []
    start = 0
    while start < len(passphrase):
        fragment_width_mm = (
            inline_width_mm if len(fragments) < inline_fragment_capacity else continuation_width_mm
        )
        end = _maximum_fitting_end(
            surface,
            passphrase,
            start=start,
            style=style,
            max_width_mm=fragment_width_mm,
        )
        if end <= start:
            character = passphrase[start]
            raise ValueError(
                "recovery passphrase continuation width cannot fit one encoded character: "
                f"U+{ord(character):04X}"
            )
        fragments.append(json.dumps(passphrase[start:end], ensure_ascii=True))
        if len(fragments) > _MAX_PART_COUNT:
            raise ValueError(
                f"recovery passphrase exceeds practical {_MAX_PART_COUNT}-part PDF limit"
            )
        start = end
    return tuple(fragments), min(len(fragments), inline_fragment_capacity)


def _maximum_fitting_end(
    surface: PdfSurface,
    passphrase: str,
    *,
    start: int,
    style: TextStyle,
    max_width_mm: float,
) -> int:
    low = start + 1
    high = len(passphrase)
    best = start
    while low <= high:
        middle = (low + high) // 2
        encoded = json.dumps(passphrase[start:middle], ensure_ascii=True)
        candidate = f"{_PART_NUMBER_RESERVE}{encoded}"
        if surface.measure_text_width(candidate, style) <= max_width_mm:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    return best


__all__ = [
    "PASSPHRASE_LITERAL_INSTRUCTIONS",
    "PASSPHRASE_PARTS_INSTRUCTIONS",
    "RecoveryPassphraseContinuationPage",
    "RecoveryPassphrasePagination",
    "RecoveryPassphrasePart",
    "paginate_recovery_passphrase",
]
