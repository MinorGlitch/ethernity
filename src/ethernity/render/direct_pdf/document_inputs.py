"""Prepare document metadata, validate inputs, and paginate QR images."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from ethernity.encoding.framing import encode_frame
from ethernity.qr.codec import QrConfig, qr_bytes
from ethernity.render.copy_catalog import build_copy_bundle, build_instruction_copy
from ethernity.render.design_style import DesignCapabilities, load_design_style
from ethernity.render.direct_pdf.page_geometry import resolve_page_geometry
from ethernity.render.direct_pdf.shard_frame_consistency import validate_shard_frame_consistency
from ethernity.render.doc_types import (
    DOC_TYPE_KIT_INDEX,
    DOC_TYPE_RECOVERY,
)
from ethernity.render.types import (
    DocumentOrigin,
    RenderInputs,
)
from ethernity.version import get_ethernity_version


@dataclass(frozen=True)
class DocumentRenderContext:
    """Document metadata and printed copy shared by direct-PDF designs."""

    doc_type: str
    doc_id: str
    created_timestamp_utc: str
    copy: dict[str, object]
    instructions_label: str
    instruction_lines: tuple[str, ...]
    footer_left: str
    footer_right: str
    origin: DocumentOrigin
    values: dict[str, object]
    capabilities: DesignCapabilities

    def document_id_label(self, default: str = "Document ID") -> str:
        """Distinguish an update's own identity from its original backup."""

        return "Update ID" if self.origin.kind == "extension" else default


@dataclass(frozen=True)
class QrPayloadItem:
    """One QR payload and pre-rendered image."""

    payload_index: int
    payload: bytes | str
    image: bytes

    @property
    def label_index(self) -> int:
        return self.payload_index + 1


def build_document_render_context(inputs: RenderInputs, *, doc_type: str) -> DocumentRenderContext:
    """Build printed copy, instructions, and document metadata."""

    base_context = dict(inputs.context)
    created_timestamp_utc = resolve_created_timestamp(base_context)
    doc_id = resolve_doc_id(inputs, base_context)
    base_context["doc_id"] = doc_id
    base_context["origin"] = origin_payload(inputs.origin)
    page = resolve_page_geometry(inputs)
    base_context["paper_size"] = page.paper_size
    copy = build_copy_bundle(doc_type=doc_type, context=base_context)
    instructions = build_instruction_copy(doc_type=doc_type, context=base_context)
    return DocumentRenderContext(
        doc_type=doc_type,
        doc_id=doc_id,
        created_timestamp_utc=created_timestamp_utc,
        copy=copy,
        instructions_label=instructions.label,
        instruction_lines=instructions.lines,
        footer_left=generator_label(get_ethernity_version()),
        footer_right=str(copy.get("footer_guidance") or ""),
        origin=inputs.origin,
        values=base_context,
        capabilities=load_design_style(inputs.design_name).capabilities,
    )


def validate_qr_inputs(
    inputs: RenderInputs,
    *,
    expected_doc_type: str,
    supported_paper_sizes: frozenset[str] | None = None,
) -> None:
    """Validate QR-only document inputs."""

    if inputs.doc_type.strip().lower() != expected_doc_type:
        raise ValueError(f"direct PDF renderer only supports {expected_doc_type} documents")
    if not inputs.render_qr:
        raise ValueError("direct PDF QR renderer requires QR rendering")
    if inputs.render_fallback:
        raise ValueError("direct PDF QR renderer does not render fallback text")
    if not inputs.frames:
        raise ValueError("frames cannot be empty for direct PDF QR rendering")
    _validate_paper_and_png(inputs, supported_paper_sizes=supported_paper_sizes)


def validate_recovery_inputs(
    inputs: RenderInputs,
    *,
    supported_paper_sizes: frozenset[str] | None = None,
) -> None:
    """Validate recovery-document inputs."""

    if inputs.doc_type.strip().lower() != DOC_TYPE_RECOVERY:
        raise ValueError("direct PDF recovery renderer only supports recovery documents")
    if inputs.render_qr or not inputs.render_fallback:
        raise ValueError("direct PDF recovery renderer requires fallback-only rendering")
    if inputs.recovery_meta is None:
        raise ValueError("recovery_meta is required for direct PDF recovery rendering")
    if not inputs.fallback_sections:
        raise ValueError("fallback_sections are required for direct PDF recovery rendering")
    resolve_page_geometry(inputs, supported_paper_sizes=supported_paper_sizes)


def validate_single_qr_fallback_inputs(
    inputs: RenderInputs,
    *,
    expected_doc_type: str,
    supported_paper_sizes: frozenset[str] | None = None,
) -> None:
    """Validate single-QR plus fallback document inputs."""

    if inputs.doc_type.strip().lower() != expected_doc_type:
        raise ValueError(f"direct PDF renderer only supports {expected_doc_type} documents")
    if not inputs.render_qr or not inputs.render_fallback:
        raise ValueError("direct PDF shard renderer requires QR and fallback rendering")
    validate_shard_frame_consistency(
        inputs,
        renderer_label="direct PDF shard renderer",
    )
    _validate_paper_and_png(inputs, supported_paper_sizes=supported_paper_sizes)


def validate_kit_index_inputs(inputs: RenderInputs) -> None:
    """Validate an inventory document with no encoded payloads."""

    if inputs.doc_type.strip().lower() != DOC_TYPE_KIT_INDEX:
        raise ValueError("direct PDF kit-index renderer only supports kit-index documents")
    if inputs.render_qr or inputs.render_fallback:
        raise ValueError("direct PDF kit-index renderer does not render QR or fallback text")
    if inputs.frames:
        raise ValueError("direct PDF kit-index renderer expects no frames")
    resolve_page_geometry(inputs)


def _validate_paper_and_png(
    inputs: RenderInputs,
    *,
    supported_paper_sizes: frozenset[str] | None = None,
) -> None:
    """Validate shared renderer page and QR image constraints."""

    resolve_page_geometry(inputs, supported_paper_sizes=supported_paper_sizes)
    qr_config = inputs.qr_config or QrConfig()
    qr_kind = str(qr_config.kind or "png").strip().lower()
    if qr_kind != "png":
        raise ValueError("direct PDF renderer currently supports PNG QR images only")


def resolved_qr_payloads(inputs: RenderInputs) -> tuple[bytes | str, ...]:
    """Resolve QR payloads from explicit payload inputs or encoded frames."""

    if inputs.qr_payloads is not None:
        payloads = tuple(inputs.qr_payloads)
    else:
        payloads = tuple(encode_frame(frame) for frame in inputs.frames)
    if len(payloads) != len(inputs.frames):
        raise ValueError("qr_payloads length must match frames")
    return payloads


def resolved_single_qr_payload(inputs: RenderInputs) -> bytes | str:
    """Resolve the only QR payload for single-payload documents."""

    if inputs.qr_payloads is not None:
        payloads = tuple(inputs.qr_payloads)
    else:
        payloads = (encode_frame(inputs.frames[0]),)
    if len(payloads) != 1:
        raise ValueError("direct PDF shard renderer requires exactly one QR payload")
    return payloads[0]


def qr_payload_items(
    payloads: Sequence[bytes | str],
    *,
    config: QrConfig,
) -> tuple[QrPayloadItem, ...]:
    """Build QR payload items with pre-rendered PNG images."""

    return tuple(
        QrPayloadItem(
            payload_index=index,
            payload=payload,
            image=qr_image(payload, config=config),
        )
        for index, payload in enumerate(payloads)
    )


def qr_image(payload: bytes | str, *, config: QrConfig) -> bytes:
    """Render one QR payload into PNG bytes."""

    return qr_bytes(
        payload,
        error=config.error,
        scale=config.scale,
        border=config.border,
        kind="png",
        dark=config.dark,
        light=config.light,
        version=config.version,
        mask=config.mask,
        micro=config.micro,
        boost_error=config.boost_error,
    )


def non_negative_int(value: object, *, default: int) -> int:
    """Parse an integer value, falling back for non-integers and clamping below zero."""

    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(0, value)


def resolve_created_timestamp(base_context: dict[str, object]) -> str:
    """Normalize created timestamp fields for printed document headers."""

    created_value = base_context.get("created_timestamp_utc")
    if created_value is None:
        created_value = base_context.get("created_date")
    created_dt = None
    created_timestamp_utc = None
    if isinstance(created_value, datetime):
        if created_value.tzinfo is None:
            created_value = created_value.replace(tzinfo=UTC)
        created_dt = created_value.astimezone(UTC)
    elif isinstance(created_value, date):
        created_dt = datetime.combine(created_value, datetime.min.time(), tzinfo=UTC)
    elif isinstance(created_value, str):
        created_timestamp_utc, created_dt = timestamp_from_string(created_value)
    if created_timestamp_utc is None:
        created_dt = created_dt or datetime.now(UTC)
        created_timestamp_utc = created_dt.strftime("%Y-%m-%d %H:%M UTC")
    base_context["created_timestamp_utc"] = created_timestamp_utc
    if created_dt is not None:
        base_context["created_date"] = created_dt.date().isoformat()
    return created_timestamp_utc


def resolve_doc_id(inputs: RenderInputs, base_context: dict[str, object]) -> str:
    """Resolve the document id shown in document headers."""

    doc_id = base_context.get("doc_id")
    if isinstance(doc_id, str) and doc_id.strip():
        return doc_id.strip()
    if not inputs.frames:
        raise ValueError("doc_id context is required when rendering without frames")
    return inputs.frames[0].doc_id.hex()


def timestamp_from_string(value: str) -> tuple[str | None, datetime | None]:
    """Parse or preserve a user-provided UTC timestamp string."""

    created_value = value.strip()
    if not created_value:
        return None, None
    parsed_value = created_value
    if created_value.endswith(" UTC"):
        parsed_value = f"{created_value[:-4].strip()}+00:00"
    elif created_value.endswith("Z"):
        parsed_value = f"{created_value[:-1]}+00:00"
    try:
        parsed_dt = datetime.fromisoformat(parsed_value)
    except ValueError:
        parsed_dt = None
    if parsed_dt is not None:
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=UTC)
        return None, parsed_dt.astimezone(UTC)
    if "UTC" in created_value or created_value.endswith("Z"):
        return created_value, None
    return f"{created_value} UTC", None


def origin_payload(origin: DocumentOrigin) -> dict[str, object]:
    """Convert render origin to the mapping expected by copy catalogs."""

    payload: dict[str, object] = {
        "kind": origin.kind,
        "extension_index": origin.extension_index,
    }
    if origin.kind == "extension":
        payload["update_mode"] = origin.update_mode.value
        if origin.root_doc_id is not None:
            payload["root_doc_id"] = origin.root_doc_id
    return payload


def generator_label(ethernity_version: str) -> str:
    """Build the generator label shown in rendered document metadata."""

    normalized = ethernity_version.strip()
    if normalized:
        return f"Ethernity v{normalized}"
    return "Ethernity"


__all__ = [
    "QrPayloadItem",
    "DocumentRenderContext",
    "build_document_render_context",
    "generator_label",
    "origin_payload",
    "non_negative_int",
    "qr_image",
    "qr_payload_items",
    "resolved_qr_payloads",
    "resolved_single_qr_payload",
    "resolve_created_timestamp",
    "resolve_doc_id",
    "timestamp_from_string",
    "validate_kit_index_inputs",
    "validate_qr_inputs",
    "validate_recovery_inputs",
    "validate_single_qr_fallback_inputs",
]
