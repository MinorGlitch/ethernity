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
import os
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, cast

from fpdf import FPDF

from ..encoding.framing import encode_frame
from ..qr.codec import QrConfig, qr_bytes
from .doc_types import DOC_TYPE_KIT, DOC_TYPE_RECOVERY
from .fallback import build_fallback_sections_data
from .html_to_pdf import render_html_to_pdf
from .layout import compute_layout
from .pages import build_pages
from .spec import DocumentSpec, document_spec
from .templating import render_template
from .text import page_format
from .types import FallbackSection, RenderInputs

_QR_URL_PREFIX = "https://ethernity.local/qr/"
_RENDER_JOBS_ENV = "ETHERNITY_RENDER_JOBS"
_DEFAULT_QR_WORKERS_CAP = 8
_MIN_QR_TASKS_PER_WORKER = 4
_STACKED_META_TEMPLATE_STYLES = frozenset({"dossier", "maritime", "midnight"})
_DEFAULT_TEMPLATE_STYLE = "ledger"


@dataclass(frozen=True)
class RecoveryMeta:
    passphrase: str | None = None
    passphrase_lines: tuple[str, ...] = ()
    quorum_value: str | None = None
    signing_pub_lines: tuple[str, ...] = ()


def _template_style_name(template_path: str | Path) -> str:
    path = Path(template_path)
    candidate = path.parent.name.strip().lower()
    if candidate in _STACKED_META_TEMPLATE_STYLES or candidate == _DEFAULT_TEMPLATE_STYLE:
        return candidate
    return _DEFAULT_TEMPLATE_STYLE


def _wrap_passphrase(passphrase: str, *, words_per_line: int = 6) -> tuple[str, ...]:
    words = passphrase.split()
    if not words:
        return ()
    return tuple(
        " ".join(words[idx : idx + words_per_line]) for idx in range(0, len(words), words_per_line)
    )


def _parse_recovery_key_lines(key_lines: list[str]) -> RecoveryMeta:
    passphrase_label = "Passphrase:"
    quorum_prefix = "Recover with "
    quorum_suffix = " shard documents."
    signing_pub_label = "Signing public key (hex):"
    passphrase: str | None = None
    quorum_value: str | None = None
    pub_lines: list[str] = []
    collecting_pub = False
    expecting_passphrase = False

    for line in key_lines:
        if expecting_passphrase:
            passphrase = line.strip() or None
            expecting_passphrase = False
            continue

        if line == passphrase_label:
            expecting_passphrase = True
            continue
        if line == signing_pub_label:
            collecting_pub = True
            continue
        if collecting_pub and line.startswith("Signing private key"):
            collecting_pub = False
            continue
        if line.startswith(quorum_prefix) and line.endswith(quorum_suffix):
            quorum_value = line.removeprefix(quorum_prefix).removesuffix(quorum_suffix).strip()
            continue
        if collecting_pub:
            pub_lines.append(line)

    return RecoveryMeta(
        passphrase=passphrase,
        passphrase_lines=_wrap_passphrase(passphrase) if passphrase else (),
        quorum_value=quorum_value,
        signing_pub_lines=tuple(pub_lines),
    )


def render_frames_to_pdf(inputs: RenderInputs) -> None:
    if not inputs.frames:
        raise ValueError("frames cannot be empty")

    base_context = dict(inputs.context)
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
    doc_id = base_context.get("doc_id")
    if not isinstance(doc_id, str):
        doc_id = inputs.frames[0].doc_id.hex()
        base_context["doc_id"] = doc_id

    paper_size = str(base_context.get("paper_size") or "A4")
    doc_type = inputs.doc_type
    if not doc_type:
        raise ValueError("doc_type is required for rendering")
    normalized_doc_type = doc_type.strip().lower()
    key_lines = list(inputs.key_lines) if inputs.key_lines is not None else []
    spec = document_spec(doc_type, paper_size, base_context)

    template_style = _template_style_name(inputs.template_path)
    if template_style == "ledger":
        spec = replace(
            spec,
            header=replace(
                spec.header,
                meta_row_gap_mm=1.2,
                divider_thickness_mm=0.6,
            ),
        )
    elif template_style == "maritime":
        spec = replace(
            spec,
            header=replace(
                spec.header,
                meta_row_gap_mm=1.2,
                stack_gap_mm=1.6,
                divider_thickness_mm=0.4,
            ),
        )
    elif template_style == "dossier":
        spec = replace(
            spec,
            header=replace(
                spec.header,
                meta_row_gap_mm=1.4,
                stack_gap_mm=2.0,
                divider_thickness_mm=0.6,
            ),
        )
    elif template_style == "midnight":
        spec = replace(
            spec,
            header=replace(
                spec.header,
                meta_row_gap_mm=1.0,
                stack_gap_mm=1.6,
                divider_thickness_mm=0.45,
            ),
        )
    recovery_meta = None
    if normalized_doc_type == DOC_TYPE_RECOVERY:
        recovery_meta = _parse_recovery_key_lines(key_lines)
        header_layout = spec.header.layout
        if template_style in _STACKED_META_TEMPLATE_STYLES:
            header_layout = "stacked"
        meta_lines_extra = (
            int(recovery_meta.quorum_value is not None)
            + len(recovery_meta.signing_pub_lines)
            + len(recovery_meta.passphrase_lines)
        )
        spec = replace(
            spec,
            header=replace(
                spec.header,
                layout=header_layout,
                meta_lines_extra=meta_lines_extra,
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
    if normalized_doc_type == DOC_TYPE_RECOVERY:
        recovery_meta = _parse_recovery_key_lines(key_lines)
    spec = spec.with_key_lines(key_lines)
    layout_spec = _layout_spec(spec, doc_id=str(doc_id), page_label="Page 1 / 1")

    keys_first_page_only = bool(spec.keys.first_page_only)
    instructions_first_page_only = bool(spec.instructions.first_page_only)
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

    fallback_sections_data, fallback_state = build_fallback_sections_data(
        inputs,
        spec,
        layout,
    )
    qr_kind = _qr_kind(qr_config)
    qr_resources: dict[str, tuple[str, bytes]] = {}
    if inputs.render_qr:
        qr_resources = _build_qr_resources(qr_payloads, config=qr_config, kind=qr_kind)
    qr_image_builder = functools.partial(_qr_url_for_index, kind=qr_kind)

    pages = build_pages(
        inputs=inputs,
        spec=spec,
        layout=layout,
        layout_rest=layout_rest,
        fallback_lines=fallback_lines,
        qr_payloads=qr_payloads,
        qr_image_builder=qr_image_builder,
        fallback_sections_data=fallback_sections_data,
        fallback_state=fallback_state,
        key_lines=key_lines,
        keys_first_page_only=keys_first_page_only,
    )

    context = _template_context(spec, layout, pages, doc_id=str(doc_id))
    context["shard_index"] = base_context.get("shard_index", 1)
    context["shard_total"] = base_context.get("shard_total", 1)
    context["created_timestamp_utc"] = created_timestamp_utc
    if created_dt is not None:
        context["created_date"] = created_dt.date().isoformat()
    if normalized_doc_type == DOC_TYPE_RECOVERY and recovery_meta is not None:
        context["recovery"] = {
            "passphrase": recovery_meta.passphrase,
            "passphrase_lines": list(recovery_meta.passphrase_lines),
            "quorum_value": recovery_meta.quorum_value,
            "signing_pub_lines": list(recovery_meta.signing_pub_lines),
        }
    html = render_template(inputs.template_path, context)
    render_html_to_pdf(html, inputs.output_path, resources=qr_resources)


def _layout_spec(spec: DocumentSpec, doc_id: str, page_label: str) -> DocumentSpec:
    return spec.with_header(doc_id=doc_id, page_label=page_label)


def _template_context(
    spec: DocumentSpec,
    layout,
    pages: list[dict[str, object]],
    *,
    doc_id: str,
) -> dict[str, object]:
    return {
        "page_size_css": spec.page.size,
        "page_width_mm": layout.page_w,
        "page_height_mm": layout.page_h,
        "margin_mm": layout.margin,
        "usable_width_mm": layout.usable_w,
        "doc_id": doc_id,
        "keys": {"lines": list(spec.keys.lines)},
        "fallback": {"width_mm": layout.fallback_width},
        "pages": pages,
    }


def _qr_kind(config: QrConfig) -> str:
    return str(config.kind or "png").strip().lower()


def _qr_url_for_index(index: int, *, kind: str) -> str:
    return f"{_QR_URL_PREFIX}{index + 1}.{kind}"


def _build_qr_resources(
    qr_payloads: list[bytes | str],
    *,
    config: QrConfig,
    kind: str,
) -> dict[str, tuple[str, bytes]]:
    content_type = _qr_content_type(kind)
    qr_kwargs = dict(_qr_kwargs(config))
    qr_kwargs["kind"] = kind
    qr_worker = functools.partial(qr_bytes, **qr_kwargs)

    images = _render_qr_images(qr_payloads, qr_worker)
    return {
        _qr_url_for_index(index, kind=kind): (content_type, image)
        for index, image in enumerate(images)
    }


def _render_qr_images(
    qr_payloads: list[bytes | str],
    qr_worker: Callable[[bytes | str], bytes],
) -> list[bytes]:
    if not qr_payloads:
        return []

    workers = _resolve_qr_workers(len(qr_payloads))
    if workers <= 1:
        return [qr_worker(payload) for payload in qr_payloads]

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(qr_worker, qr_payloads))


def _resolve_qr_workers(task_count: int) -> int:
    raw = os.environ.get(_RENDER_JOBS_ENV, "").strip().lower()
    explicit = False
    requested: int | None = None
    if raw and raw != "auto":
        try:
            parsed = int(raw)
        except ValueError:
            raise ValueError(f"{_RENDER_JOBS_ENV} must be a positive integer or 'auto'") from None
        if parsed > 0:
            requested = parsed
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


__all__ = [
    "FallbackSection",
    "RenderInputs",
    "render_frames_to_pdf",
]
