"""Input invariants shared by direct shard-document renderers."""

from __future__ import annotations

from ethernity.encoding.framing import FrameType, encode_frame
from ethernity.encoding.qr_payloads import QR_PAYLOAD_CODEC_BASE64, decode_qr_payload
from ethernity.render.types import RenderInputs


def validate_single_shard_fallback_contract(
    inputs: RenderInputs,
    *,
    renderer_label: str,
) -> None:
    """Require one canonical frame to drive both the QR and manual fallback."""

    if len(inputs.frames) != 1:
        raise ValueError(f"{renderer_label} requires exactly one frame")
    if int(inputs.frames[0].frame_type) != int(FrameType.KEY_DOCUMENT):
        raise ValueError(f"{renderer_label} requires a KEY_DOCUMENT frame")

    sections = tuple(inputs.fallback_sections or ())
    if len(sections) != 1:
        raise ValueError(f"{renderer_label} requires exactly one fallback section")
    if sections[0].frame != inputs.frames[0]:
        raise ValueError(f"{renderer_label} fallback frame must match its QR frame")

    if inputs.qr_payloads is None:
        return
    payloads = tuple(inputs.qr_payloads)
    if len(payloads) != 1:
        raise ValueError(f"{renderer_label} requires exactly one QR payload")
    payload = payloads[0]
    expected_frame = encode_frame(inputs.frames[0])
    if isinstance(payload, bytes) and payload == expected_frame:
        return
    try:
        qr_frame = decode_qr_payload(payload, codec=QR_PAYLOAD_CODEC_BASE64)
    except ValueError as exc:
        raise ValueError(f"{renderer_label} QR payload must encode its shard frame") from exc
    if qr_frame != expected_frame:
        raise ValueError(f"{renderer_label} QR payload must encode its shard frame")


__all__ = ["validate_single_shard_fallback_contract"]
