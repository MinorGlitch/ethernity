from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pypdf import PdfReader

from ethernity.render.checks import build_rendered_document_summary
from ethernity.render.direct_pdf import document
from ethernity.render.direct_pdf.components import BoxPlacement, Panel
from ethernity.render.direct_pdf.page import build_page_plan
from ethernity.render.direct_pdf.page_geometry import resolve_page_geometry
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.types import PdfColor, PdfRect
from ethernity.render.types import DocumentOrigin, RenderInputs


def _inputs(path: Path, created: date | str | None = None) -> RenderInputs:
    return RenderInputs(
        frames=(),
        output_path=path,
        context={"created_timestamp_utc": created},
        doc_type="kit_index",
        origin=DocumentOrigin(kind="recovery_kit"),
        render_qr=False,
        render_fallback=False,
    )


@dataclass(frozen=True)
class _BrokenPaintPlan:
    component_id: str
    layout: BoxPlacement

    def paint(self, surface: PdfSurface) -> None:
        raise RuntimeError("painting failed")


def _plan(
    surface: PdfSurface, inputs: RenderInputs, *, broken_painter: bool = False
) -> document.DirectPdfDocumentPlan:
    page_rect = resolve_page_geometry(inputs).rect
    panel = Panel(component_id="panel", fill=PdfColor(240, 240, 240)).plan(
        surface, PdfRect(10, 10, 20, 20)
    )
    component = _BrokenPaintPlan(panel.component_id, panel.layout) if broken_painter else panel
    page = build_page_plan(page_number=1, rect=page_rect, plans=(component,))
    summary = build_rendered_document_summary(
        inputs,
        qr_payloads=(),
        encoded_payload_count=0,
        physical_qr_count=0,
        physical_qr_payload_indexes=(),
        page_count=1,
        fallback_summary=None,
    )
    return document.DirectPdfDocumentPlan(page_plans=(page,), document_summary=summary)


def _planning_failure(surface: PdfSurface, inputs: RenderInputs) -> document.DirectPdfDocumentPlan:
    raise RuntimeError("planning failed")


def test_render_reports_real_page_count_and_can_stop_before_output(tmp_path: Path) -> None:
    calls = []
    path = tmp_path / "progress.pdf"
    inputs = replace(_inputs(path), on_page=lambda *args: calls.append(args))
    document.render_document_plan(inputs, style_name="sentinel", builder=_plan)
    assert calls == [("kit_index", 0, 1), ("kit_index", 1, 1)]
    assert len(PdfReader(path).pages) == 1
    original = path.read_bytes()

    def stop(*_args) -> None:
        raise InterruptedError("stop rendering")

    with pytest.raises(InterruptedError):
        document.render_document_plan(
            replace(inputs, on_page=stop), style_name="sentinel", builder=_plan
        )
    assert path.read_bytes() == original


def _painting_failure(surface: PdfSurface, inputs: RenderInputs) -> document.DirectPdfDocumentPlan:
    return _plan(surface, inputs, broken_painter=True)


@pytest.mark.parametrize("builder", (_planning_failure, _painting_failure))
def test_failed_render_preserves_existing_output(
    tmp_path: Path, builder: document.DocumentPlanBuilder
) -> None:
    path = tmp_path / "existing.pdf"
    original = b"previous output"
    path.write_bytes(original)

    with pytest.raises(RuntimeError, match="failed"):
        document.render_document_plan(_inputs(path), style_name="sentinel", builder=builder)

    assert path.read_bytes() == original


@pytest.mark.parametrize(
    ("created", "expected"),
    (
        ("2026-07-06 12:00 UTC", datetime(2026, 7, 6, 12, tzinfo=UTC)),
        (date(2026, 7, 6), datetime(2026, 7, 6, tzinfo=UTC)),
        (
            datetime(2026, 7, 6, 14, tzinfo=timezone(timedelta(hours=2))),
            datetime(2026, 7, 6, 12, tzinfo=UTC),
        ),
    ),
)
def test_explicit_creation_date_reaches_emitted_pdf(
    tmp_path: Path, created: date | str, expected: datetime
) -> None:
    inputs = _inputs(tmp_path / "dated.pdf", created)
    document.render_document_plan(
        inputs,
        style_name="sentinel",
        builder=_plan,
        creation_date=document.explicit_creation_date(inputs),
    )

    metadata = PdfReader(inputs.output_path).metadata
    assert metadata is not None
    assert metadata.creation_date == expected
