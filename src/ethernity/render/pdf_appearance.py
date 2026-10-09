"""Validate text placements and QR payloads in the composed, printable PDF."""

from __future__ import annotations

import ctypes
import math
from contextlib import closing
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
import zxingcpp
from PIL import Image, ImageChops

from ethernity.render.checks import RenderValidationError
from ethernity.render.types import LayoutReport, PageLayout, RenderRect
from ethernity.security.resource_worker import (
    DisposableWorkerError,
    WorkerLimits,
    run_disposable_worker,
)

_DPI = 300
_SCALE = _DPI / 72.0
_MM_TO_PIXEL = _DPI / 25.4
_POINT_TO_MM = 25.4 / 72.0
_POSITION_TOLERANCE_MM = 0.02
_MAX_PAGE_PIXELS = 25_000_000
_MIN_QR_CONTRAST = 64


def validate_pdf_appearance(
    *,
    path: str | Path,
    layout_report: LayoutReport,
    render_qr: bool,
    document_label: str,
) -> tuple[bytes, ...]:
    """Check actual page pixels in a bounded process, in page and reading order.

    PDFium is not thread safe. Keeping it in the disposable worker also bounds native
    parsing, raster memory, and decoder time without serializing application threads.
    """

    try:
        return run_disposable_worker(
            "PDF appearance validation",
            _validate_pdf_appearance_worker,
            (str(path), layout_report, render_qr, document_label),
            limits=WorkerLimits(
                memory_bytes=1024 * 1024 * 1024,
                cpu_seconds=45,
                wall_seconds=60.0,
                output_bytes=32 * 1024 * 1024,
            ),
        )
    except DisposableWorkerError as exc:
        raise RenderValidationError(str(exc)) from exc


def _validate_pdf_appearance_worker(
    path: str, layout: LayoutReport, render_qr: bool, label: str
) -> tuple[bytes, ...]:
    decoded: list[bytes] = []
    with pdfium.PdfDocument(path) as document:
        for index, plan in enumerate(layout.pages):
            page = document[index]
            try:
                width, height = page.get_size()
                if math.ceil(width * _SCALE) * math.ceil(height * _SCALE) > _MAX_PAGE_PIXELS:
                    raise RenderValidationError(f"{label} exceeds the PDF raster page pixel limit")
                with closing(page.get_textpage()) as textpage:
                    objects = tuple(page.get_objects(max_depth=1, textpage=textpage))
                    texts = tuple(obj for obj in objects if isinstance(obj, pdfium.PdfTextObj))
                    _validate_text_objects(
                        texts,
                        plan=plan,
                        height_pt=height,
                        label=label,
                    )
                    composed = _render_page(page)
                    try:
                        if render_qr:
                            decoded.extend(_decode_page_qrs(composed, plan=plan))
                        _validate_text_visibility(
                            page, objects=objects, texts=texts, composed=composed, label=label
                        )
                    finally:
                        composed.close()
            finally:
                page.close()
    return tuple(decoded)


def _validate_text_objects(
    objects: tuple[pdfium.PdfTextObj, ...],
    *,
    plan: PageLayout,
    height_pt: float,
    label: str,
) -> None:
    expected = tuple(
        (component, line)
        for component in plan.components
        for line in component.text_lines
        if line.text
    )
    for obj, (component, line) in zip(objects, expected, strict=False):
        matrix = obj.get_matrix().get()
        x_mm = matrix[4] * _POINT_TO_MM
        baseline_y_mm = (height_pt - matrix[5]) * _POINT_TO_MM
        metadata = component.text_metadata
        value_label = metadata.role.replace("_", " ") if metadata else "planned text"
        if (
            abs(x_mm - line.x_mm) > _POSITION_TOLERANCE_MM
            or abs(baseline_y_mm - line.baseline_y_mm) > _POSITION_TOLERANCE_MM
            or any(
                abs(value - target) > 1e-5
                for value, target in zip(matrix[:4], (1, 0, 0, 1), strict=True)
            )
            or component.font_size_pt is None
            or abs(obj.get_font_size() - component.font_size_pt) > 0.01
        ):
            raise RenderValidationError(
                f"{label} has missing or incorrect {value_label} at its planned placement",
                details={"page_number": plan.page_number, "component_id": component.component_id},
            )
        color = tuple(ctypes.c_uint() for _ in range(4))
        if not pdfium_raw.FPDFPageObj_GetFillColor(obj, *(ctypes.byref(value) for value in color)):
            raise RenderValidationError(f"{label} has unreadable text paint state")
        if pdfium_raw.FPDFTextObj_GetTextRenderMode(
            obj
        ) != pdfium_raw.FPDF_TEXTRENDERMODE_FILL or tuple(value.value for value in color) != (
            *line.color,
            255,
        ):
            raise RenderValidationError(f"{label} has invisible or incorrect {value_label} paint")
    if len(objects) != len(expected):
        raise RenderValidationError(f"{label} painted text does not match its layout report")


def _validate_text_visibility(
    page: pdfium.PdfPage,
    *,
    objects: tuple[pdfium.PdfObject, ...],
    texts: tuple[pdfium.PdfTextObj, ...],
    composed: Image.Image,
    label: str,
) -> None:
    """Require glyph ink to contribute to the final page, including under later paint.

    Compare the final page to the same page with text disabled. An isolated text alpha
    mask locates glyph interiors, so panels and decorative ink cannot satisfy the check.
    """

    for obj in texts:
        _set_active(obj, False)
    without_text = _render_page(page)
    try:
        for obj in objects:
            _set_active(obj, isinstance(obj, pdfium.PdfTextObj))
        isolated = _render_page(page, transparent=True)
        try:
            alpha = isolated.getchannel("A")
            mask = alpha.point(lambda value: 255 if value >= 240 else 0)
            difference = ImageChops.difference(composed, without_text)
            red, green, blue = difference.split()
            contrast = ImageChops.lighter(ImageChops.lighter(red, green), blue)
            visible = contrast.point(lambda value: 255 if value >= 16 else 0)
            hidden = ImageChops.subtract(mask, visible)
            if hidden.getbbox() is not None:
                raise RenderValidationError(f"{label} has covered or unreadable printed text")
            for obj in texts:
                box = _object_pixel_box(obj, page)
                if obj.extract().strip() and mask.crop(box).getbbox() is None:
                    # A thin underscore may have no nearly opaque pixels. Check
                    # its darkest ink instead, with a half-coverage minimum.
                    glyph_alpha = alpha.crop(box)
                    threshold = max(128, min(240, glyph_alpha.getextrema()[1]))
                    ink = glyph_alpha.point(
                        lambda value, threshold=threshold: 255 if value >= threshold else 0
                    )
                    if ink.getbbox() is None:
                        raise RenderValidationError(f"{label} has invisible printed text")
                    if ImageChops.subtract(ink, visible.crop(box)).getbbox() is not None:
                        raise RenderValidationError(
                            f"{label} has covered or unreadable printed text"
                        )
        finally:
            isolated.close()
    finally:
        without_text.close()


def _set_active(obj: pdfium.PdfObject, active: bool) -> None:
    if not pdfium_raw.FPDFPageObj_SetIsActive(obj, active):
        raise RenderValidationError("PDF appearance validation could not isolate page text")


def _render_page(page: pdfium.PdfPage, *, transparent: bool = False) -> Image.Image:
    with closing(
        page.render(scale=_SCALE, fill_color=(0, 0, 0, 0) if transparent else (255, 255, 255, 255))
    ) as bitmap:
        return bitmap.to_pil().convert("RGBA" if transparent else "RGB")


def _object_pixel_box(obj: pdfium.PdfObject, page: pdfium.PdfPage) -> tuple[int, int, int, int]:
    left, bottom, right, top = obj.get_bounds()
    height = page.get_height()
    return (
        math.floor(left * _SCALE),
        math.floor((height - top) * _SCALE),
        math.ceil(right * _SCALE),
        math.ceil((height - bottom) * _SCALE),
    )


def _decode_page_qrs(image: Image.Image, *, plan: PageLayout) -> tuple[bytes, ...]:
    # Every image component in the direct renderer is a QR placement. Use its measured
    # box, not its resource identity, and order rows before columns for kit documents.
    rects = sorted(
        (component.rect for component in plan.components if component.component_type == "image"),
        key=lambda rect: (round(rect.y_mm, 2), rect.x_mm),
    )
    decoded: list[bytes] = []
    for rect in rects:
        # A decoder can stretch tiny luminance differences in a tightly cropped QR.
        # Require contrast in the actual print pixels as well as successful decoding.
        box = (
            math.ceil(rect.x_mm * _MM_TO_PIXEL),
            math.ceil(rect.y_mm * _MM_TO_PIXEL),
            math.floor(rect.right_mm * _MM_TO_PIXEL),
            math.floor(rect.bottom_mm * _MM_TO_PIXEL),
        )
        with image.crop(box).convert("L") as luminance:
            histogram = luminance.histogram()
            dark = next(index for index, count in enumerate(histogram) if count)
            light = next(index for index in reversed(range(len(histogram))) if histogram[index])
        if light - dark < _MIN_QR_CONTRAST:
            raise RenderValidationError(
                "rendered PDF has no usable QR payloads: insufficient print contrast"
            )
        with image.crop(_qr_pixel_box(rect, image.size)) as crop:
            payloads = zxingcpp.read_barcodes(
                crop, formats=zxingcpp.BarcodeFormats(zxingcpp.BarcodeFormat.QRCode)
            )
        if len(payloads) != 1:
            raise RenderValidationError(
                "rendered PDF has no usable QR payloads at a planned placement"
            )
        decoded.append(bytes(payloads[0].bytes))
    return tuple(decoded)


def _qr_pixel_box(rect: RenderRect, size: tuple[int, int]) -> tuple[int, int, int, int]:
    return (
        max(0, math.floor((rect.x_mm - 1.0) * _MM_TO_PIXEL)),
        max(0, math.floor((rect.y_mm - 1.0) * _MM_TO_PIXEL)),
        min(size[0], math.ceil((rect.right_mm + 1.0) * _MM_TO_PIXEL)),
        min(size[1], math.ceil((rect.bottom_mm + 1.0) * _MM_TO_PIXEL)),
    )


__all__ = ["validate_pdf_appearance"]
