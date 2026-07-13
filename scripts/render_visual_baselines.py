#!/usr/bin/env python3
"""Generate direct-PDF visual diagnostic artifacts for renderer review work."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Literal, cast

from PIL import Image, ImageChops, ImageOps, ImageStat
from pypdf import PdfReader

from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.page_sizes import (
    DEFAULT_PAPER_SIZE_NAME,
    PaperSize,
    normalize_paper_size_name,
)
from ethernity.qr.scan import scan_qr_payloads
from ethernity.render import render_frames_to_pdf
from ethernity.render.designs import list_design_manifests
from ethernity.render.direct_pdf.page_geometry import registered_paper_sizes
from ethernity.render.doc_types import (
    DOC_TYPE_KIT,
    DOC_TYPE_KIT_INDEX,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SHARD,
    DOC_TYPE_SIGNING_KEY_SHARD,
)
from ethernity.render.proofs import extract_pdf_text, validate_fallback_render_proof
from ethernity.render.recovery_meta import build_recovery_meta
from ethernity.render.types import (
    FallbackSection,
    RenderComponentLayoutProof,
    RenderInputs,
    RenderLineage,
    RenderRectProof,
    RenderResult,
)

RendererName = Literal["direct"]
RasterizeMode = Literal["auto", "always", "never"]

DESIGN_NAMES: Final = ("archive", "forge", "ledger", "maritime", "sentinel")
DIRECT_SUPPORTED_CASES: Final = frozenset(
    {
        ("sentinel", DOC_TYPE_KIT),
        ("sentinel", DOC_TYPE_MAIN),
        ("sentinel", DOC_TYPE_RECOVERY),
        ("sentinel", DOC_TYPE_SHARD),
        ("sentinel", DOC_TYPE_SIGNING_KEY_SHARD),
        ("sentinel", DOC_TYPE_KIT_INDEX),
    }
)
DIRECT_SUPPORTED_DESIGNS: Final = frozenset({"forge"})
DIRECT_SUPPORTED_ARCHIVE_DOC_TYPES: Final = frozenset(
    {
        DOC_TYPE_KIT,
        DOC_TYPE_MAIN,
        DOC_TYPE_RECOVERY,
        DOC_TYPE_SHARD,
        DOC_TYPE_SIGNING_KEY_SHARD,
    }
)
DIRECT_SUPPORTED_LEDGER_DOC_TYPES: Final = frozenset(
    {
        DOC_TYPE_KIT,
        DOC_TYPE_MAIN,
        DOC_TYPE_RECOVERY,
        DOC_TYPE_SHARD,
        DOC_TYPE_SIGNING_KEY_SHARD,
    }
)
DIRECT_SUPPORTED_MARITIME_DOC_TYPES: Final = frozenset(
    {
        DOC_TYPE_KIT,
        DOC_TYPE_MAIN,
        DOC_TYPE_RECOVERY,
        DOC_TYPE_SHARD,
        DOC_TYPE_SIGNING_KEY_SHARD,
    }
)
DIRECT_SUPPORTED_DOC_TYPES: Final = frozenset(
    {
        DOC_TYPE_KIT,
        DOC_TYPE_KIT_INDEX,
        DOC_TYPE_MAIN,
        DOC_TYPE_RECOVERY,
        DOC_TYPE_SHARD,
        DOC_TYPE_SIGNING_KEY_SHARD,
    }
)
MANIFEST_NAME: Final = "manifest.json"
DIRECT_RENDERER_NAME: Final[RendererName] = "direct"
_DOC_ID: Final = b"\x88" * DOC_ID_LEN
_CREATED_TIMESTAMP_UTC: Final = "2026-07-06 12:00 UTC"
_REGION_BANDS: Final = (
    ("header", 0.0, 0.24),
    ("body", 0.24, 0.87),
    ("footer", 0.87, 1.0),
)
VISUAL_REVIEW_NOTE: Final = (
    "Raster deltas are diagnostics for reviewing visual drift, not pixel-perfect acceptance "
    "criteria. Preserve the existing render style, layout intent, hierarchy, and tone; "
    "document intentional bug-fix deviations."
)
_PAGE_LABEL_PATTERN: Final = re.compile(
    r"(?<![A-Z])PAGE\s+\d+\s*/\s*\d+\b",
    re.IGNORECASE,
)
MINIMUM_TEXT_FONT_SIZE_PT: Final = 6.0
MINIMUM_MANUAL_FALLBACK_LINE_NUMBER_FONT_SIZE_PT: Final = 6.5
# This is the smallest intentional QR image in the production templates. Treat reductions as a
# print/scanner compatibility change that requires an explicit contract update and fresh scans.
MINIMUM_QR_IMAGE_SIZE_MM: Final = 36.0
_CONTENT_OVERLAP_EPSILON_MM: Final = 0.05
_QR_EXPECTED_DOC_TYPES: Final = frozenset(
    {
        DOC_TYPE_KIT,
        DOC_TYPE_MAIN,
        DOC_TYPE_SHARD,
        DOC_TYPE_SIGNING_KEY_SHARD,
    }
)
_SINGLE_PAGE_DOC_TYPES: Final = frozenset(
    {
        DOC_TYPE_SHARD,
        DOC_TYPE_SIGNING_KEY_SHARD,
    }
)
_MANUAL_FALLBACK_LINE_NUMBER_CASES: Final = frozenset(
    {
        ("archive", DOC_TYPE_RECOVERY),
        ("archive", DOC_TYPE_SHARD),
        ("archive", DOC_TYPE_SIGNING_KEY_SHARD),
        ("forge", DOC_TYPE_RECOVERY),
        ("ledger", DOC_TYPE_RECOVERY),
        ("ledger", DOC_TYPE_SHARD),
        ("ledger", DOC_TYPE_SIGNING_KEY_SHARD),
        ("maritime", DOC_TYPE_RECOVERY),
        ("maritime", DOC_TYPE_SHARD),
        ("maritime", DOC_TYPE_SIGNING_KEY_SHARD),
        ("sentinel", DOC_TYPE_RECOVERY),
    }
)


@dataclass(frozen=True)
class VisualBaselineCase:
    """One design/document combination that can be rendered as a migration reference."""

    design: str
    doc_type: str
    paper_size: str = DEFAULT_PAPER_SIZE_NAME
    page_spec: PaperSize | None = None

    def __post_init__(self) -> None:
        if (
            self.page_spec is not None
            and normalize_paper_size_name(self.paper_size) != self.page_spec.name
        ):
            raise ValueError("page_spec name must match paper_size")

    @property
    def case_id(self) -> str:
        base = f"{self.design}/{self.doc_type}"
        if normalize_paper_size_name(self.paper_size) == DEFAULT_PAPER_SIZE_NAME:
            return base
        return f"{base}@{self.paper_size.strip().lower()}"


@dataclass(frozen=True)
class RasterResult:
    """Result of optional PDF-to-PNG rasterization."""

    paths: tuple[Path, ...]
    rasterizer: str | None = None
    skipped_reason: str | None = None


@dataclass(frozen=True)
class BaselineArtifact:
    """Manifest entry for one rendered PDF and any rasterized page images."""

    renderer: RendererName
    pdf_path: str
    pdf_sha256: str
    page_count: int
    text_sha256: str
    text_char_count: int
    png_paths: tuple[str, ...]
    rasterizer: str | None
    raster_skipped_reason: str | None
    layout_overflow: bool | None
    layout_component_count: int
    separation_constraint_count: int
    separation_constraints_satisfied: bool | None
    content_overlap_evidence_complete: bool
    content_overlap_count: int
    content_overlap_pairs: tuple[str, ...]
    minimum_font_size_pt: float | None
    minimum_manual_fallback_line_number_font_size_pt: float | None
    minimum_qr_image_size_mm: float | None
    expected_qr_count: int | None
    decoded_qr_count: int | None
    qr_scan_succeeded: bool | None
    numbered_page_count: int | None
    all_pages_numbered: bool | None
    poppler_warning_count: int | None
    poppler_clean: bool | None
    poppler_skipped_reason: str | None
    composited_decoded_qr_count: int | None
    composited_qr_scan_succeeded: bool | None
    composited_qr_scan_skipped_reason: str | None


@dataclass(frozen=True)
class ImageRegionDiagnostic:
    """Pixel delta diagnostics for a named page region."""

    name: str
    bbox_px: tuple[int, int, int, int]
    mean_abs_delta: float
    rms_delta: float
    max_abs_delta: int


@dataclass(frozen=True)
class ImageDeltaDiagnostic:
    """Per-page raster diagnostic between a reference and candidate image."""

    page_number: int
    status: str
    reference_png: str
    candidate_png: str
    diff_png: str | None = None
    mean_abs_delta: float | None = None
    rms_delta: float | None = None
    max_abs_delta: int | None = None
    width_px: int | None = None
    height_px: int | None = None
    regions: tuple[ImageRegionDiagnostic, ...] = ()


@dataclass(frozen=True)
class BaselineCaseReport:
    """Manifest entry for a rendered diagnostic case."""

    case_id: str
    design: str
    doc_type: str
    paper_size: str
    direct_supported: bool
    artifacts: tuple[BaselineArtifact, ...]
    diagnostics: tuple[ImageDeltaDiagnostic, ...]


@dataclass(frozen=True)
class BaselineReport:
    """Top-level visual diagnostic manifest."""

    schema_version: int
    visual_review_note: str
    output_dir: str
    cases: tuple[BaselineCaseReport, ...]


RenderCallable = Callable[[RenderInputs], RenderResult]


def discover_design_cases(
    *,
    paper_sizes: Sequence[str] | None = None,
) -> tuple[VisualBaselineCase, ...]:
    """Discover supported design/document pairs from built-in design manifests."""

    selected_paper_sizes = tuple(
        paper_sizes
        if paper_sizes is not None
        else sorted(name.upper() for name in registered_paper_sizes())
    )
    cases: list[VisualBaselineCase] = []
    for design, manifest in list_design_manifests().items():
        for doc_type in sorted(manifest.documents):
            for paper_size in selected_paper_sizes:
                cases.append(
                    VisualBaselineCase(
                        design=design,
                        doc_type=doc_type,
                        paper_size=paper_size,
                    )
                )
    return tuple(cases)


def filter_design_cases(
    cases: Sequence[VisualBaselineCase],
    *,
    designs: Sequence[str] = (),
    doc_types: Sequence[str] = (),
    paper_sizes: Sequence[str] = (),
) -> tuple[VisualBaselineCase, ...]:
    """Filter discovered cases using optional design and document selections."""

    selected_designs = frozenset(designs)
    selected_doc_types = frozenset(doc_types)
    selected_paper_sizes = frozenset(value.strip().upper() for value in paper_sizes)
    return tuple(
        case
        for case in cases
        if (not selected_designs or case.design in selected_designs)
        and (not selected_doc_types or case.doc_type in selected_doc_types)
        and (not selected_paper_sizes or case.paper_size.strip().upper() in selected_paper_sizes)
    )


def supports_direct_baseline(case: VisualBaselineCase) -> bool:
    """Return whether the current direct renderer supports this baseline case."""

    return (
        (case.design, case.doc_type) in DIRECT_SUPPORTED_CASES
        or case.design == "archive"
        and case.doc_type in DIRECT_SUPPORTED_ARCHIVE_DOC_TYPES
        or case.design == "ledger"
        and case.doc_type in DIRECT_SUPPORTED_LEDGER_DOC_TYPES
        or case.design == "maritime"
        and case.doc_type in DIRECT_SUPPORTED_MARITIME_DOC_TYPES
        or case.design in DIRECT_SUPPORTED_DESIGNS
        and case.doc_type in DIRECT_SUPPORTED_DOC_TYPES
    )


def render_visual_baselines(
    output_dir: Path,
    *,
    cases: Sequence[VisualBaselineCase] | None = None,
    rasterize: RasterizeMode = "auto",
    raster_dpi: int = 144,
    renderer: RenderCallable = render_frames_to_pdf,
    require_evidence: bool = True,
    strict_external_tools: bool = True,
) -> BaselineReport:
    """Render artifacts and enforce production evidence unless a test opts out explicitly.

    ``require_evidence=False`` is reserved for synthetic renderers that do not implement the
    production proof contract. Portable unit matrices may disable only missing external-tool
    evidence with ``strict_external_tools=False``; observed tool failures still fail.
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    selected_cases = tuple(cases if cases is not None else discover_design_cases())
    case_reports: list[BaselineCaseReport] = []

    for case in selected_cases:
        _ensure_direct_supported(case)
        artifact = render_baseline_artifact(
            case,
            DIRECT_RENDERER_NAME,
            output_dir,
            rasterize=rasterize,
            raster_dpi=raster_dpi,
            renderer=renderer,
            require_fallback_proof=require_evidence,
        )
        if require_evidence:
            validate_layout_evidence(case, artifact)
            validate_page_count_contract(case, artifact)
            validate_typography_floor(case, artifact)
            validate_page_label_evidence(case, artifact)
            validate_poppler_evidence(
                case,
                artifact,
                strict_external_tools=strict_external_tools,
            )
            validate_qr_evidence(
                case,
                artifact,
                strict_external_tools=strict_external_tools,
            )

        case_reports.append(
            BaselineCaseReport(
                case_id=case.case_id,
                design=case.design,
                doc_type=case.doc_type,
                paper_size=case.paper_size,
                direct_supported=supports_direct_baseline(case),
                artifacts=(artifact,),
                diagnostics=(),
            )
        )

    report = BaselineReport(
        schema_version=7,
        visual_review_note=VISUAL_REVIEW_NOTE,
        output_dir=str(output_dir),
        cases=tuple(case_reports),
    )
    write_manifest(output_dir / MANIFEST_NAME, report)
    return report


def render_baseline_artifact(
    case: VisualBaselineCase,
    renderer_name: RendererName,
    output_dir: Path,
    *,
    rasterize: RasterizeMode,
    raster_dpi: int,
    renderer: RenderCallable,
    require_fallback_proof: bool = True,
) -> BaselineArtifact:
    """Render one case PDF and summarize its artifact evidence."""

    case_dir = output_dir / case.design / case.doc_type / case.paper_size.strip().lower()
    case_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = case_dir / f"{renderer_name}.pdf"
    inputs = build_sample_inputs(case, pdf_path)

    result = renderer(inputs)
    if require_fallback_proof:
        validate_fallback_proof_evidence(case, inputs, result)

    reader = PdfReader(str(pdf_path))
    text = extract_pdf_text(reader)
    poppler_warnings, poppler_skipped_reason = pdf_poppler_warnings(pdf_path)
    raster = rasterize_pdf_pages(
        pdf_path,
        case_dir / renderer_name,
        mode=rasterize,
        dpi=raster_dpi,
    )
    layout_pages = result.layout_proof.pages if result.layout_proof is not None else ()
    layout_components = tuple(component for page in layout_pages for component in page.components)
    separation_constraints = tuple(
        constraint for page in layout_pages for constraint in page.separation_constraints
    )
    content_overlap_evidence_complete, content_overlap_pairs = content_overlap_evidence(
        layout_components
    )
    font_sizes = tuple(
        component.font_size_pt
        for component in layout_components
        if component.font_size_pt is not None
    )
    manual_fallback_line_number_font_sizes = tuple(
        component.font_size_pt
        for component in layout_components
        if component.font_size_pt is not None
        and is_manual_fallback_line_number_component(case, component.component_id)
    )
    qr_image_sizes = tuple(
        min(component.rect.width_mm, component.rect.height_mm)
        for component in layout_components
        if component.component_type == "image"
        and "qr" in component.component_id.lower()
        and (
            "image" in component.component_id.lower()
            or component.component_id.lower().endswith("-qr")
        )
    )
    expected_qr_count = (
        result.artifact_proof.physical_qr_count if result.artifact_proof is not None else None
    )
    decoded_qr_count: int | None = None
    qr_scan_succeeded: bool | None = None
    if expected_qr_count is not None:
        decoded_qr_count = len(scan_qr_payloads((pdf_path,))) if expected_qr_count else 0
        qr_scan_succeeded = decoded_qr_count == expected_qr_count
    composited_decoded_qr_count, composited_qr_scan_skipped_reason = (
        scan_composited_pdf_qr_count(pdf_path) if expected_qr_count else (0, None)
    )
    composited_qr_scan_succeeded = (
        composited_decoded_qr_count == expected_qr_count
        if composited_decoded_qr_count is not None and expected_qr_count is not None
        else None
    )
    numbered_page_count: int | None = None
    all_pages_numbered: bool | None = None
    if result.layout_proof is not None:
        numbered_page_count = sum(
            bool(_PAGE_LABEL_PATTERN.search(page.extract_text() or "")) for page in reader.pages
        )
        all_pages_numbered = numbered_page_count == len(reader.pages)
    return BaselineArtifact(
        renderer=renderer_name,
        pdf_path=_relative_path(output_dir, pdf_path),
        pdf_sha256=_file_sha256(pdf_path),
        page_count=len(reader.pages),
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text_char_count=len(text),
        png_paths=tuple(_relative_path(output_dir, path) for path in raster.paths),
        rasterizer=raster.rasterizer,
        raster_skipped_reason=raster.skipped_reason,
        layout_overflow=(result.layout_proof.overflow if result.layout_proof is not None else None),
        layout_component_count=len(layout_components),
        separation_constraint_count=len(separation_constraints),
        separation_constraints_satisfied=(
            all(constraint.satisfied for constraint in separation_constraints)
            if result.layout_proof is not None
            else None
        ),
        content_overlap_evidence_complete=content_overlap_evidence_complete,
        content_overlap_count=len(content_overlap_pairs),
        content_overlap_pairs=content_overlap_pairs,
        minimum_font_size_pt=min(font_sizes) if font_sizes else None,
        minimum_manual_fallback_line_number_font_size_pt=(
            min(manual_fallback_line_number_font_sizes)
            if manual_fallback_line_number_font_sizes
            else None
        ),
        minimum_qr_image_size_mm=min(qr_image_sizes) if qr_image_sizes else None,
        expected_qr_count=expected_qr_count,
        decoded_qr_count=decoded_qr_count,
        qr_scan_succeeded=qr_scan_succeeded,
        numbered_page_count=numbered_page_count,
        all_pages_numbered=all_pages_numbered,
        poppler_warning_count=(len(poppler_warnings) if poppler_warnings is not None else None),
        poppler_clean=(not poppler_warnings if poppler_warnings is not None else None),
        poppler_skipped_reason=poppler_skipped_reason,
        composited_decoded_qr_count=composited_decoded_qr_count,
        composited_qr_scan_succeeded=composited_qr_scan_succeeded,
        composited_qr_scan_skipped_reason=composited_qr_scan_skipped_reason,
    )


def validate_layout_evidence(case: VisualBaselineCase, artifact: BaselineArtifact) -> None:
    """Fail visual-baseline generation on measured overflow or separation violations."""

    if artifact.layout_overflow is None or artifact.layout_component_count <= 0:
        raise RuntimeError(f"rendered layout proof is missing for {case.case_id}")
    if artifact.layout_overflow is True:
        raise RuntimeError(f"rendered layout overflow detected for {case.case_id}")
    if (
        artifact.separation_constraint_count <= 0
        or artifact.separation_constraints_satisfied is None
    ):
        raise RuntimeError(f"rendered separation-constraint proof is missing for {case.case_id}")
    if artifact.separation_constraints_satisfied is False:
        raise RuntimeError(f"rendered separation constraint failed for {case.case_id}")
    if not artifact.content_overlap_evidence_complete:
        raise RuntimeError(f"rendered content-overlap evidence is incomplete for {case.case_id}")
    if artifact.content_overlap_count != len(artifact.content_overlap_pairs):
        raise RuntimeError(f"rendered content-overlap evidence is inconsistent for {case.case_id}")
    if artifact.content_overlap_count:
        details = "; ".join(artifact.content_overlap_pairs[:3])
        raise RuntimeError(f"rendered content overlap detected for {case.case_id}: {details}")


def validate_page_count_contract(case: VisualBaselineCase, artifact: BaselineArtifact) -> None:
    """Require shard sheets to remain one physical page with one physical QR."""

    if case.doc_type not in _SINGLE_PAGE_DOC_TYPES:
        return
    if artifact.page_count != 1:
        raise RuntimeError(
            f"rendered shard page-count contract failed for {case.case_id}: "
            f"expected 1 page, rendered {artifact.page_count}"
        )
    if artifact.expected_qr_count != 1:
        raise RuntimeError(
            f"rendered shard QR-count contract failed for {case.case_id}: "
            f"expected 1 physical QR, rendered {artifact.expected_qr_count}"
        )


def content_overlap_evidence(
    components: Sequence[RenderComponentLayoutProof],
) -> tuple[bool, tuple[str, ...]]:
    """Find unintended text/text and text/image intersections in measured visible content."""

    visible: list[tuple[str, str, RenderRectProof]] = []
    evidence_complete = True
    for component in components:
        if component.component_type == "text":
            if component.used_rect is None:
                evidence_complete = False
                continue
            visible.append(("text", component.component_id, component.used_rect))
        elif component.component_type == "image":
            visible.append(("image", component.component_id, component.rect))

    overlaps: list[str] = []
    for index, (first_type, first_id, first_rect) in enumerate(visible):
        for second_type, second_id, second_rect in visible[index + 1 :]:
            if first_type == second_type == "image":
                continue
            overlap_width_mm = min(first_rect.right_mm, second_rect.right_mm) - max(
                first_rect.x_mm,
                second_rect.x_mm,
            )
            overlap_height_mm = min(first_rect.bottom_mm, second_rect.bottom_mm) - max(
                first_rect.y_mm,
                second_rect.y_mm,
            )
            if (
                overlap_width_mm > _CONTENT_OVERLAP_EPSILON_MM
                and overlap_height_mm > _CONTENT_OVERLAP_EPSILON_MM
            ):
                overlaps.append(f"{first_id} ({first_type}) intersects {second_id} ({second_type})")
    return evidence_complete, tuple(overlaps)


def validate_fallback_proof_evidence(
    case: VisualBaselineCase,
    inputs: RenderInputs,
    result: RenderResult,
) -> None:
    """Require complete, internally consistent proof for requested manual fallback output."""

    if not inputs.render_fallback:
        return
    artifact_proof = result.artifact_proof
    if artifact_proof is None:
        raise RuntimeError(f"render artifact proof is missing for {case.case_id}")
    fallback_proof = result.fallback_proof
    if fallback_proof is None or artifact_proof.fallback_proof is None:
        raise RuntimeError(f"fallback render proof is missing for {case.case_id}")
    if artifact_proof.fallback_proof != fallback_proof:
        raise RuntimeError(f"artifact and fallback render proofs disagree for {case.case_id}")

    try:
        validate_fallback_render_proof(
            artifact_label=case.case_id,
            frames=tuple(section.frame for section in inputs.fallback_sections),
            fallback_proof=fallback_proof,
        )
    except ValueError as exc:
        raise RuntimeError(f"fallback render proof failed for {case.case_id}: {exc}") from exc


def validate_typography_floor(case: VisualBaselineCase, artifact: BaselineArtifact) -> None:
    """Fail visual-baseline generation when text drops below transcription-safe floors."""

    minimum_font_size = artifact.minimum_font_size_pt
    if minimum_font_size is None:
        raise RuntimeError(f"rendered typography evidence is missing for {case.case_id}")
    if minimum_font_size < MINIMUM_TEXT_FONT_SIZE_PT:
        raise RuntimeError(
            f"rendered text font floor failed for {case.case_id}: "
            f"{minimum_font_size:.2f}pt < {MINIMUM_TEXT_FONT_SIZE_PT:.2f}pt"
        )
    if artifact.layout_component_count <= 0 or not requires_manual_fallback_line_numbers(case):
        return
    minimum_line_number_size = artifact.minimum_manual_fallback_line_number_font_size_pt
    if minimum_line_number_size is None:
        raise RuntimeError(f"manual fallback line-number evidence is missing for {case.case_id}")
    if minimum_line_number_size < MINIMUM_MANUAL_FALLBACK_LINE_NUMBER_FONT_SIZE_PT:
        raise RuntimeError(
            f"manual fallback line-number font floor failed for {case.case_id}: "
            f"{minimum_line_number_size:.2f}pt < "
            f"{MINIMUM_MANUAL_FALLBACK_LINE_NUMBER_FONT_SIZE_PT:.2f}pt"
        )


def validate_page_label_evidence(
    case: VisualBaselineCase,
    artifact: BaselineArtifact,
) -> None:
    """Require measured page numbering on every rendered page."""

    if artifact.numbered_page_count is None or artifact.all_pages_numbered is None:
        raise RuntimeError(f"rendered page-label evidence is missing for {case.case_id}")
    if artifact.all_pages_numbered is False:
        raise RuntimeError(
            f"rendered page-label coverage mismatch for {case.case_id}: "
            f"numbered {artifact.numbered_page_count} of {artifact.page_count} pages"
        )


def validate_poppler_evidence(
    case: VisualBaselineCase,
    artifact: BaselineArtifact,
    *,
    strict_external_tools: bool,
) -> None:
    """Require a clean Poppler parse when production external-tool evidence is strict."""

    if artifact.poppler_clean is False:
        raise RuntimeError(
            f"Poppler reported {artifact.poppler_warning_count} warning(s) for {case.case_id}"
        )
    if artifact.poppler_clean is True and artifact.poppler_warning_count is None:
        raise RuntimeError(f"Poppler warning-count evidence is missing for {case.case_id}")
    if artifact.poppler_clean is None and strict_external_tools:
        reason = artifact.poppler_skipped_reason or "Poppler evidence unavailable"
        raise RuntimeError(f"Poppler evidence is missing for {case.case_id}: {reason}")


def validate_qr_evidence(
    case: VisualBaselineCase,
    artifact: BaselineArtifact,
    *,
    strict_external_tools: bool,
) -> None:
    """Require readable embedded and whole-page QRs at the physical print-size floor."""

    if case.doc_type not in _QR_EXPECTED_DOC_TYPES:
        return
    if artifact.expected_qr_count is None or artifact.expected_qr_count <= 0:
        raise RuntimeError(f"rendered QR proof is missing for {case.case_id}")
    if artifact.qr_scan_succeeded is not True or artifact.decoded_qr_count is None:
        raise RuntimeError(
            f"rendered QR scan evidence failed or is missing for {case.case_id}: "
            f"expected {artifact.expected_qr_count}, decoded {artifact.decoded_qr_count}"
        )

    minimum_qr_size = artifact.minimum_qr_image_size_mm
    if minimum_qr_size is None:
        raise RuntimeError(f"rendered QR-size evidence is missing for {case.case_id}")
    if minimum_qr_size < MINIMUM_QR_IMAGE_SIZE_MM:
        raise RuntimeError(
            f"rendered QR physical-size floor failed for {case.case_id}: "
            f"{minimum_qr_size:.2f} mm < {MINIMUM_QR_IMAGE_SIZE_MM:.2f} mm"
        )

    if artifact.composited_qr_scan_succeeded is False:
        raise RuntimeError(
            f"composited QR scan count mismatch for {case.case_id}: "
            f"expected {artifact.expected_qr_count}, "
            f"decoded {artifact.composited_decoded_qr_count}"
        )
    if (
        artifact.composited_qr_scan_succeeded is True
        and artifact.composited_decoded_qr_count is None
    ):
        raise RuntimeError(f"composited QR scan count evidence is missing for {case.case_id}")
    if artifact.composited_qr_scan_succeeded is None and strict_external_tools:
        reason = artifact.composited_qr_scan_skipped_reason or "whole-page QR scan unavailable"
        raise RuntimeError(f"composited QR scan evidence is missing for {case.case_id}: {reason}")


def requires_manual_fallback_line_numbers(case: VisualBaselineCase) -> bool:
    """Return whether this design/document renders explicitly numbered manual fallback rows."""

    return (case.design, case.doc_type) in _MANUAL_FALLBACK_LINE_NUMBER_CASES


def is_manual_fallback_line_number_component(
    case: VisualBaselineCase,
    component_id: str,
) -> bool:
    """Identify text components that visibly carry manual fallback row numbers."""

    normalized = component_id.lower()
    if "-fallback-line-number-" in normalized or "-fallback-number-" in normalized:
        return True
    return case.design == "archive" and "-fallback-line-" in normalized


def pdf_poppler_warnings(pdf_path: Path) -> tuple[tuple[str, ...] | None, str | None]:
    """Return Poppler parser warnings without treating extracted text as diagnostics."""

    pdftotext = shutil.which("pdftotext")
    if pdftotext is not None:
        command = [pdftotext, str(pdf_path), "-"]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    else:
        pdftoppm = shutil.which("pdftoppm")
        if pdftoppm is None:
            return None, "Poppler tools not found"
        with tempfile.TemporaryDirectory(prefix="poppler-validate-", dir=pdf_path.parent) as tmp:
            command = [
                pdftoppm,
                "-r",
                "10",
                "-png",
                str(pdf_path),
                str(Path(tmp) / "page"),
            ]
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit status {completed.returncode}"
        raise RuntimeError(f"Poppler could not parse {pdf_path}: {detail}")
    warnings = tuple(
        line.strip()
        for line in completed.stderr.splitlines()
        if line.strip() and not line.startswith("Fontconfig error: Cannot load default config file")
    )
    return warnings, None


def scan_composited_pdf_qr_count(
    pdf_path: Path,
    *,
    dpi: int = 200,
) -> tuple[int | None, str | None]:
    """Decode QRs from rasterized whole pages, including all paint and scaling effects."""

    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm is None:
        return None, "pdftoppm not found"
    with tempfile.TemporaryDirectory(prefix="composited-qr-", dir=pdf_path.parent) as tmp:
        completed = subprocess.run(
            [
                pdftoppm,
                "-r",
                str(dpi),
                "-png",
                str(pdf_path),
                str(Path(tmp) / "page"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or f"exit status {completed.returncode}"
            raise RuntimeError(f"could not rasterize {pdf_path} for QR scan: {detail}")
        return len(scan_qr_payloads((Path(tmp),), include_extension_carriers=False)), None


def build_sample_inputs(case: VisualBaselineCase, output_path: Path) -> RenderInputs:
    """Build stable synthetic render inputs for a visual baseline case."""

    context = _base_context(case.page_spec.name if case.page_spec is not None else case.paper_size)
    if case.doc_type == DOC_TYPE_MAIN:
        frames = tuple(
            _frame(
                FrameType.MAIN_DOCUMENT,
                index=index,
                total=20,
                data=f"visual-baseline-main-fragment-{index}".encode("ascii"),
            )
            for index in range(20)
        )
        return RenderInputs(
            frames=frames,
            output_path=output_path,
            context=context,
            doc_type=case.doc_type,
            design_name=case.design,
            lineage=RenderLineage(kind="root_backup"),
            render_qr=True,
            render_fallback=False,
            page_size=case.page_spec,
        )

    if case.doc_type == DOC_TYPE_RECOVERY:
        auth_frame = _frame(FrameType.AUTH, index=0, total=1, data=b"a" * 500)
        main_frame = _frame(
            FrameType.MAIN_DOCUMENT,
            index=0,
            total=1,
            data=b"m" * 4_000,
        )
        frames = (auth_frame, main_frame)
        return RenderInputs(
            frames=frames,
            output_path=output_path,
            context=context,
            doc_type=case.doc_type,
            design_name=case.design,
            lineage=RenderLineage(kind="root_backup"),
            render_qr=False,
            render_fallback=True,
            key_lines=_sample_key_lines(),
            recovery_meta=build_recovery_meta(
                passphrase=" ".join(f"word{index:02d}" for index in range(1, 25)),
                quorum_threshold=None,
                quorum_shares=None,
                signing_pub=b"\x31" * 32,
            ),
            fallback_sections=(
                FallbackSection(label="AUTH FRAME", frame=auth_frame),
                FallbackSection(label="MAIN FRAME", frame=main_frame),
            ),
            page_size=case.page_spec,
        )

    if case.doc_type in {DOC_TYPE_SHARD, DOC_TYPE_SIGNING_KEY_SHARD}:
        frame = _frame(
            FrameType.KEY_DOCUMENT,
            index=0,
            total=1,
            data=b"s" * 900,
        )
        shard_context = dict(context)
        shard_context.update({"shard_index": 1, "shard_total": 3, "shard_threshold": 2})
        return RenderInputs(
            frames=(frame,),
            output_path=output_path,
            context=shard_context,
            doc_type=case.doc_type,
            design_name=case.design,
            lineage=RenderLineage(kind="root_backup"),
            render_qr=True,
            render_fallback=True,
            fallback_sections=(FallbackSection(label="SHARD PAYLOAD", frame=frame),),
            page_size=case.page_spec,
        )

    if case.doc_type == DOC_TYPE_KIT:
        frames = tuple(
            _frame(
                FrameType.MAIN_DOCUMENT,
                index=index,
                total=14,
                data=f"visual-baseline-kit-frame-{index}".encode("ascii"),
            )
            for index in range(14)
        )
        kit_context = _kit_context(context)
        return RenderInputs(
            frames=frames,
            output_path=output_path,
            context=kit_context,
            doc_type=case.doc_type,
            design_name=case.design,
            lineage=RenderLineage(kind="recovery_kit"),
            qr_payloads=tuple(
                "ETK1:kit-shell-html" if index == 0 else f"ETK1:kit-chunk-{index:04d}"
                for index in range(14)
            ),
            render_qr=True,
            render_fallback=False,
            page_size=case.page_spec,
        )

    if case.doc_type == DOC_TYPE_KIT_INDEX:
        return RenderInputs(
            frames=(),
            output_path=output_path,
            context=_kit_context(context),
            doc_type=case.doc_type,
            design_name=case.design,
            lineage=RenderLineage(kind="recovery_kit"),
            qr_payloads=(),
            render_qr=False,
            render_fallback=False,
            page_size=case.page_spec,
        )

    raise ValueError(f"unsupported visual baseline doc_type: {case.doc_type}")


def rasterize_pdf_pages(
    pdf_path: Path,
    output_prefix: Path,
    *,
    mode: RasterizeMode,
    dpi: int,
) -> RasterResult:
    """Rasterize a PDF with Poppler `pdftoppm` when available or required."""

    if mode == "never":
        return RasterResult(paths=(), skipped_reason="disabled")

    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm is None:
        if mode == "always":
            raise RuntimeError("pdftoppm is required when --rasterize=always")
        return RasterResult(paths=(), skipped_reason="pdftoppm not found")

    for stale_png in output_prefix.parent.glob(f"{output_prefix.name}-*.png"):
        stale_png.unlink()

    subprocess.run(
        [
            pdftoppm,
            "-png",
            "-r",
            str(dpi),
            str(pdf_path),
            str(output_prefix),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return RasterResult(
        paths=tuple(sorted(output_prefix.parent.glob(f"{output_prefix.name}-*.png"))),
        rasterizer="pdftoppm",
    )


def build_image_pair_diagnostics(
    output_dir: Path,
    reference: BaselineArtifact,
    candidate: BaselineArtifact,
) -> tuple[ImageDeltaDiagnostic, ...]:
    """Build paired raster diagnostics when both artifacts were rasterized."""

    reference_paths = tuple(output_dir / path for path in reference.png_paths)
    candidate_paths = tuple(output_dir / path for path in candidate.png_paths)
    diagnostics: list[ImageDeltaDiagnostic] = []
    for index, (reference_path, candidate_path) in enumerate(
        zip(reference_paths, candidate_paths),
        start=1,
    ):
        diagnostics.append(
            measure_png_pair_diagnostic(
                output_dir,
                reference_path,
                candidate_path,
                page_number=index,
            )
        )
    if len(reference_paths) != len(candidate_paths):
        diagnostics.append(
            ImageDeltaDiagnostic(
                page_number=min(len(reference_paths), len(candidate_paths)) + 1,
                status="page-count-mismatch",
                reference_png="",
                candidate_png="",
            )
        )
    return tuple(diagnostics)


def measure_png_pair_diagnostic(
    output_dir: Path,
    reference_path: Path,
    candidate_path: Path,
    *,
    page_number: int,
) -> ImageDeltaDiagnostic:
    """Measure diagnostic pixel deltas for one pair of rendered page images."""

    with (
        Image.open(reference_path) as reference_image,
        Image.open(candidate_path) as candidate_image,
    ):
        reference_rgb = reference_image.convert("RGB")
        candidate_rgb = candidate_image.convert("RGB")
        status = "measured"
        if reference_rgb.size != candidate_rgb.size:
            reference_width, reference_height = reference_rgb.size
            candidate_width, candidate_height = candidate_rgb.size
            if (
                abs(reference_width - candidate_width) <= 2
                and abs(reference_height - candidate_height) <= 2
            ):
                width = min(reference_width, candidate_width)
                height = min(reference_height, candidate_height)
                reference_rgb = reference_rgb.crop((0, 0, width, height))
                candidate_rgb = candidate_rgb.crop((0, 0, width, height))
                status = "measured-normalized-size"
            else:
                return ImageDeltaDiagnostic(
                    page_number=page_number,
                    status="size-mismatch",
                    reference_png=_relative_path(output_dir, reference_path),
                    candidate_png=_relative_path(output_dir, candidate_path),
                    width_px=candidate_rgb.size[0],
                    height_px=candidate_rgb.size[1],
                )

        diff = ImageChops.difference(reference_rgb, candidate_rgb)
        diff_path = candidate_path.with_name(f"diff-{page_number}.png")
        ImageOps.autocontrast(diff).save(diff_path)
        mean_delta, rms_delta, max_delta = _image_delta_stats(diff)
        return ImageDeltaDiagnostic(
            page_number=page_number,
            status=status,
            reference_png=_relative_path(output_dir, reference_path),
            candidate_png=_relative_path(output_dir, candidate_path),
            diff_png=_relative_path(output_dir, diff_path),
            mean_abs_delta=mean_delta,
            rms_delta=rms_delta,
            max_abs_delta=max_delta,
            width_px=reference_rgb.size[0],
            height_px=reference_rgb.size[1],
            regions=_region_diagnostics(diff),
        )


def _region_diagnostics(diff: Image.Image) -> tuple[ImageRegionDiagnostic, ...]:
    width, height = diff.size
    regions: list[ImageRegionDiagnostic] = []
    for name, start_fraction, end_fraction in _REGION_BANDS:
        top = max(0, min(height - 1, int(round(height * start_fraction))))
        bottom = height if end_fraction >= 1.0 else int(round(height * end_fraction))
        bottom = max(top + 1, min(height, bottom))
        bbox = (0, top, width, bottom)
        mean_delta, rms_delta, max_delta = _image_delta_stats(diff.crop(bbox))
        regions.append(
            ImageRegionDiagnostic(
                name=name,
                bbox_px=bbox,
                mean_abs_delta=mean_delta,
                rms_delta=rms_delta,
                max_abs_delta=max_delta,
            )
        )
    return tuple(regions)


def _image_delta_stats(diff: Image.Image) -> tuple[float, float, int]:
    stat = ImageStat.Stat(diff)
    extrema = cast(tuple[tuple[int, int], ...], diff.getextrema())
    max_delta = max(channel_max for _, channel_max in extrema)
    return (
        sum(stat.mean) / len(stat.mean),
        sum(stat.rms) / len(stat.rms),
        max_delta,
    )


def write_manifest(path: Path, report: BaselineReport) -> None:
    """Write the baseline report as deterministic, reviewable JSON."""

    path.write_text(json.dumps(asdict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render direct PDF artifacts for visual review diagnostics."
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--design", action="append", choices=DESIGN_NAMES, default=[])
    parser.add_argument(
        "--doc-type",
        action="append",
        choices=tuple(sorted(DIRECT_SUPPORTED_DOC_TYPES)),
        default=[],
    )
    parser.add_argument(
        "--paper-size",
        action="append",
        choices=tuple(sorted(name.upper() for name in registered_paper_sizes())),
        default=[],
    )
    parser.add_argument("--rasterize", choices=("auto", "always", "never"), default="auto")
    parser.add_argument("--raster-dpi", type=int, default=144)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    cases = filter_design_cases(
        discover_design_cases(),
        designs=tuple(args.design),
        doc_types=tuple(args.doc_type),
        paper_sizes=tuple(args.paper_size),
    )
    if not cases:
        print("no visual baseline cases matched the requested filters", file=sys.stderr)
        return 1
    try:
        render_visual_baselines(
            args.output_dir,
            cases=cases,
            rasterize=args.rasterize,
            raster_dpi=args.raster_dpi,
        )
    except Exception as exc:
        print(f"failed to render visual baselines: {exc}", file=sys.stderr)
        return 1
    print(args.output_dir / MANIFEST_NAME)
    return 0


def _ensure_direct_supported(case: VisualBaselineCase) -> None:
    if not supports_direct_baseline(case):
        raise ValueError(f"direct renderer does not support visual baseline case {case.case_id}")


def _base_context(paper_size: str = DEFAULT_PAPER_SIZE_NAME) -> dict[str, object]:
    return {
        "paper_size": paper_size.strip().upper(),
        "doc_id": _DOC_ID.hex(),
        "created_timestamp_utc": _CREATED_TIMESTAMP_UTC,
    }


def _kit_context(base_context: dict[str, object]) -> dict[str, object]:
    context = dict(base_context)
    context.update(
        {
            "kit_qr_page_count": 2,
            "kit_qr_chunk_count": 14,
            "inventory_rows": (
                {
                    "component_id": "KIT-SHELL",
                    "detail": "Offline recovery kit shell",
                    "status": "Generated",
                },
                {
                    "component_id": "KIT-CHUNK-01",
                    "detail": "Recovery kit payload chunk 1",
                    "status": "Generated",
                },
                {
                    "component_id": "KIT-CHUNK-02",
                    "detail": "Recovery kit payload chunk 2",
                    "status": "Generated",
                },
            ),
        }
    )
    return context


def _sample_key_lines() -> tuple[str, ...]:
    return (
        "Passphrase: alpha bravo charlie delta echo foxtrot",
        "Shard quorum: 2 of 3",
        "Signing public key: 31313131313131313131313131313131",
    )


def _frame(frame_type: FrameType, *, index: int, total: int, data: bytes) -> Frame:
    return Frame(
        version=VERSION,
        frame_type=frame_type,
        doc_id=_DOC_ID,
        index=index,
        total=total,
        data=data,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
