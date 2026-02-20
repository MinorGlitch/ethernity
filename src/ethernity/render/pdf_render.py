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

from __future__ import annotations

import concurrent.futures
import functools
import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, cast

from fpdf import FPDF

from ..encoding.framing import encode_frame
from ..qr.codec import QrConfig, qr_bytes
from ..version import get_ethernity_version
from .copy_catalog import build_copy_bundle
from .doc_types import DOC_TYPE_KIT, DOC_TYPE_MAIN, DOC_TYPE_RECOVERY
from .fallback import FallbackConsumerState, FallbackSectionData, build_fallback_sections_data
from .html_to_pdf import render_html_to_pdf
from .layout import compute_layout
from .pages import build_pages
from .recovery_meta import recovery_meta_lines_extra
from .spec import DocumentSpec, document_spec
from .template_model import DocModel, InstructionsModel, RecoveryModel, TemplateContext
from .template_style import TemplateCapabilities, load_template_style
from .templating import render_template
from .text import page_format
from .types import RenderInputs

_QR_URL_PREFIX = "https://ethernity.local/qr/"
_ASSET_URL_PREFIX = "https://ethernity.local/assets/"
_RENDER_JOBS_ENV = "ETHERNITY_RENDER_JOBS"
_DEFAULT_QR_WORKERS_CAP = 8
_MIN_QR_TASKS_PER_WORKER = 4
_CONTEXT_PASSTHROUGH_KEYS = ("inventory_rows",)
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATE_ASSETS_DIR = _PACKAGE_ROOT / "templates" / "_shared" / "assets"


@dataclass(frozen=True)
class ForgeCopy:
    doc_id_label: str
    generated_utc_label: str
    version: str
    generator_label: str
    protocol_label: str
    backup_system_label: str


def _forge_copy_payload(*, ethernity_version: str) -> ForgeCopy:
    return ForgeCopy(
        doc_id_label="DOC ID",
        generated_utc_label="GENERATED (UTC)",
        version="v2.1",
        generator_label=_generator_label(ethernity_version),
        protocol_label="Ethernity Forge Security Protocols",
        backup_system_label="The Forge Secure Backup System",
    )


def _ethernity_version() -> str:
    return get_ethernity_version()


def _generator_label(ethernity_version: str) -> str:
    normalized = ethernity_version.strip()
    if normalized:
        return f"Ethernity v{normalized}"
    return "Ethernity"


def _uses_uniform_main_qr_capacity(*, doc_type: str, capabilities: TemplateCapabilities) -> bool:
    return doc_type.strip().lower() == DOC_TYPE_MAIN and capabilities.uniform_main_qr_capacity


def _apply_main_qr_grid_overrides(
    *,
    spec: DocumentSpec,
    doc_type: str,
    capabilities: TemplateCapabilities,
) -> DocumentSpec:
    normalized_doc_type = doc_type.strip().lower()
    if normalized_doc_type != DOC_TYPE_MAIN:
        return spec

    qr_grid = spec.qr_grid
    changed = False
    if capabilities.main_qr_grid_size_mm is not None:
        qr_grid = replace(qr_grid, qr_size_mm=float(capabilities.main_qr_grid_size_mm))
        changed = True
    if capabilities.main_qr_grid_max_cols is not None:
        qr_grid = replace(qr_grid, max_cols=int(capabilities.main_qr_grid_max_cols))
        changed = True
    if not changed:
        return spec
    return replace(spec, qr_grid=qr_grid)


def _resolve_created_timestamp(base_context: dict[str, object]) -> tuple[str, datetime | None]:
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
        created_value = created_value.strip()
        if created_value:
            if "UTC" in created_value or created_value.endswith("Z"):
                created_timestamp_utc = created_value
            else:
                created_timestamp_utc = f"{created_value} UTC"

    if created_timestamp_utc is None:
        created_dt = created_dt or datetime.now(timezone.utc)
        created_timestamp_utc = created_dt.strftime("%Y-%m-%d %H:%M UTC")

    base_context["created_timestamp_utc"] = created_timestamp_utc
    if created_dt is not None:
        base_context["created_date"] = created_dt.date().isoformat()
    return created_timestamp_utc, created_dt


def _layout_spec(spec: DocumentSpec, doc_id: str, page_label: str) -> DocumentSpec:
    return spec.with_header(doc_id=doc_id, page_label=page_label)


def _page_size_css(spec: DocumentSpec) -> str:
    if spec.page.width_mm and spec.page.height_mm:
        return f"{float(spec.page.width_mm)}mm {float(spec.page.height_mm)}mm"
    return str(spec.page.size)


def _fallback_rows_used(page: object) -> int:
    blocks = getattr(page, "fallback_blocks", ())
    if not blocks:
        return 0
    used_rows = max(0, len(blocks) - 1)
    for block in blocks:
        title = getattr(block, "title", None)
        lines = getattr(block, "lines", ())
        if title:
            used_rows += 1
        used_rows += len(lines)
    return used_rows


def _write_layout_debug_json(
    *,
    output_path: str | Path,
    inputs: RenderInputs,
    style_name: str,
    layout: object,
    layout_rest: object | None,
    pages: list[object],
) -> None:
    debug_path = inputs.layout_debug_json_path
    if debug_path is None:
        return
    resolved = Path(debug_path).expanduser()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "doc_type": inputs.doc_type,
        "template_path": str(inputs.template_path),
        "style_name": style_name,
        "output_path": str(output_path),
        "layout_first": {
            "line_height_mm": getattr(layout, "line_height", None),
            "fallback_lines_per_page": getattr(layout, "fallback_lines_per_page", None),
            "content_start_y_mm": getattr(layout, "content_start_y", None),
            "margin_mm": getattr(layout, "margin", None),
            "page_height_mm": getattr(layout, "page_h", None),
            "qr_cols": getattr(layout, "cols", None),
            "qr_rows": getattr(layout, "rows", None),
            "qr_per_page": getattr(layout, "per_page", None),
        },
        "layout_rest": (
            None
            if layout_rest is None
            else {
                "line_height_mm": getattr(layout_rest, "line_height", None),
                "fallback_lines_per_page": getattr(layout_rest, "fallback_lines_per_page", None),
                "content_start_y_mm": getattr(layout_rest, "content_start_y", None),
                "qr_cols": getattr(layout_rest, "cols", None),
                "qr_rows": getattr(layout_rest, "rows", None),
                "qr_per_page": getattr(layout_rest, "per_page", None),
            }
        ),
        "pages": [
            {
                "page_num": getattr(page, "page_num", None),
                "fallback_line_capacity": getattr(page, "fallback_line_capacity", None),
                "fallback_row_height_mm": getattr(page, "fallback_row_height_mm", None),
                "fallback_rows_used": _fallback_rows_used(page),
                "fallback_block_count": len(getattr(page, "fallback_blocks", ())),
                "qr_count": len(getattr(page, "qr_items", ())),
            }
            for page in pages
        ],
    }
    resolved.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def render_frames_to_pdf(inputs: RenderInputs) -> None:
    if not inputs.frames:
        raise ValueError("frames cannot be empty")

    base_context = dict(inputs.context)
    created_timestamp_utc, created_dt = _resolve_created_timestamp(base_context)

    doc_id = base_context.get("doc_id")
    if not isinstance(doc_id, str):
        doc_id = inputs.frames[0].doc_id.hex()
        base_context["doc_id"] = doc_id

    paper_size = str(base_context.get("paper_size") or "A4")
    normalized_doc_type = inputs.doc_type.strip().lower()
    key_lines = list(inputs.key_lines) if inputs.key_lines is not None else []
    spec = document_spec(inputs.doc_type, paper_size, base_context)

    style = load_template_style(inputs.template_path)
    spec = replace(
        spec,
        header=replace(
            spec.header,
            meta_row_gap_mm=float(style.header.meta_row_gap_mm),
            stack_gap_mm=float(style.header.stack_gap_mm),
            divider_thickness_mm=float(style.header.divider_thickness_mm),
        ),
    )
    divider_gap_extra_mm = float(style.content_offset.divider_gap_extra_mm)
    if divider_gap_extra_mm and normalized_doc_type in style.content_offset.doc_types:
        spec = replace(
            spec,
            header=replace(
                spec.header,
                divider_gap_mm=float(spec.header.divider_gap_mm) + divider_gap_extra_mm,
            ),
        )
    spec = _apply_main_qr_grid_overrides(
        spec=spec,
        doc_type=normalized_doc_type,
        capabilities=style.capabilities,
    )

    recovery_meta = None
    if normalized_doc_type == DOC_TYPE_RECOVERY:
        if inputs.recovery_meta is None:
            raise ValueError("recovery metadata is required for recovery document rendering")
        recovery_meta = inputs.recovery_meta
        spec = replace(
            spec,
            header=replace(
                spec.header,
                meta_lines_extra=recovery_meta_lines_extra(recovery_meta),
            ),
        )

    layout_spec = _layout_spec(spec, doc_id=str(doc_id), page_label="Page 1 / 1")
    paper_format = page_format(layout_spec.page)

    pdf = FPDF(unit="mm", format=cast(Any, paper_format))
    pdf.set_auto_page_break(False)

    include_instructions = inputs.doc_type != DOC_TYPE_KIT
    include_keys = inputs.doc_type != DOC_TYPE_RECOVERY
    layout, fallback_lines = compute_layout(
        inputs,
        layout_spec,
        pdf,
        key_lines,
        include_keys=include_keys,
        include_instructions=include_instructions,
    )
    key_lines = list(layout.key_lines)
    spec = spec.with_key_lines(key_lines)
    layout_spec = _layout_spec(spec, doc_id=str(doc_id), page_label="Page 1 / 1")

    keys_first_page_only = bool(spec.keys.first_page_only)
    instructions_first_page_only = bool(spec.instructions.first_page_only)
    if _uses_uniform_main_qr_capacity(
        doc_type=inputs.doc_type,
        capabilities=style.capabilities,
    ):
        instructions_first_page_only = False
    layout_rest = None
    if instructions_first_page_only or keys_first_page_only:
        layout_rest, _ = compute_layout(
            inputs,
            layout_spec,
            pdf,
            key_lines,
            include_keys=not keys_first_page_only,
            include_instructions=include_instructions and not instructions_first_page_only,
        )

    qr_config = inputs.qr_config or QrConfig()
    qr_payloads = (
        list(inputs.qr_payloads)
        if inputs.qr_payloads is not None
        else [encode_frame(frame) for frame in inputs.frames]
    )
    if len(qr_payloads) != len(inputs.frames):
        raise ValueError("qr_payloads length must match frames")

    fallback_result = build_fallback_sections_data(inputs, spec, layout)
    fallback_sections_data: list[FallbackSectionData] | None = None
    fallback_state: FallbackConsumerState | None = None
    if fallback_result is not None:
        fallback_sections_data, fallback_state = fallback_result

    qr_kind = _qr_kind(qr_config)
    resources = dict(_build_static_template_resources())
    if inputs.render_qr:
        resources.update(
            _build_qr_resources(
                qr_payloads,
                config=qr_config,
                kind=qr_kind,
                render_jobs=inputs.render_jobs,
            )
        )
    qr_url_for_index = functools.partial(_qr_url_for_index, kind=qr_kind)

    pages = build_pages(
        inputs=inputs,
        spec=spec,
        layout=layout,
        layout_rest=layout_rest,
        fallback_lines=fallback_lines,
        qr_image_builder=qr_url_for_index,
        fallback_sections_data=fallback_sections_data,
        fallback_state=fallback_state,
    )

    scan_hint = (
        "Start at the top-left and follow each row."
        if normalized_doc_type == DOC_TYPE_KIT
        else None
    )
    recovery_view = None
    if recovery_meta is not None:
        recovery_view = RecoveryModel(
            passphrase=recovery_meta.passphrase,
            passphrase_lines=recovery_meta.passphrase_lines,
            quorum_value=recovery_meta.quorum_value,
            signing_pub_lines=recovery_meta.signing_pub_lines,
        )
    context = TemplateContext(
        page_size_css=_page_size_css(spec),
        page_width_mm=layout.page_w,
        page_height_mm=layout.page_h,
        margin_mm=layout.margin,
        usable_width_mm=layout.usable_w,
        doc_id=str(doc_id),
        created_timestamp_utc=created_timestamp_utc,
        doc=DocModel(title=spec.header.title, subtitle=spec.header.subtitle),
        instructions=InstructionsModel(
            label=spec.instructions.label or "Instructions",
            lines=tuple(spec.instructions.lines),
            scan_hint=scan_hint,
        ),
        pages=tuple(pages),
        fallback_width_mm=layout.fallback_width,
        recovery=recovery_view,
    ).to_template_dict()

    context["shard_index"] = base_context.get("shard_index", 1)
    shard_total = base_context.get("shard_total", 1)
    context["shard_total"] = shard_total
    context["shard_threshold"] = base_context.get("shard_threshold", shard_total)
    ethernity_version = _ethernity_version()
    context["ethernity_version"] = ethernity_version
    for key in _CONTEXT_PASSTHROUGH_KEYS:
        if key in base_context:
            context[key] = base_context[key]
    if style.capabilities.inject_forge_copy:
        context["forge_copy"] = asdict(_forge_copy_payload(ethernity_version=ethernity_version))
    if created_dt is not None:
        context["created_date"] = created_dt.date().isoformat()
    template_name = Path(inputs.template_path).name
    context["copy"] = build_copy_bundle(template_name=template_name, context=context)

    html = render_template(inputs.template_path, context)
    render_html_to_pdf(html, inputs.output_path, resources=resources)
    _write_layout_debug_json(
        output_path=inputs.output_path,
        inputs=inputs,
        style_name=style.name,
        layout=layout,
        layout_rest=layout_rest,
        pages=pages,
    )


def _qr_kind(config: QrConfig) -> str:
    return str(config.kind or "png").strip().lower()


def _qr_url_for_index(index: int, *, kind: str) -> str:
    return f"{_QR_URL_PREFIX}{index + 1}.{kind}"


@functools.lru_cache(maxsize=1)
def _build_static_template_resources() -> dict[str, tuple[str, bytes]]:
    resources: dict[str, tuple[str, bytes]] = {}
    icon_font = _TEMPLATE_ASSETS_DIR / "material-symbols-outlined.ttf"
    if icon_font.is_file():
        resources[f"{_ASSET_URL_PREFIX}{icon_font.name}"] = ("font/ttf", icon_font.read_bytes())
    return resources


def _build_qr_resources(
    qr_payloads: list[bytes | str],
    *,
    config: QrConfig,
    kind: str,
    render_jobs: int | Literal["auto"] | None = None,
) -> dict[str, tuple[str, bytes]]:
    content_type = _qr_content_type(kind)
    qr_kwargs = dict(_qr_kwargs(config))
    qr_kwargs["kind"] = kind
    qr_worker = functools.partial(qr_bytes, **qr_kwargs)

    images = _render_qr_images(qr_payloads, qr_worker, render_jobs=render_jobs)
    return {
        _qr_url_for_index(index, kind=kind): (content_type, image)
        for index, image in enumerate(images)
    }


def _render_qr_images(
    qr_payloads: list[bytes | str],
    qr_worker: Callable[[bytes | str], bytes],
    *,
    render_jobs: int | Literal["auto"] | None,
) -> list[bytes]:
    if not qr_payloads:
        return []

    workers = _resolve_qr_workers(len(qr_payloads), configured=render_jobs)
    if workers <= 1:
        return [qr_worker(payload) for payload in qr_payloads]

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(qr_worker, qr_payloads))


def _resolve_qr_workers(
    task_count: int,
    *,
    configured: int | Literal["auto"] | None = None,
) -> int:
    raw = os.environ.get(_RENDER_JOBS_ENV, "").strip().lower()
    explicit = False
    requested: int | None = None
    if raw and raw != "auto":
        try:
            parsed = int(raw)
        except ValueError:
            raise ValueError(f"{_RENDER_JOBS_ENV} must be a positive integer or 'auto'") from None
        if parsed <= 0:
            raise ValueError(f"{_RENDER_JOBS_ENV} must be a positive integer or 'auto'")
        requested = parsed
        explicit = True
    elif configured is not None:
        if configured != "auto":
            requested = configured
            explicit = True

    cpu = os.process_cpu_count() or 1
    if requested is None:
        requested = min(cpu, _DEFAULT_QR_WORKERS_CAP)

    workers = max(1, min(requested, cpu, task_count))
    if not explicit:
        workers = min(workers, max(1, task_count // _MIN_QR_TASKS_PER_WORKER))

    return max(1, workers)


def _qr_content_type(kind: str) -> str:
    if kind == "png":
        return "image/png"
    if kind == "svg":
        return "image/svg+xml"
    if kind in {"jpg", "jpeg"}:
        return "image/jpeg"
    if kind == "gif":
        return "image/gif"
    return "application/octet-stream"


def _qr_kwargs(config: QrConfig) -> dict[str, Any]:
    return vars(config)


__all__ = ["render_frames_to_pdf"]
