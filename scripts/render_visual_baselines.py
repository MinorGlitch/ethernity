#!/usr/bin/env python3
"""Generate direct-PDF visual diagnostic artifacts for renderer review work."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Literal, cast

from PIL import Image, ImageChops, ImageOps, ImageStat
from pypdf import PdfReader

from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.render import render_frames_to_pdf
from ethernity.render.designs import list_design_manifests
from ethernity.render.doc_types import (
    DOC_TYPE_KIT,
    DOC_TYPE_KIT_INDEX,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SHARD,
    DOC_TYPE_SIGNING_KEY_SHARD,
)
from ethernity.render.proofs import extract_pdf_text
from ethernity.render.recovery_meta import build_recovery_meta
from ethernity.render.types import FallbackSection, RenderInputs, RenderLineage, RenderResult

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


@dataclass(frozen=True)
class VisualBaselineCase:
    """One design/document combination that can be rendered as a migration reference."""

    design: str
    doc_type: str

    @property
    def case_id(self) -> str:
        return f"{self.design}/{self.doc_type}"


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


def discover_design_cases() -> tuple[VisualBaselineCase, ...]:
    """Discover supported design/document pairs from built-in design manifests."""

    cases: list[VisualBaselineCase] = []
    for design, manifest in list_design_manifests().items():
        for doc_type in sorted(manifest.documents):
            cases.append(VisualBaselineCase(design=design, doc_type=doc_type))
    return tuple(cases)


def filter_design_cases(
    cases: Sequence[VisualBaselineCase],
    *,
    designs: Sequence[str] = (),
    doc_types: Sequence[str] = (),
) -> tuple[VisualBaselineCase, ...]:
    """Filter discovered cases using optional design and document selections."""

    selected_designs = frozenset(designs)
    selected_doc_types = frozenset(doc_types)
    return tuple(
        case
        for case in cases
        if (not selected_designs or case.design in selected_designs)
        and (not selected_doc_types or case.doc_type in selected_doc_types)
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
) -> BaselineReport:
    """Render selected visual diagnostic artifacts and return the manifest model."""

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
        )

        case_reports.append(
            BaselineCaseReport(
                case_id=case.case_id,
                design=case.design,
                doc_type=case.doc_type,
                direct_supported=supports_direct_baseline(case),
                artifacts=(artifact,),
                diagnostics=(),
            )
        )

    report = BaselineReport(
        schema_version=3,
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
) -> BaselineArtifact:
    """Render one case PDF and summarize its artifact evidence."""

    case_dir = output_dir / case.design / case.doc_type
    case_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = case_dir / f"{renderer_name}.pdf"
    inputs = build_sample_inputs(case, pdf_path)

    renderer(inputs)

    reader = PdfReader(str(pdf_path))
    text = extract_pdf_text(reader)
    raster = rasterize_pdf_pages(
        pdf_path,
        case_dir / renderer_name,
        mode=rasterize,
        dpi=raster_dpi,
    )
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
    )


def build_sample_inputs(case: VisualBaselineCase, output_path: Path) -> RenderInputs:
    """Build stable synthetic render inputs for a visual baseline case."""

    context = _base_context()
    if case.doc_type == DOC_TYPE_MAIN:
        frames = tuple(
            _frame(
                FrameType.MAIN_DOCUMENT,
                index=index,
                total=4,
                data=f"visual-baseline-main-fragment-{index}".encode("ascii"),
            )
            for index in range(4)
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
        )

    if case.doc_type == DOC_TYPE_RECOVERY:
        auth_frame = _frame(FrameType.AUTH, index=0, total=1, data=b"visual-baseline-auth")
        main_frame = _frame(
            FrameType.MAIN_DOCUMENT,
            index=0,
            total=1,
            data=b"visual-baseline-recovery-main-payload",
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
                passphrase="alpha bravo charlie delta echo foxtrot",
                quorum_threshold=2,
                quorum_shares=3,
                signing_pub=b"\x31" * 32,
            ),
            fallback_sections=(
                FallbackSection(label="AUTH FRAME", frame=auth_frame),
                FallbackSection(label="MAIN FRAME", frame=main_frame),
            ),
        )

    if case.doc_type in {DOC_TYPE_SHARD, DOC_TYPE_SIGNING_KEY_SHARD}:
        frame = _frame(
            FrameType.KEY_DOCUMENT,
            index=0,
            total=1,
            data=f"visual-baseline-{case.doc_type}-payload".encode("ascii"),
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
        )

    if case.doc_type == DOC_TYPE_KIT:
        frames = tuple(
            _frame(
                FrameType.MAIN_DOCUMENT,
                index=index,
                total=3,
                data=f"visual-baseline-kit-frame-{index}".encode("ascii"),
            )
            for index in range(3)
        )
        kit_context = _kit_context(context)
        return RenderInputs(
            frames=frames,
            output_path=output_path,
            context=kit_context,
            doc_type=case.doc_type,
            design_name=case.design,
            lineage=RenderLineage(kind="recovery_kit"),
            qr_payloads=(
                "ETK1:kit-shell-html",
                "ETK1:kit-chunk-0001",
                "ETK1:kit-chunk-0002",
            ),
            render_qr=True,
            render_fallback=False,
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
    parser.add_argument("--rasterize", choices=("auto", "always", "never"), default="auto")
    parser.add_argument("--raster-dpi", type=int, default=144)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    cases = filter_design_cases(
        discover_design_cases(),
        designs=tuple(args.design),
        doc_types=tuple(args.doc_type),
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


def _base_context() -> dict[str, object]:
    return {
        "paper_size": "A4",
        "doc_id": _DOC_ID.hex(),
        "created_timestamp_utc": _CREATED_TIMESTAMP_UTC,
    }


def _kit_context(base_context: dict[str, object]) -> dict[str, object]:
    context = dict(base_context)
    context.update(
        {
            "kit_qr_page_count": 1,
            "kit_qr_chunk_count": 3,
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
