"""Read-only file and print estimates using the backup encoder and measured renderer."""

from __future__ import annotations

from dataclasses import dataclass

from ethernity.core.bounds import MAX_CIPHERTEXT_BYTES
from ethernity.crypto import signing
from ethernity.encoding import framing
from ethernity.encoding.chunking import chunk_payload
from ethernity.formats.manifest import BackupFile
from ethernity.qr.capacity import choose_frame_chunk_size
from ethernity.render.backend_dispatch import plan_document_summary
from ethernity.render.service import RenderService
from ethernity.render.types import DocumentOrigin
from ethernity.workflows.execution import BackupRequest, prepare_backup
from ethernity.workflows.shared.standalone import encode_standalone_backup


@dataclass(frozen=True, slots=True)
class BackupEstimate:
    """Exact input totals and estimated main-document pagination, without encryption."""

    file_count: int
    input_bytes: int
    document_bytes: int
    backup_pages: int
    qr_count: int


def estimate_backup(request: BackupRequest) -> BackupEstimate:
    """Load and compress the selected files, then measure estimated QR pages.

    This performs no KDF, encryption, secret generation, or filesystem writes. Pagination
    uses the chosen design's real measured planner. The synthetic frame data has the
    expected encrypted length; it cannot be used to recover any input file.
    """

    prepared = prepare_backup(request)
    parts = [
        BackupFile(path=item.relative_path, data=item.data, mtime=item.mtime)
        for item in prepared.input_files
    ]
    document, raw_payload = encode_standalone_backup(
        parts,
        sealed=prepared.plan.sealed,
        signing_seed=None if prepared.plan.sealed else bytes(32),
        input_origin=prepared.input_origin,
        input_roots=prepared.input_roots,
        payload_codec_mode=prepared.config.cli_defaults.backup.payload_codec,
    )
    ciphertext_size = _estimated_age_size(len(document))
    if ciphertext_size > MAX_CIPHERTEXT_BYTES:
        raise ValueError(
            f"Estimated backup exceeds the encrypted size limit ({MAX_CIPHERTEXT_BYTES} bytes)."
        )
    doc_id = bytes(framing.DOC_ID_LEN)
    codec = prepared.config.cli_defaults.backup.qr_payload_codec
    chunk_size = choose_frame_chunk_size(
        ciphertext_size,
        preferred_chunk_size=prepared.config.qr_chunk_size,
        doc_id=doc_id,
        frame_type=framing.FrameType.MAIN_DOCUMENT,
        qr_config=prepared.config.qr_config,
        payload_codec=codec,
    )
    frames = chunk_payload(
        b"\xff" * ciphertext_size,
        doc_id=doc_id,
        frame_type=framing.FrameType.MAIN_DOCUMENT,
        chunk_size=chunk_size,
    )
    auth_payload = signing.encode_auth_payload(bytes(32), sign_pub=bytes(32), signature=bytes(64))
    frames.append(
        framing.Frame(
            version=framing.VERSION,
            frame_type=framing.FrameType.AUTH,
            doc_id=doc_id,
            index=0,
            total=1,
            data=auth_payload,
        )
    )
    service = RenderService(prepared.config)
    inputs = service.qr_inputs(
        frames,
        "unused-backup-estimate.pdf",
        qr_payloads=service.build_qr_payloads(frames, codec=codec),
        origin=DocumentOrigin(kind="root_backup"),
    )
    summary = plan_document_summary(inputs)
    return BackupEstimate(
        file_count=len(prepared.input_files),
        input_bytes=len(raw_payload),
        document_bytes=len(document),
        backup_pages=summary.page_count,
        qr_count=len(frames),
    )


def _estimated_age_size(plaintext_size: int) -> int:
    # age v1: one scrypt stanza, a 16-byte payload nonce, and a 16-byte AEAD tag
    # for each 64 KiB stream chunk. A two-digit work factor gives a 150-byte
    # header. See https://age-encryption.org/v1, "Payload" and "scrypt recipient".
    # This is an estimate because the backend chooses the stanza work factor.
    stream_chunks = max(1, (plaintext_size + 65535) // 65536)
    return plaintext_size + 150 + 16 + 16 * stream_chunks


__all__ = ["BackupEstimate", "estimate_backup"]
