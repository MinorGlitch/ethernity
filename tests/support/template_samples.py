"""Inputs shared by the template document, shard, and recovery matrices."""

from pathlib import Path

from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.page_sizes import PaperSize
from ethernity.render.designs import list_design_definitions
from ethernity.render.recovery_meta import build_recovery_meta
from ethernity.render.types import DocumentOrigin, FallbackSection, RenderInputs

DESIGNS = tuple(list_design_definitions())

SIZES = (
    PaperSize("A4", "A4", 210, 297),
    PaperSize("LETTER", "Letter", 215.9, 279.4),
    PaperSize("MINIMUM", "Minimum", 210, 279.4),
    PaperSize("CUSTOM", "Custom", 260, 360),
    PaperSize("A5", "A5", 148, 210),
)


def inputs_for(
    tmp_path: Path,
    design: str,
    kind: str,
    *,
    size: PaperSize = SIZES[0],
    payload_size: int = 400,
    phrase: str = "alpha bravo charlie",
) -> RenderInputs:
    shard = kind in ("shard", "signing_key_shard")
    frame = Frame(
        VERSION,
        FrameType.KEY_DOCUMENT if shard else FrameType.MAIN_DOCUMENT,
        b"\x88" * 8,
        0,
        1,
        b"s" * payload_size,
    )
    return RenderInputs(
        frames=() if kind == "kit_index" else (frame,),
        output_path=tmp_path / "document.pdf",
        design_name=design,
        doc_type=kind,
        page_size=size,
        origin=DocumentOrigin(kind="root_backup"),
        context={
            "created_timestamp_utc": "2026-07-06 12:00 UTC",
            "doc_id": "88" * 8,
            "shard_index": 1,
            "shard_total": 3,
            "shard_threshold": 2,
        },
        render_qr=kind in ("main", "kit", "shard", "signing_key_shard"),
        render_fallback=kind == "recovery" or shard,
        recovery_meta=build_recovery_meta(
            passphrase=phrase, quorum_threshold=2, quorum_shares=3, signing_pub=b"\x31" * 32
        )
        if kind == "recovery"
        else None,
        fallback_sections=(FallbackSection("SHARD PAYLOAD" if shard else "MAIN FRAME", frame),)
        if kind == "recovery" or shard
        else (),
    )
