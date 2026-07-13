"""Shared mechanics for structured direct-PDF document families."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone

from ethernity.core.bounds import MAX_FALLBACK_LINES
from ethernity.encoding.framing import Frame, encode_frame
from ethernity.encoding.zbase32 import encode_zbase32
from ethernity.qr.codec import QrConfig, qr_bytes
from ethernity.render.copy_catalog import build_copy_bundle, build_instruction_copy
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.debug import write_direct_layout_debug_json
from ethernity.render.direct_pdf.layout_proof import build_direct_layout_proof
from ethernity.render.direct_pdf.page import DirectPdfPagePlan
from ethernity.render.direct_pdf.page_geometry import resolve_page_geometry
from ethernity.render.direct_pdf.shard_contract import validate_single_shard_fallback_contract
from ethernity.render.direct_pdf.surface import FpdfSurface, PdfSurface
from ethernity.render.direct_pdf.types import PdfRect, TextStyle
from ethernity.render.doc_types import DOC_TYPE_RECOVERY
from ethernity.render.fallback_text import fallback_section_title, format_zbase32_lines
from ethernity.render.proofs import build_render_artifact_proof, frame_digest
from ethernity.render.recovery_meta import RecoveryMeta
from ethernity.render.template_style import TemplateCapabilities, load_template_style
from ethernity.render.types import (
    FallbackSection,
    RenderArtifactProof,
    RenderFallbackProof,
    RenderInputs,
    RenderLineage,
    RenderResult,
)
from ethernity.version import get_ethernity_version


@dataclass(frozen=True)
class StructuredDirectPlan:
    """Measured pages and proofs for one structured direct render."""

    page_plans: tuple[DirectPdfPagePlan, ...]
    artifact_proof: RenderArtifactProof
    fallback_proof: RenderFallbackProof | None = None


@dataclass(frozen=True)
class StructuredContext:
    """Shared render context for structured direct-PDF design families."""

    doc_type: str
    doc_id: str
    created_timestamp_utc: str
    copy: dict[str, object]
    instructions_label: str
    instruction_lines: tuple[str, ...]
    footer_left: str
    footer_right: str
    lineage: RenderLineage
    values: dict[str, object]
    capabilities: TemplateCapabilities


@dataclass(frozen=True)
class QrPayloadItem:
    """One QR payload and pre-rendered image."""

    payload_index: int
    payload: bytes | str
    image: bytes

    @property
    def label_index(self) -> int:
        return self.payload_index + 1


@dataclass(frozen=True)
class QrPage:
    """One page of QR payload cards."""

    page_number: int
    items: tuple[QrPayloadItem, ...]


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


StructuredPlanBuilder = Callable[[PdfSurface, RenderInputs], StructuredDirectPlan]


def render_structured_plan(
    inputs: RenderInputs,
    *,
    style_name: str,
    builder: StructuredPlanBuilder,
) -> RenderResult:
    """Render a structured direct-PDF plan and return render proofs."""

    page = resolve_page_geometry(inputs)
    surface = FpdfSurface(page_width_mm=page.width_mm, page_height_mm=page.height_mm)
    packaged_direct_pdf_assets().register_fonts(surface)
    plan = builder(surface, inputs)
    layout_proof = build_direct_layout_proof(plan.page_plans)
    write_direct_layout_debug_json(
        inputs=inputs,
        page_plans=plan.page_plans,
        style_name=style_name,
        layout_proof=layout_proof,
    )
    for page_plan in plan.page_plans:
        page_plan.paint(surface)
    surface.output(inputs.output_path)
    return RenderResult(
        fallback_proof=plan.fallback_proof,
        artifact_proof=plan.artifact_proof,
        layout_proof=layout_proof,
    )


def build_structured_context(inputs: RenderInputs, *, doc_type: str) -> StructuredContext:
    """Build shared copy, spec, and metadata context for a structured render."""

    base_context = dict(inputs.context)
    created_timestamp_utc = resolve_created_timestamp(base_context)
    doc_id = resolve_doc_id(inputs, base_context)
    base_context["doc_id"] = doc_id
    base_context["lineage"] = lineage_payload(inputs.lineage)
    page = resolve_page_geometry(inputs)
    base_context["paper_size"] = page.paper_size
    copy = build_copy_bundle(doc_type=doc_type, context=base_context)
    instructions = build_instruction_copy(doc_type=doc_type, context=base_context)
    return StructuredContext(
        doc_type=doc_type,
        doc_id=doc_id,
        created_timestamp_utc=created_timestamp_utc,
        copy=copy,
        instructions_label=instructions.label,
        instruction_lines=instructions.lines,
        footer_left=generator_label(get_ethernity_version()),
        footer_right=str(copy.get("footer_guidance") or ""),
        lineage=inputs.lineage,
        values=base_context,
        capabilities=load_template_style(inputs.design_name).capabilities,
    )


def validate_qr_inputs(
    inputs: RenderInputs,
    *,
    expected_doc_type: str,
    supported_paper_sizes: frozenset[str] | None = None,
) -> None:
    """Validate structured QR-only document inputs."""

    if inputs.doc_type.strip().lower() != expected_doc_type:
        raise ValueError(f"direct structured renderer only supports {expected_doc_type} documents")
    if not inputs.render_qr:
        raise ValueError("direct structured QR renderer requires QR rendering")
    if inputs.render_fallback:
        raise ValueError("direct structured QR renderer does not render fallback text")
    if not inputs.frames:
        raise ValueError("frames cannot be empty for direct structured QR rendering")
    validate_paper_and_png(inputs, supported_paper_sizes=supported_paper_sizes)


def validate_recovery_inputs(
    inputs: RenderInputs,
    *,
    supported_paper_sizes: frozenset[str] | None = None,
) -> None:
    """Validate structured recovery-document inputs."""

    if inputs.doc_type.strip().lower() != DOC_TYPE_RECOVERY:
        raise ValueError("direct structured recovery renderer only supports recovery documents")
    if inputs.render_qr or not inputs.render_fallback:
        raise ValueError("direct structured recovery renderer requires fallback-only rendering")
    if inputs.recovery_meta is None:
        raise ValueError("recovery_meta is required for direct structured recovery rendering")
    if not inputs.fallback_sections:
        raise ValueError("fallback_sections are required for direct structured recovery rendering")
    validate_paper_and_png(inputs, supported_paper_sizes=supported_paper_sizes)


def validate_single_qr_fallback_inputs(
    inputs: RenderInputs,
    *,
    expected_doc_type: str,
    supported_paper_sizes: frozenset[str] | None = None,
) -> None:
    """Validate structured single-QR plus fallback document inputs."""

    if inputs.doc_type.strip().lower() != expected_doc_type:
        raise ValueError(f"direct structured renderer only supports {expected_doc_type} documents")
    if not inputs.render_qr or not inputs.render_fallback:
        raise ValueError("direct structured shard renderer requires QR and fallback rendering")
    validate_single_shard_fallback_contract(
        inputs,
        renderer_label="direct structured shard renderer",
    )
    validate_paper_and_png(inputs, supported_paper_sizes=supported_paper_sizes)


def validate_paper_and_png(
    inputs: RenderInputs,
    *,
    supported_paper_sizes: frozenset[str] | None = None,
) -> None:
    """Validate common structured-renderer page and QR image constraints."""

    resolve_page_geometry(inputs, supported_paper_sizes=supported_paper_sizes)
    qr_config = inputs.qr_config or QrConfig()
    qr_kind = str(qr_config.kind or "png").strip().lower()
    if qr_kind != "png":
        raise ValueError("direct structured renderer currently supports PNG QR images only")


def resolved_qr_payloads(inputs: RenderInputs) -> tuple[bytes | str, ...]:
    """Resolve QR payloads from explicit payload inputs or encoded frames."""

    if inputs.qr_payloads is not None:
        payloads = tuple(inputs.qr_payloads)
    else:
        payloads = tuple(encode_frame(frame) for frame in inputs.frames)
    if len(payloads) != len(inputs.frames):
        raise ValueError("qr_payloads length must match frames")
    return payloads


def resolved_single_qr_payload(inputs: RenderInputs) -> bytes | str:
    """Resolve the only QR payload for single-payload structured documents."""

    if inputs.qr_payloads is not None:
        payloads = tuple(inputs.qr_payloads)
    else:
        payloads = (encode_frame(inputs.frames[0]),)
    if len(payloads) != 1:
        raise ValueError("direct structured shard renderer requires exactly one QR payload")
    return payloads[0]


def qr_payload_items(
    payloads: Sequence[bytes | str],
    *,
    config: QrConfig,
) -> tuple[QrPayloadItem, ...]:
    """Build QR payload items with pre-rendered PNG images."""

    return tuple(
        QrPayloadItem(
            payload_index=index,
            payload=payload,
            image=qr_image(payload, config=config),
        )
        for index, payload in enumerate(payloads)
    )


def qr_image(payload: bytes | str, *, config: QrConfig) -> bytes:
    """Render one QR payload into PNG bytes."""

    return qr_bytes(
        payload,
        error=config.error,
        scale=config.scale,
        border=config.border,
        kind="png",
        dark=config.dark,
        light=config.light,
        version=config.version,
        mask=config.mask,
        micro=config.micro,
        boost_error=config.boost_error,
    )


def paginate_qr_items(
    items: Sequence[QrPayloadItem],
    *,
    capacity: int,
    first_page_capacity: int | None = None,
) -> tuple[QrPage, ...]:
    """Paginate QR payload items with an optional smaller first-page capacity."""

    if not items:
        raise ValueError("direct structured renderer has no QR payloads to render")
    if capacity <= 0:
        raise ValueError("QR page capacity must be positive")
    if first_page_capacity is not None and first_page_capacity <= 0:
        raise ValueError("QR first-page capacity must be positive")

    pages: list[QrPage] = []
    cursor = 0
    while cursor < len(items):
        page_capacity = first_page_capacity if not pages and first_page_capacity else capacity
        page_items = tuple(items[cursor : cursor + page_capacity])
        pages.append(
            QrPage(
                page_number=len(pages) + 1,
                items=page_items,
            )
        )
        cursor += len(page_items)
    return tuple(pages)


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
    """Paginate fallback entries with distinct first/continuation capacities."""

    if not entries:
        raise ValueError("direct structured renderer has no fallback entries to render")
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


def fallback_capacity(area: PdfRect, *, row_height_mm: float) -> int:
    """Return how many fallback rows fit inside an area."""

    capacity = math.floor(max(0.0, area.height_mm - 6.0) / row_height_mm)
    if capacity <= 0:
        raise ValueError("fallback area must fit at least one row")
    return capacity


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


def build_artifact_proof(
    inputs: RenderInputs,
    *,
    qr_payloads: Sequence[bytes | str],
    encoded_payload_count: int,
    physical_qr_count: int,
    physical_qr_payload_indexes: Sequence[int],
    page_count: int,
    fallback_proof: RenderFallbackProof | None,
) -> RenderArtifactProof:
    """Build a render artifact proof for structured direct renderers."""

    return build_render_artifact_proof(
        inputs,
        qr_payloads=tuple(qr_payloads),
        encoded_payload_count=encoded_payload_count,
        physical_qr_count=physical_qr_count,
        physical_qr_payload_indexes=tuple(physical_qr_payload_indexes),
        page_count=page_count,
        fallback_proof=fallback_proof,
    )


def component_prefix(component_base: str, page_number: int) -> str:
    """Return a stable component id prefix for a page."""

    return f"{component_base}-p{page_number}"


def positive_int(value: object, *, default: int) -> int:
    """Parse a positive integer value with a default fallback."""

    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return default
    else:
        return default
    return parsed if parsed > 0 else default


def resolve_created_timestamp(base_context: dict[str, object]) -> str:
    """Normalize created timestamp fields for structured direct display."""

    created_value = base_context.get("created_timestamp_utc")
    if created_value is None:
        created_value = base_context.get("created_date")
    created_dt = None
    created_timestamp_utc = None
    if isinstance(created_value, datetime):
        if created_value.tzinfo is None:
            created_value = created_value.replace(tzinfo=timezone.utc)
        created_dt = created_value.astimezone(timezone.utc)
    elif isinstance(created_value, date):
        created_dt = datetime.combine(created_value, datetime.min.time(), tzinfo=timezone.utc)
    elif isinstance(created_value, str):
        created_timestamp_utc, created_dt = timestamp_from_string(created_value)
    if created_timestamp_utc is None:
        created_dt = created_dt or datetime.now(timezone.utc)
        created_timestamp_utc = created_dt.strftime("%Y-%m-%d %H:%M UTC")
    base_context["created_timestamp_utc"] = created_timestamp_utc
    if created_dt is not None:
        base_context["created_date"] = created_dt.date().isoformat()
    return created_timestamp_utc


def resolve_doc_id(inputs: RenderInputs, base_context: dict[str, object]) -> str:
    """Resolve the document id shown in structured document headers."""

    doc_id = base_context.get("doc_id")
    if isinstance(doc_id, str) and doc_id.strip():
        return doc_id.strip()
    if not inputs.frames:
        raise ValueError("doc_id context is required when rendering without frames")
    return inputs.frames[0].doc_id.hex()


def timestamp_from_string(value: str) -> tuple[str | None, datetime | None]:
    """Parse or preserve a user-provided UTC timestamp string."""

    created_value = value.strip()
    if not created_value:
        return None, None
    parsed_value = created_value
    if created_value.endswith(" UTC"):
        parsed_value = f"{created_value[:-4].strip()}+00:00"
    elif created_value.endswith("Z"):
        parsed_value = f"{created_value[:-1]}+00:00"
    try:
        parsed_dt = datetime.fromisoformat(parsed_value)
    except ValueError:
        parsed_dt = None
    if parsed_dt is not None:
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
        return None, parsed_dt.astimezone(timezone.utc)
    if "UTC" in created_value or created_value.endswith("Z"):
        return created_value, None
    return f"{created_value} UTC", None


def lineage_payload(lineage: RenderLineage) -> dict[str, object]:
    """Convert render lineage to the mapping expected by copy catalogs."""

    return {
        "kind": lineage.kind,
        "extension_index": lineage.extension_index,
    }


def generator_label(ethernity_version: str) -> str:
    """Build the generator label shown in rendered document metadata."""

    normalized = ethernity_version.strip()
    if normalized:
        return f"Ethernity v{normalized}"
    return "Ethernity"


def recovery_meta_or_default(inputs: RenderInputs) -> RecoveryMeta:
    """Return required recovery metadata or a default object for typed callers."""

    return inputs.recovery_meta or RecoveryMeta()


__all__ = [
    "FallbackEntry",
    "FallbackLineEntry",
    "FallbackPage",
    "FallbackPageEntry",
    "FallbackSectionLines",
    "FallbackTitleEntry",
    "QrPage",
    "QrPayloadItem",
    "StructuredContext",
    "StructuredDirectPlan",
    "StructuredPlanBuilder",
    "build_artifact_proof",
    "build_fallback_proof",
    "build_structured_context",
    "component_prefix",
    "fallback_capacity",
    "fallback_entries",
    "measured_fallback_number_width",
    "fallback_sections",
    "generator_label",
    "lineage_payload",
    "paginate_fallback_entries",
    "paginate_qr_items",
    "positive_int",
    "qr_image",
    "qr_payload_items",
    "recovery_meta_or_default",
    "render_structured_plan",
    "resolved_qr_payloads",
    "resolved_single_qr_payload",
    "resolve_created_timestamp",
    "resolve_doc_id",
    "timestamp_from_string",
    "validate_qr_inputs",
    "validate_recovery_inputs",
    "validate_single_qr_fallback_inputs",
]
