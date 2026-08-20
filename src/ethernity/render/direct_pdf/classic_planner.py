"""Shared page orchestration for the Ledger and Maritime design families."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from ethernity.qr.codec import QrConfig
from ethernity.render.direct_pdf.fallback_layout import (
    FallbackPage,
    FallbackSectionLines,
    ResponsiveFallbackPageProfile,
    ResponsiveFallbackSpec,
    build_fallback_proof,
    resolve_responsive_fallback_pagination,
)
from ethernity.render.direct_pdf.page import DirectPdfPagePlan
from ethernity.render.direct_pdf.recovery_metadata import (
    RecoveryPassphraseContinuationPage,
    RecoveryPassphrasePagination,
)
from ethernity.render.direct_pdf.structured_common import (
    QrPage,
    StructuredDirectPlan,
    build_artifact_proof,
    paginate_qr_items,
    qr_image,
    qr_payload_items,
    resolved_qr_payloads,
    resolved_single_qr_payload,
)
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.types import PdfRect
from ethernity.render.recovery_meta import RecoveryMeta
from ethernity.render.types import RenderInputs

ClassicQrPageBuilder = Callable[[QrPage, int, int], DirectPdfPagePlan]
ClassicTrailingPageBuilder = Callable[[int, int], DirectPdfPagePlan]
ClassicRecoveryPageBuilder = Callable[
    [FallbackPage, RecoveryMeta, PdfRect, int],
    DirectPdfPagePlan,
]
ClassicPassphrasePageBuilder = Callable[
    [RecoveryPassphraseContinuationPage, int, int],
    DirectPdfPagePlan,
]
ClassicFallbackPageBuilder = Callable[[FallbackPage, bytes, int], DirectPdfPagePlan]


def build_classic_qr_plan(
    inputs: RenderInputs,
    *,
    capacity: int,
    page_builder: ClassicQrPageBuilder,
    first_page_capacity: int | None = None,
    trailing_page_builder: ClassicTrailingPageBuilder | None = None,
) -> StructuredDirectPlan:
    """Paginate QR items, build local pages, and prove the resulting artifact."""

    payloads = resolved_qr_payloads(inputs)
    items = qr_payload_items(payloads, config=inputs.qr_config or QrConfig())
    qr_pages = paginate_qr_items(
        items,
        capacity=capacity,
        first_page_capacity=first_page_capacity,
    )
    trailing_page_count = 1 if trailing_page_builder is not None else 0
    total_pages = len(qr_pages) + trailing_page_count
    page_plans = tuple(page_builder(qr_page, total_pages, len(items)) for qr_page in qr_pages)
    if trailing_page_builder is not None:
        page_plans = (
            *page_plans,
            trailing_page_builder(total_pages, total_pages),
        )
    artifact_proof = build_artifact_proof(
        inputs,
        qr_payloads=payloads,
        encoded_payload_count=len(payloads),
        physical_qr_count=len(items),
        physical_qr_payload_indexes=tuple(item.payload_index for item in items),
        page_count=len(page_plans),
        fallback_proof=None,
    )
    return StructuredDirectPlan(page_plans=page_plans, artifact_proof=artifact_proof)


def recovery_overflow_meta(pagination: RecoveryPassphrasePagination) -> RecoveryMeta:
    """Remove inline passphrase copy once it has moved to continuation pages."""

    return replace(
        pagination.inline_meta,
        passphrase=None,
        passphrase_lines=(),
        passphrase_instructions="",
    )


def build_classic_recovery_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
    *,
    passphrase_pagination: RecoveryPassphrasePagination,
    overflow_meta: RecoveryMeta,
    first_fallback_area: PdfRect,
    continuation_fallback_area: PdfRect,
    fallback_spec: ResponsiveFallbackSpec,
    fallback_page_builder: ClassicRecoveryPageBuilder,
    passphrase_page_builder: ClassicPassphrasePageBuilder,
) -> StructuredDirectPlan:
    """Build recovery fallback and passphrase pages with one proof path."""

    fallback_pagination = resolve_responsive_fallback_pagination(
        surface,
        inputs.fallback_sections or (),
        first_profile=ResponsiveFallbackPageProfile(
            area=first_fallback_area,
            spec=fallback_spec,
        ),
        continuation_profile=ResponsiveFallbackPageProfile(
            area=continuation_fallback_area,
            spec=fallback_spec,
        ),
    )
    fallback_pages = fallback_pagination.pages
    passphrase_pages = passphrase_pagination.continuation_pages
    total_pages = len(fallback_pages) + len(passphrase_pages)
    fallback_page_plans = tuple(
        fallback_page_builder(
            fallback_page,
            (
                passphrase_pagination.inline_meta
                if fallback_page.page_number == 1 or not passphrase_pages
                else overflow_meta
            ),
            (
                first_fallback_area
                if fallback_page.page_number == 1 or not passphrase_pages
                else continuation_fallback_area
            ),
            total_pages,
        )
        for fallback_page in fallback_pages
    )
    passphrase_page_plans = tuple(
        passphrase_page_builder(
            continuation_page,
            len(fallback_pages) + continuation_page.page_index,
            total_pages,
        )
        for continuation_page in passphrase_pages
    )
    page_plans = fallback_page_plans + passphrase_page_plans
    fallback_proof = build_fallback_proof(
        inputs,
        fallback_pagination.sections,
        fallback_pages,
    )
    artifact_proof = build_artifact_proof(
        inputs,
        qr_payloads=(),
        encoded_payload_count=len(inputs.qr_payloads or inputs.frames),
        physical_qr_count=0,
        physical_qr_payload_indexes=(),
        page_count=len(page_plans),
        fallback_proof=fallback_proof,
    )
    return StructuredDirectPlan(
        page_plans=page_plans,
        artifact_proof=artifact_proof,
        fallback_proof=fallback_proof,
    )


def build_classic_single_qr_fallback_plan(
    inputs: RenderInputs,
    *,
    sections: Sequence[FallbackSectionLines],
    fallback_pages: Sequence[FallbackPage],
    page_builder: ClassicFallbackPageBuilder,
) -> StructuredDirectPlan:
    """Build classic shard pages and prove their QR and fallback payloads."""

    payload = resolved_single_qr_payload(inputs)
    rendered_qr = qr_image(payload, config=inputs.qr_config or QrConfig())
    pages = tuple(fallback_pages)
    page_plans = tuple(
        page_builder(fallback_page, rendered_qr, len(pages)) for fallback_page in pages
    )
    fallback_proof = build_fallback_proof(inputs, sections, pages)
    artifact_proof = build_artifact_proof(
        inputs,
        qr_payloads=(payload,),
        encoded_payload_count=1,
        physical_qr_count=len(page_plans),
        physical_qr_payload_indexes=tuple(0 for _ in page_plans),
        page_count=len(page_plans),
        fallback_proof=fallback_proof,
    )
    return StructuredDirectPlan(
        page_plans=page_plans,
        artifact_proof=artifact_proof,
        fallback_proof=fallback_proof,
    )


__all__ = [
    "build_classic_qr_plan",
    "build_classic_recovery_plan",
    "build_classic_single_qr_fallback_plan",
    "recovery_overflow_meta",
]
