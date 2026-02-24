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

from ..config import AppConfig
from ..core.bounds import MAX_QR_PAYLOAD_CHARS
from ..encoding.framing import Frame, encode_frame
from ..encoding.qr_payloads import encode_qr_payload
from .doc_types import (
    DOC_TYPE_KIT,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SHARD,
)
from .recovery_meta import RecoveryMeta
from .types import FallbackSection, RenderInputs


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

    def build_qr_payloads(self, frames: Sequence[Frame]) -> list[bytes | str]:
        """Encode frames into QR payload text and enforce payload length bounds."""

        payloads: list[bytes | str] = []
        for frame in frames:
            payload = encode_qr_payload(encode_frame(frame))
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
    ) -> RenderInputs:
        """Build render inputs for the main QR document."""

        return self._build_inputs(
            frames=frames,
            template_path=self.config.template_path,
            output_path=output_path,
            context=context,
            qr_payloads=qr_payloads,
            render_fallback=False,
            doc_type=DOC_TYPE_MAIN,
            layout_debug_json_path=layout_debug_json_path,
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
    ) -> RenderInputs:
        """Build render inputs for the recovery document."""

        return self._build_inputs(
            frames=frames,
            template_path=self.config.recovery_template_path,
            output_path=output_path,
            context=context,
            render_qr=False,
            key_lines=key_lines,
            recovery_meta=recovery_meta,
            fallback_sections=fallback_sections,
            doc_type=DOC_TYPE_RECOVERY,
            layout_debug_json_path=layout_debug_json_path,
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
        template_path: str | Path | None = None,
        doc_type: str | None = None,
        layout_debug_json_path: str | Path | None = None,
    ) -> RenderInputs:
        """Build render inputs for a shard or signing-key shard document."""

        return self._build_inputs(
            frames=[frame],
            template_path=template_path or self.config.shard_template_path,
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
            doc_type=doc_type or DOC_TYPE_SHARD,
            layout_debug_json_path=layout_debug_json_path,
        )

    def kit_inputs(
        self,
        frames: Sequence[Frame],
        output_path: str | Path,
        *,
        qr_payloads: Sequence[bytes | str],
        context: dict[str, object] | None = None,
        template_path: str | Path | None = None,
        layout_debug_json_path: str | Path | None = None,
    ) -> RenderInputs:
        """Build render inputs for the recovery kit document/index."""

        return self._build_inputs(
            frames=frames,
            template_path=template_path or self.config.kit_template_path,
            output_path=output_path,
            context=context,
            qr_payloads=qr_payloads,
            render_fallback=False,
            doc_type=DOC_TYPE_KIT,
            layout_debug_json_path=layout_debug_json_path,
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
        recovery_meta: RecoveryMeta | None = None,
        fallback_sections: Sequence[FallbackSection] | None = None,
        doc_type: str,
        layout_debug_json_path: str | Path | None = None,
    ) -> RenderInputs:
        """Construct a `RenderInputs` object with config defaults applied."""

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
            recovery_meta=recovery_meta,
            fallback_sections=fallback_sections,
            render_jobs=self.config.cli_defaults.runtime.render_jobs,
            layout_debug_json_path=layout_debug_json_path,
        )
