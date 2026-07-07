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

"""Build render inputs and QR payloads for document rendering flows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ethernity.config import AppConfig
from ethernity.core.bounds import MAX_QR_PAYLOAD_CHARS
from ethernity.encoding.framing import Frame, encode_frame
from ethernity.encoding.qr_payloads import (
    QR_PAYLOAD_CODEC_BASE64,
    QrPayloadCodec,
    encode_qr_payload,
)
from ethernity.render.doc_types import (
    DOC_TYPE_KIT,
    DOC_TYPE_KIT_INDEX,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SHARD,
)
from ethernity.render.recovery_meta import RecoveryMeta
from ethernity.render.types import FallbackSection, RenderInputs, RenderLineage


@dataclass(frozen=True)
class RenderService:
    """Facade for constructing render inputs from config and frames."""

    config: AppConfig

    def base_context(self, extra: dict[str, object] | None = None) -> dict[str, object]:
        """Build a template context base and merge caller-provided fields."""

        context: dict[str, object] = {"paper_size": self.config.paper_size}
        if extra:
            context.update(extra)
        return context

    def build_qr_payloads(
        self,
        frames: Sequence[Frame],
        *,
        codec: QrPayloadCodec = QR_PAYLOAD_CODEC_BASE64,
    ) -> list[bytes | str]:
        """Encode frames into QR payload text and enforce payload length bounds."""

        payloads: list[bytes | str] = []
        for frame in frames:
            payload = encode_qr_payload(encode_frame(frame), codec=codec)
            if codec == QR_PAYLOAD_CODEC_BASE64:
                if isinstance(payload, bytes):
                    try:
                        payload_text = payload.decode("ascii")
                    except UnicodeDecodeError as exc:
                        raise ValueError("QR payload text must be ASCII") from exc
                else:
                    payload_text = payload
                if len(payload_text) > MAX_QR_PAYLOAD_CHARS:
                    raise ValueError(
                        f"QR payload exceeds MAX_QR_PAYLOAD_CHARS ({MAX_QR_PAYLOAD_CHARS}): "
                        f"{len(payload_text)} chars"
                    )
            payloads.append(payload)
        return payloads

    def qr_inputs(
        self,
        frames: Sequence[Frame],
        output_path: str | Path,
        *,
        qr_payloads: Sequence[bytes | str] | None = None,
        context: dict[str, object] | None = None,
        layout_debug_json_path: str | Path | None = None,
        lineage: RenderLineage,
    ) -> RenderInputs:
        """Build render inputs for the main QR document."""

        return self._build_inputs(
            frames=frames,
            output_path=output_path,
            context=context,
            qr_payloads=qr_payloads,
            render_fallback=False,
            doc_type=DOC_TYPE_MAIN,
            design_name=self.config.design_name,
            layout_debug_json_path=layout_debug_json_path,
            lineage=lineage,
        )

    def recovery_inputs(
        self,
        frames: Sequence[Frame],
        output_path: str | Path,
        *,
        key_lines: Sequence[str],
        recovery_meta: RecoveryMeta,
        fallback_sections: Sequence[FallbackSection] | None = None,
        context: dict[str, object] | None = None,
        layout_debug_json_path: str | Path | None = None,
        lineage: RenderLineage,
    ) -> RenderInputs:
        """Build render inputs for the recovery document."""

        return self._build_inputs(
            frames=frames,
            output_path=output_path,
            context=context,
            render_qr=False,
            key_lines=key_lines,
            recovery_meta=recovery_meta,
            fallback_sections=fallback_sections,
            doc_type=DOC_TYPE_RECOVERY,
            design_name=self.config.design_name,
            layout_debug_json_path=layout_debug_json_path,
            lineage=lineage,
        )

    def shard_inputs(
        self,
        frame: Frame,
        output_path: str | Path,
        *,
        shard_index: int,
        shard_total: int,
        shard_threshold: int | None = None,
        qr_payloads: Sequence[bytes | str] | None = None,
        doc_type: str | None = None,
        design_name: str | None = None,
        layout_debug_json_path: str | Path | None = None,
        lineage: RenderLineage,
    ) -> RenderInputs:
        """Build render inputs for a shard or signing-key shard document."""

        resolved_doc_type = doc_type or DOC_TYPE_SHARD
        return self._build_inputs(
            frames=[frame],
            output_path=output_path,
            context=self.base_context(
                {
                    "shard_index": shard_index,
                    "shard_total": shard_total,
                    "shard_threshold": (
                        shard_total if shard_threshold is None else shard_threshold
                    ),
                }
            ),
            qr_payloads=qr_payloads,
            fallback_sections=(FallbackSection(label=None, frame=frame),),
            doc_type=resolved_doc_type,
            design_name=design_name or self.config.design_name,
            layout_debug_json_path=layout_debug_json_path,
            lineage=lineage,
        )

    def kit_inputs(
        self,
        frames: Sequence[Frame],
        output_path: str | Path,
        *,
        qr_payloads: Sequence[bytes | str],
        context: dict[str, object] | None = None,
        design_name: str | None = None,
        doc_type: str = DOC_TYPE_KIT,
        layout_debug_json_path: str | Path | None = None,
        lineage: RenderLineage,
    ) -> RenderInputs:
        """Build render inputs for the QR-bearing recovery kit document."""

        return self._build_inputs(
            frames=frames,
            output_path=output_path,
            context=context,
            qr_payloads=qr_payloads,
            render_fallback=False,
            doc_type=doc_type,
            design_name=design_name or self.config.design_name,
            layout_debug_json_path=layout_debug_json_path,
            lineage=lineage,
        )

    def kit_index_inputs(
        self,
        output_path: str | Path,
        *,
        context: dict[str, object] | None = None,
        design_name: str | None = None,
        qr_page_count: int | None = None,
        qr_chunk_count: int = 0,
        layout_debug_json_path: str | Path | None = None,
        lineage: RenderLineage,
    ) -> RenderInputs:
        """Build render inputs for the non-payload recovery kit index document."""

        index_context = dict(context or {})
        if qr_page_count is not None:
            index_context.setdefault("kit_qr_page_count", qr_page_count)
        index_context.setdefault("kit_qr_chunk_count", qr_chunk_count)
        return self._build_inputs(
            frames=(),
            output_path=output_path,
            context=index_context,
            qr_payloads=(),
            render_qr=False,
            render_fallback=False,
            doc_type=DOC_TYPE_KIT_INDEX,
            design_name=design_name or self.config.design_name,
            layout_debug_json_path=layout_debug_json_path,
            lineage=lineage,
        )

    def _build_inputs(
        self,
        *,
        frames: Sequence[Frame],
        output_path: str | Path,
        context: dict[str, object] | None,
        qr_payloads: Sequence[bytes | str] | None = None,
        render_qr: bool = True,
        render_fallback: bool = True,
        key_lines: Sequence[str] | None = None,
        recovery_meta: RecoveryMeta | None = None,
        fallback_sections: Sequence[FallbackSection] | None = None,
        doc_type: str,
        design_name: str,
        layout_debug_json_path: str | Path | None = None,
        lineage: RenderLineage,
    ) -> RenderInputs:
        """Construct a `RenderInputs` object with config defaults applied."""

        if lineage is None:
            raise ValueError("render lineage is required")
        resolved_context = self.base_context(context)
        return RenderInputs(
            frames=frames,
            output_path=output_path,
            context=resolved_context,
            doc_type=doc_type,
            design_name=design_name,
            qr_config=self.config.qr_config,
            qr_payloads=qr_payloads,
            render_qr=render_qr,
            render_fallback=render_fallback,
            key_lines=key_lines,
            recovery_meta=recovery_meta,
            fallback_sections=fallback_sections,
            render_jobs=self.config.cli_defaults.runtime.render_jobs,
            layout_debug_json_path=layout_debug_json_path,
            lineage=lineage,
        )
