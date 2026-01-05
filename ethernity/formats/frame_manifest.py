#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
import json

from ..encoding.framing import DOC_ID_LEN, Frame, FrameType, VERSION
from ..core.models import DocumentPlan

MANIFEST_VERSION = 1


@dataclass(frozen=True)
class Manifest:
    version: int
    doc_id: bytes
    data_frame_type: int
    data_frame_total: int
    payload_len: int
    chunk_size: int
    mode: str | None = None
    key_material: str | None = None
    sealed: bool | None = None
    sharding: dict[str, int] | None = None
    recipients: tuple[str, ...] = ()

    def doc_id_hex(self) -> str:
        return self.doc_id.hex()


def build_manifest_frame(
    *,
    doc_id: bytes,
    data_frame_type: int,
    data_frame_total: int,
    payload_len: int,
    chunk_size: int,
    plan: DocumentPlan | None = None,
) -> Frame:
    data = _manifest_dict(
        doc_id=doc_id,
        data_frame_type=data_frame_type,
        data_frame_total=data_frame_total,
        payload_len=payload_len,
        chunk_size=chunk_size,
        plan=plan,
    )
    encoded = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return Frame(
        version=VERSION,
        frame_type=FrameType.MANIFEST,
        doc_id=doc_id,
        index=0,
        total=1,
        data=encoded,
    )


def parse_manifest_frame(frame: Frame) -> Manifest:
    if frame.frame_type != FrameType.MANIFEST:
        raise ValueError("not a manifest frame")
    data = json.loads(frame.data.decode("utf-8"))
    doc_id = _require_hex_bytes(data, "doc_id", DOC_ID_LEN)
    if doc_id != frame.doc_id:
        raise ValueError("manifest doc_id mismatch")
    version = _require_int(data, "version")
    data_frame_type = _require_int(data, "data_frame_type")
    data_frame_total = _require_int(data, "data_frame_total")
    payload_len = _require_int(data, "payload_len")
    chunk_size = _require_int(data, "chunk_size")
    if data_frame_total <= 0 or payload_len <= 0 or chunk_size <= 0:
        raise ValueError("manifest values must be positive")
    return Manifest(
        version=version,
        doc_id=doc_id,
        data_frame_type=data_frame_type,
        data_frame_total=data_frame_total,
        payload_len=payload_len,
        chunk_size=chunk_size,
        mode=data.get("mode"),
        key_material=data.get("key_material"),
        sealed=data.get("sealed"),
        sharding=data.get("sharding"),
        recipients=tuple(data.get("recipients", ())),
    )


def _manifest_dict(
    *,
    doc_id: bytes,
    data_frame_type: int,
    data_frame_total: int,
    payload_len: int,
    chunk_size: int,
    plan: DocumentPlan | None,
) -> dict[str, object]:
    if len(doc_id) != DOC_ID_LEN:
        raise ValueError(f"doc_id must be {DOC_ID_LEN} bytes")
    data: dict[str, object] = {
        "version": MANIFEST_VERSION,
        "doc_id": doc_id.hex(),
        "data_frame_type": int(data_frame_type),
        "data_frame_total": int(data_frame_total),
        "payload_len": int(payload_len),
        "chunk_size": int(chunk_size),
    }
    if plan is not None:
        data["mode"] = plan.mode.value
        data["key_material"] = plan.key_material.value
        data["sealed"] = bool(plan.sealed)
        if plan.sharding:
            data["sharding"] = {
                "threshold": plan.sharding.threshold,
                "shares": plan.sharding.shares,
            }
        if plan.recipients:
            data["recipients"] = list(plan.recipients)
    return data


def _require_int(data: dict, key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise ValueError(f"manifest {key} must be an int")
    return value


def _require_hex_bytes(data: dict, key: str, length: int) -> bytes:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValueError(f"manifest {key} must be a string")
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"manifest {key} is not valid hex") from exc
    if len(raw) != length:
        raise ValueError(f"manifest {key} must be {length} bytes")
    return raw
