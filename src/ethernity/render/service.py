#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..config import AppConfig
from ..encoding.framing import Frame, encode_frame
from ..encoding.qr_payloads import encode_qr_payload, normalize_qr_payload_encoding
from .doc_types import (
    DOC_TYPE_KIT,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SHARD,
)
from .layout import FallbackSection, RenderInputs


@dataclass(frozen=True)
class RenderService:
    config: AppConfig

    def base_context(self, extra: dict[str, object] | None = None) -> dict[str, object]:
        context: dict[str, object] = {"paper_size": self.config.paper_size}
        if extra:
            context.update(extra)
        return context

    def build_qr_payloads(self, frames: Sequence[Frame]) -> list[bytes | str]:
        encoding = normalize_qr_payload_encoding(self.config.qr_payload_encoding)
        return [encode_qr_payload(encode_frame(frame), encoding=encoding) for frame in frames]

    def qr_inputs(
        self,
        frames: Sequence[Frame],
        output_path: str | Path,
        *,
        qr_payloads: Sequence[bytes | str] | None = None,
        context: dict[str, object] | None = None,
    ) -> RenderInputs:
        return self._build_inputs(
            frames=frames,
            template_path=self.config.template_path,
            output_path=output_path,
            context=context,
            qr_payloads=qr_payloads,
            render_fallback=False,
            doc_type=DOC_TYPE_MAIN,
        )

    def recovery_inputs(
        self,
        frames: Sequence[Frame],
        output_path: str | Path,
        *,
        key_lines: Sequence[str],
        fallback_sections: Sequence[FallbackSection] | None = None,
        context: dict[str, object] | None = None,
    ) -> RenderInputs:
        return self._build_inputs(
            frames=frames,
            template_path=self.config.recovery_template_path,
            output_path=output_path,
            context=context,
            render_qr=False,
            key_lines=key_lines,
            fallback_sections=fallback_sections,
            doc_type=DOC_TYPE_RECOVERY,
        )

    def shard_inputs(
        self,
        frame: Frame,
        output_path: str | Path,
        *,
        shard_index: int,
        shard_total: int,
        qr_payloads: Sequence[bytes | str] | None = None,
        template_path: str | Path | None = None,
        doc_type: str | None = None,
    ) -> RenderInputs:
        return self._build_inputs(
            frames=[frame],
            template_path=template_path or self.config.shard_template_path,
            output_path=output_path,
            context=self.base_context({"shard_index": shard_index, "shard_total": shard_total}),
            qr_payloads=qr_payloads,
            doc_type=doc_type or DOC_TYPE_SHARD,
        )

    def kit_inputs(
        self,
        frames: Sequence[Frame],
        output_path: str | Path,
        *,
        qr_payloads: Sequence[bytes | str],
        context: dict[str, object] | None = None,
    ) -> RenderInputs:
        return self._build_inputs(
            frames=frames,
            template_path=self.config.kit_template_path,
            output_path=output_path,
            context=context,
            qr_payloads=qr_payloads,
            render_fallback=False,
            doc_type=DOC_TYPE_KIT,
        )

    def _build_inputs(
        self,
        *,
        frames: Sequence[Frame],
        template_path: str | Path,
        output_path: str | Path,
        context: dict[str, object] | None,
        qr_payloads: Sequence[bytes | str] | None = None,
        render_qr: bool = True,
        render_fallback: bool = True,
        key_lines: Sequence[str] | None = None,
        fallback_sections: Sequence[FallbackSection] | None = None,
        doc_type: str | None = None,
    ) -> RenderInputs:
        resolved_context = self.base_context(context)
        return RenderInputs(
            frames=frames,
            template_path=template_path,
            output_path=output_path,
            context=resolved_context,
            doc_type=doc_type,
            qr_config=self.config.qr_config,
            qr_payloads=qr_payloads,
            render_qr=render_qr,
            render_fallback=render_fallback,
            key_lines=key_lines,
            fallback_sections=fallback_sections,
        )
