"""Shared QR, recovery, and shard document planning."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import TypeVar

from ethernity.qr.codec import QrConfig
from ethernity.render.checks import build_rendered_document_summary
from ethernity.render.direct_pdf import document_inputs
from ethernity.render.direct_pdf.document import DirectPdfDocumentPlan
from ethernity.render.direct_pdf.fallback_layout import (
    FallbackEntry,
    FallbackPage,
    FallbackSectionLines,
    ResponsiveFallbackPageProfile,
    ResponsiveFallbackSpec,
    build_fallback_summary,
    build_fallback_summary_from_entry_groups,
    resolve_responsive_fallback_pagination,
)
from ethernity.render.direct_pdf.page import DirectPdfPagePlan
from ethernity.render.direct_pdf.recovery_metadata import (
    RecoveryPassphraseContinuationPage,
    RecoveryPassphrasePagination,
)
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.types import PdfRect
from ethernity.render.recovery_meta import RecoveryMeta
from ethernity.render.types import FallbackSummary, RenderInputs

QrPageBuilder = Callable[[document_inputs.QrPage, int, int], DirectPdfPagePlan]
TrailingPageBuilder = Callable[[int, int], DirectPdfPagePlan]
RecoveryPageBuilder = Callable[
    [FallbackPage, RecoveryMeta, PdfRect, int],
    DirectPdfPagePlan,
]
PassphrasePageBuilder = Callable[
    [RecoveryPassphraseContinuationPage, int, int],
    DirectPdfPagePlan,
]
PageT = TypeVar("PageT")


def assemble_document_plan(
    inputs: RenderInputs,
    page_plans: Sequence[DirectPdfPagePlan],
    *,
    qr_payloads: Sequence[bytes | str] | None,
    encoded_payload_count: int,
    physical_qr_payload_indexes: Sequence[int] = (),
    fallback_summary: FallbackSummary | None = None,
) -> DirectPdfDocumentPlan:
    """Record layouts for already planned pages without choosing their layout or role."""

    pages = tuple(page_plans)
    if not pages:
        raise ValueError("direct PDF document must contain at least one planned page")
    indexes = tuple(physical_qr_payload_indexes)
    document_summary = build_rendered_document_summary(
        inputs,
        qr_payloads=qr_payloads,
        encoded_payload_count=encoded_payload_count,
        physical_qr_count=len(indexes),
        physical_qr_payload_indexes=indexes,
        page_count=len(pages),
        fallback_summary=fallback_summary,
    )
    return DirectPdfDocumentPlan(
        page_plans=pages,
        document_summary=document_summary,
        fallback_summary=fallback_summary,
    )


def build_qr_document_plan(
    inputs: RenderInputs,
    *,
    capacity: int,
    page_builder: QrPageBuilder,
    first_page_capacity: int | None = None,
    trailing_page_builder: TrailingPageBuilder | None = None,
) -> DirectPdfDocumentPlan:
    """Paginate QR items, build local pages, and summarize the document contents."""

    payloads = document_inputs.resolved_qr_payloads(inputs)
    items = document_inputs.qr_payload_items(payloads, config=inputs.qr_config or QrConfig())
    qr_pages = document_inputs.paginate_qr_items(
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
    return assemble_document_plan(
        inputs,
        page_plans,
        qr_payloads=payloads,
        encoded_payload_count=len(payloads),
        physical_qr_payload_indexes=tuple(item.payload_index for item in items),
    )


def recovery_overflow_meta(pagination: RecoveryPassphrasePagination) -> RecoveryMeta:
    """Remove inline passphrase copy once it has moved to continuation pages."""

    return replace(
        pagination.inline_meta,
        passphrase=None,
        passphrase_lines=(),
        passphrase_instructions="",
    )


def build_responsive_recovery_document_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
    *,
    passphrase_pagination: RecoveryPassphrasePagination,
    overflow_meta: RecoveryMeta,
    first_fallback_area: PdfRect,
    continuation_fallback_area: PdfRect,
    fallback_spec: ResponsiveFallbackSpec,
    fallback_page_builder: RecoveryPageBuilder,
    passphrase_page_builder: PassphrasePageBuilder,
) -> DirectPdfDocumentPlan:
    """Build recovery fallback and passphrase pages with one layout path."""

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
    return build_recovery_document_plan(
        inputs,
        fallback_pages=fallback_pages,
        passphrase_pages=passphrase_pagination.continuation_pages,
        fallback_summary=build_fallback_summary(
            inputs, fallback_pagination.sections, fallback_pages
        ),
        qr_payloads=(),
        fallback_page_builder=lambda page, total_pages: fallback_page_builder(
            page,
            (
                passphrase_pagination.inline_meta
                if page.page_number == 1 or not passphrase_pagination.continuation_pages
                else overflow_meta
            ),
            (
                first_fallback_area
                if page.page_number == 1 or not passphrase_pagination.continuation_pages
                else continuation_fallback_area
            ),
            total_pages,
        ),
        passphrase_page_builder=passphrase_page_builder,
    )


def build_recovery_document_plan(
    inputs: RenderInputs,
    *,
    fallback_pages: Sequence[PageT],
    passphrase_pages: Sequence[RecoveryPassphraseContinuationPage],
    fallback_summary: FallbackSummary,
    fallback_page_builder: Callable[[PageT, int], DirectPdfPagePlan],
    passphrase_page_builder: PassphrasePageBuilder,
    qr_payloads: Sequence[bytes | str] | None = None,
) -> DirectPdfDocumentPlan:
    """Append passphrase pages after locally paginated recovery fallback pages."""

    total_pages = len(fallback_pages) + len(passphrase_pages)
    fallback_page_plans = tuple(fallback_page_builder(page, total_pages) for page in fallback_pages)
    passphrase_page_plans = tuple(
        passphrase_page_builder(
            continuation_page,
            len(fallback_pages) + continuation_page.page_index,
            total_pages,
        )
        for continuation_page in passphrase_pages
    )
    page_plans = fallback_page_plans + passphrase_page_plans
    return assemble_document_plan(
        inputs,
        page_plans,
        qr_payloads=qr_payloads,
        encoded_payload_count=len(inputs.qr_payloads or inputs.frames),
        fallback_summary=fallback_summary,
    )


def build_single_qr_fallback_plan(
    inputs: RenderInputs,
    *,
    sections: Sequence[FallbackSectionLines],
    fallback_pages: Sequence[PageT],
    page_entries: Callable[[PageT], Sequence[FallbackEntry]],
    page_builder: Callable[[PageT, bytes, int], DirectPdfPagePlan],
) -> DirectPdfDocumentPlan:
    """Build shard pages and record their QR and fallback payloads."""

    payload = document_inputs.resolved_single_qr_payload(inputs)
    rendered_qr = document_inputs.qr_image(payload, config=inputs.qr_config or QrConfig())
    pages = tuple(fallback_pages)
    page_plans = tuple(
        page_builder(fallback_page, rendered_qr, len(pages)) for fallback_page in pages
    )
    fallback_summary = build_fallback_summary_from_entry_groups(
        inputs, sections, tuple(page_entries(page) for page in pages)
    )
    return assemble_document_plan(
        inputs,
        page_plans,
        qr_payloads=(payload,),
        encoded_payload_count=1,
        physical_qr_payload_indexes=tuple(0 for _ in page_plans),
        fallback_summary=fallback_summary,
    )


__all__ = [
    "assemble_document_plan",
    "build_qr_document_plan",
    "build_recovery_document_plan",
    "build_responsive_recovery_document_plan",
    "build_single_qr_fallback_plan",
    "recovery_overflow_meta",
]
