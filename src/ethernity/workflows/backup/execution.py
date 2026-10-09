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

"""Generate QR, recovery, and shard backup documents."""

from __future__ import annotations

from pathlib import Path

from ethernity import render as render_module
from ethernity.config import AppConfig
from ethernity.core.bounds import MAX_CIPHERTEXT_BYTES
from ethernity.core.models import DocumentPlan, SigningSeedMode
from ethernity.crypto import (
    decrypt_bytes,
    encrypt_bytes_with_passphrase,
    sharding as sharding_module,
    signing as signing_module,
)
from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.crypto.passphrases import normalize_valid_bip39_whitespace
from ethernity.crypto.sharding import ShardPayload
from ethernity.crypto.signing import derive_public_key
from ethernity.encoding.chunking import chunk_payload
from ethernity.encoding.framing import VERSION, Frame, FrameType, decode_frame
from ethernity.encoding.qr_payloads import QrPayloadCodec, decode_qr_payload
from ethernity.formats import (
    document_codec as document_codec_module,
    payload_codec as payload_codec_module,
)
from ethernity.formats.manifest import BackupFile
from ethernity.publication import PublicationDurability
from ethernity.qr.capacity import choose_frame_chunk_size
from ethernity.qr.scan import scan_qr_payloads
from ethernity.render.checks import RenderValidationError
from ethernity.render.fallback_labels import AUTH_FALLBACK_LABEL, MAIN_FALLBACK_LABEL
from ethernity.render.layout_debug import (
    layout_debug_json_path,
    resolve_layout_debug_dir,
)
from ethernity.render.recovery_kit_index import (
    build_recovery_kit_index_inventory_rows,
    resolve_recovery_kit_index_style,
)
from ethernity.render.recovery_lines import append_signing_key_lines
from ethernity.render.recovery_meta import RecoveryMeta, build_recovery_meta
from ethernity.render.service import RenderService
from ethernity.render.types import DocumentOrigin, RenderInputs, RenderResult
from ethernity.render.validation import validate_rendered_pdf_document
from ethernity.workflows.shared import issue_codes
from ethernity.workflows.shared.events import (
    emit_event,
    emit_phase,
    emit_progress,
    report_render_page,
)
from ethernity.workflows.shared.notices import warn
from ethernity.workflows.shared.operation_types import BackupResult, InputFile
from ethernity.workflows.shared.outputs import (
    commit_prepared_output_dir,
    discard_prepared_output_dir,
    prepare_backup_output_dir,
)
from ethernity.workflows.shared.shard_rendering import ShardRenderContext, render_shard_documents
from ethernity.workflows.shared.standalone import encode_standalone_backup


def _expected_kit_index_component_ids(inputs: RenderInputs) -> tuple[str, ...]:
    rows = inputs.context.get("inventory_rows")
    if not isinstance(rows, list):
        return ()
    component_ids: list[str] = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("component_id"), str):
            component_ids.append(row["component_id"])
    return tuple(component_ids)


def _update_kit_index_qr_page_count(
    kit_index_inputs: RenderInputs | None,
    render_result: RenderResult,
) -> None:
    if kit_index_inputs is None:
        return
    if render_result.document_summary is None:
        raise RenderValidationError("rendered QR document is missing its document summary")
    if render_result.document_summary.page_count > 0:
        kit_index_inputs.context["kit_qr_page_count"] = render_result.document_summary.page_count


def _prepare_backup_document(
    input_files: list[InputFile],
    plan: DocumentPlan,
    sign_priv: bytes,
    input_origin: str,
    input_roots: list[str],
    payload_codec_mode: payload_codec_module.PayloadEncodingMode = (
        payload_codec_module.PAYLOAD_ENCODING_AUTO
    ),
) -> tuple[bytes, bytes]:
    """Encode input files and return the backup document bytes and raw file payload."""
    parts = [
        BackupFile(path=item.relative_path, data=item.data, mtime=item.mtime)
        for item in input_files
    ]
    return encode_standalone_backup(
        parts,
        sealed=plan.sealed,
        signing_seed=sign_priv if not plan.sealed else None,
        input_origin=input_origin,
        input_roots=input_roots,
        payload_codec_mode=payload_codec_mode,
    )


def _create_auth_frame(
    doc_id: bytes,
    doc_hash: bytes,
    sign_priv: bytes,
    sign_pub: bytes,
) -> Frame:
    """Create the authentication frame."""
    auth_signature = signing_module.sign_auth(doc_hash, sign_pub=sign_pub, sign_priv=sign_priv)
    auth_payload = signing_module.encode_auth_payload(
        doc_hash,
        sign_pub=sign_pub,
        signature=auth_signature,
    )
    return Frame(
        version=VERSION,
        frame_type=FrameType.AUTH,
        doc_id=doc_id,
        index=0,
        total=1,
        data=auth_payload,
    )


def _create_shard_payloads(
    plan: DocumentPlan,
    passphrase: str,
    doc_hash: bytes,
    sign_priv: bytes,
    sign_pub: bytes,
    shard_signing_key: bool,
) -> tuple[list[ShardPayload], list[ShardPayload]]:
    """Create shard payloads for passphrase and signing key.

    Returns (shard_payloads, signing_key_shard_payloads).
    """
    plan_sharding = plan.sharding
    signing_key_sharding = plan.signing_seed_sharding or plan.sharding
    shard_payloads: list[ShardPayload] = []
    signing_key_shard_payloads: list[ShardPayload] = []

    if plan_sharding is not None:
        shard_payloads = sharding_module.split_passphrase(
            passphrase,
            threshold=plan_sharding.threshold,
            shares=plan_sharding.shares,
            doc_hash=doc_hash,
            sign_priv=sign_priv,
            sign_pub=sign_pub,
        )
        if shard_signing_key:
            if signing_key_sharding is None:
                raise ValueError("signing key sharding requires a shard quorum")
            signing_key_shard_payloads = sharding_module.split_signing_seed(
                sign_priv,
                threshold=signing_key_sharding.threshold,
                shares=signing_key_sharding.shares,
                doc_hash=doc_hash,
                sign_priv=sign_priv,
                sign_pub=sign_pub,
            )

    return shard_payloads, signing_key_shard_payloads


def _render_all_documents(
    *,
    qr_inputs: RenderInputs,
    recovery_inputs: RenderInputs,
    kit_index_inputs: RenderInputs | None,
    shard_payloads: list[ShardPayload],
    signing_key_shard_payloads: list[ShardPayload],
    doc_id: bytes,
    output_dir: str,
    render_service: RenderService,
    layout_debug_dir: str | None,
    qr_payload_codec: QrPayloadCodec,
    origin: DocumentOrigin,
) -> tuple[list[str], list[str]]:
    """Render and validate each document before reporting its completion."""
    documents: list[tuple[RenderInputs, str, str, tuple[str, ...]]] = [
        (qr_inputs, "QR document", "qr_document", ()),
        (recovery_inputs, "recovery document", "recovery_document", ()),
    ]
    if kit_index_inputs is not None:
        documents.append(
            (
                kit_index_inputs,
                "recovery kit index",
                "recovery_kit_index",
                _expected_kit_index_component_ids(kit_index_inputs),
            )
        )
    render_total = len(documents) + len(shard_payloads) + len(signing_key_shard_payloads)
    rendered = 0
    emit_progress(phase="render", current=0, total=render_total, unit="documents")

    def report_completed(label: str, *, kind: str, path: str | Path) -> None:
        nonlocal rendered
        rendered += 1
        emit_progress(
            phase="render",
            current=rendered,
            total=render_total,
            unit="documents",
            label=f"Rendered {label}",
            details={"kind": kind, "path": str(path)},
        )

    for inputs, label, kind, expected_text in documents:
        result = render_module.render_frames_to_pdf(inputs)
        validate_rendered_pdf_document(
            inputs=inputs,
            result=result,
            document_label=f"rendered {label}",
            expected_text=expected_text,
        )
        if kind == "qr_document":
            _update_kit_index_qr_page_count(kit_index_inputs, result)
        report_completed(label, kind=kind, path=inputs.output_path)

    def report_shard(shard: ShardPayload, path: str) -> None:
        signing_key = shard.key_type == sharding_module.KEY_TYPE_SIGNING_SEED
        label = "signing-key shard" if signing_key else "shard document"
        kind = "signing_key_shard_document" if signing_key else "shard_document"
        report_completed(
            f"{label} {shard.share_index} of {shard.share_count}", kind=kind, path=path
        )

    return render_shard_documents(
        shard_payloads,
        signing_key_shard_payloads,
        context=ShardRenderContext(
            doc_id=doc_id,
            output_dir=output_dir,
            render_service=render_service,
            layout_debug_dir=layout_debug_dir,
            qr_payload_codec=qr_payload_codec,
            origin=origin,
        ),
        on_document=report_shard,
    )


def _read_staged_shard_quorum(
    paths: list[str],
    *,
    doc_id: bytes,
    doc_hash: bytes,
    sign_pub: bytes,
    qr_payload_codec: QrPayloadCodec,
) -> list[ShardPayload]:
    """Recover one complete quorum from the actual staged PDF carriers."""

    shares: list[ShardPayload] = []
    for path in paths:
        payloads = scan_qr_payloads([Path(path)])
        if len(payloads) != 1:
            raise ValueError("staged recovery sheet must contain exactly one shard QR")
        frame = decode_frame(decode_qr_payload(payloads[0], codec=qr_payload_codec))
        if (
            frame.frame_type != FrameType.KEY_DOCUMENT
            or frame.doc_id != doc_id
            or frame.version != VERSION
            or frame.index != 0
            or frame.total != 1
        ):
            raise ValueError("staged recovery sheet does not match the new root identity")
        shard = sharding_module.decode_shard_payload(frame.data)
        if shard.doc_hash != doc_hash or shard.sign_pub != sign_pub:
            raise ValueError("staged recovery shard does not bind to the new root ciphertext")
        shares.append(shard)
        if len(shares) >= shard.threshold:
            return shares
    raise ValueError("staged recovery sheets do not provide a complete quorum")


def _validate_staged_credentials(
    *,
    ciphertext: bytes,
    backup_document: bytes,
    passphrase: str,
    signing_seed: bytes,
    doc_id: bytes,
    doc_hash: bytes,
    auth_frame: Frame,
    shard_paths: list[str],
    signing_key_shard_paths: list[str],
    qr_payload_codec: QrPayloadCodec,
) -> None:
    """Verify credentials and signed ciphertext before publishing verified carriers."""

    recovered_passphrase = passphrase
    sign_pub = derive_public_key(signing_seed)
    if shard_paths:
        shares = _read_staged_shard_quorum(
            shard_paths,
            doc_id=doc_id,
            doc_hash=doc_hash,
            sign_pub=sign_pub,
            qr_payload_codec=qr_payload_codec,
        )
        recovered_passphrase = sharding_module.recover_passphrase(shares)
        if recovered_passphrase != passphrase:
            raise ValueError("staged recovery quorum does not recover the backup passphrase")
    if signing_key_shard_paths:
        shares = _read_staged_shard_quorum(
            signing_key_shard_paths,
            doc_id=doc_id,
            doc_hash=doc_hash,
            sign_pub=sign_pub,
            qr_payload_codec=qr_payload_codec,
        )
        if sharding_module.recover_signing_seed(shares) != signing_seed:
            raise ValueError("staged signing-key quorum does not recover the backup signing seed")
    if decrypt_bytes(ciphertext, passphrase=recovered_passphrase) != backup_document:
        raise ValueError("staged backup credentials do not recover the complete standalone payload")
    auth = signing_module.decode_auth_payload(auth_frame.data)
    if (
        auth.doc_hash != doc_hash
        or auth.sign_pub != derive_public_key(signing_seed)
        or not signing_module.verify_auth(
            doc_hash, sign_pub=auth.sign_pub, signature=auth.signature
        )
    ):
        raise ValueError("staged backup authentication does not match the new root")


def run_backup(
    *,
    input_files: list[InputFile],
    base_dir: Path | None,
    output_dir: str | Path | None,
    layout_debug_dir: str | Path | None = None,
    input_origin: str = "file",
    input_roots: list[str] | None = None,
    plan: DocumentPlan,
    passphrase: str | None,
    passphrase_words: int | None = None,
    config: AppConfig,
    signing_seed_override: bytes | None = None,
    payload_codec_override: payload_codec_module.PayloadEncodingMode | None = None,
    render_origin: DocumentOrigin,
    debug: bool = False,
    debug_max_bytes: int | None = None,
    debug_reveal_secrets: bool = False,
    publication_durability: PublicationDurability = "best-effort",
    quiet: bool = False,
) -> BackupResult:
    """Run the backup process and generate PDF documents."""
    if not input_files:
        raise ValueError("at least one input file is required")
    if passphrase is not None and plan.sharding is None and not passphrase.isprintable():
        raise ValueError(
            "directly printed passphrase must contain only manually enterable printable text"
        )

    sign_priv, sign_pub, store_signing_key, shard_signing_key = _backup_signing_material(
        plan, signing_seed_override
    )
    producer_passphrase = (
        normalize_valid_bip39_whitespace(passphrase) if passphrase is not None else None
    )

    backup_document, payload, qr_payload_codec_mode = _encode_backup_inputs(
        input_files,
        plan,
        sign_priv,
        input_origin,
        input_roots,
        config,
        payload_codec_override,
    )

    ciphertext, passphrase_final = _encrypt_backup_inputs(
        backup_document, producer_passphrase, passphrase_words
    )
    (
        key_lines,
        recovery_meta,
        doc_id,
        doc_hash,
        auth_frame,
        shard_payloads,
        signing_key_shard_payloads,
    ) = _backup_recovery_material(
        plan,
        passphrase_final,
        ciphertext,
        sign_priv,
        sign_pub,
        shard_signing_key,
        store_signing_key,
    )
    # Prepare render inputs
    main_chunk_size = _backup_qr_chunk_size(
        ciphertext, config, doc_id, qr_payload_codec_mode, quiet
    )
    frames = chunk_payload(
        ciphertext,
        doc_id=doc_id,
        frame_type=FrameType.MAIN_DOCUMENT,
        chunk_size=main_chunk_size,
    )
    qr_frames = [*frames, auth_frame]
    emit_phase(phase="output", label="Preparing backup destination")
    output_dir, staging_output_dir = prepare_backup_output_dir(
        output_dir,
        doc_id.hex(),
    )
    try:
        output_dir_path = Path(staging_output_dir)
        qr_path = str(output_dir_path / "qr_document.pdf")
        recovery_path = str(output_dir_path / "recovery_document.pdf")
        kit_index_style = resolve_recovery_kit_index_style(config)
        kit_index_path = None
        if kit_index_style is not None:
            kit_index_path = str(output_dir_path / "recovery_kit_index.pdf")
        layout_debug_dir = resolve_layout_debug_dir(
            layout_debug_dir,
            forbidden_dirs={
                "final output": output_dir,
                "staging output": staging_output_dir,
            },
        )
        if render_origin is None:
            raise ValueError("backup execution requires explicit render origin")
        origin = render_origin

        render_service = RenderService(config, on_page=report_render_page)
        qr_payloads = render_service.build_qr_payloads(qr_frames, codec=qr_payload_codec_mode)
        qr_inputs = render_service.qr_inputs(
            qr_frames,
            qr_path,
            qr_payloads=qr_payloads,
            layout_debug_json_path=layout_debug_json_path(layout_debug_dir, "qr_document"),
            origin=origin,
        )
        kit_index_context = render_service.base_context(
            {
                "doc_id": doc_id.hex(),
                "inventory_rows": build_recovery_kit_index_inventory_rows(
                    shard_payloads=shard_payloads,
                    signing_key_shard_payloads=signing_key_shard_payloads,
                ),
            }
        )
        kit_index_inputs = (
            render_service.kit_index_inputs(
                kit_index_path,
                context=kit_index_context,
                design_name=kit_index_style,
                qr_chunk_count=len(qr_frames),
                layout_debug_json_path=layout_debug_json_path(
                    layout_debug_dir, "recovery_kit_index"
                ),
                origin=origin,
            )
            if kit_index_style is not None and kit_index_path is not None
            else None
        )

        main_fallback_frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=ciphertext,
        )
        fallback_sections = [
            render_module.FallbackSection(label=AUTH_FALLBACK_LABEL, frame=auth_frame),
            render_module.FallbackSection(label=MAIN_FALLBACK_LABEL, frame=main_fallback_frame),
        ]
        recovery_inputs = render_service.recovery_inputs(
            frames,
            recovery_path,
            key_lines=key_lines,
            recovery_meta=recovery_meta,
            fallback_sections=fallback_sections,
            layout_debug_json_path=layout_debug_json_path(layout_debug_dir, "recovery_document"),
            origin=origin,
        )

        emit_event("destination", path=str(Path(output_dir).absolute()))
        emit_phase(phase="render", label="Rendering backup documents")
        shard_paths, signing_key_shard_paths = _render_all_documents(
            qr_inputs=qr_inputs,
            recovery_inputs=recovery_inputs,
            kit_index_inputs=kit_index_inputs,
            shard_payloads=shard_payloads,
            signing_key_shard_payloads=signing_key_shard_payloads,
            doc_id=doc_id,
            output_dir=staging_output_dir,
            render_service=render_service,
            layout_debug_dir=layout_debug_dir,
            qr_payload_codec=qr_payload_codec_mode,
            origin=origin,
        )
        emit_phase(phase="verify", label="Checking generated documents")
        _validate_staged_credentials(
            ciphertext=ciphertext,
            backup_document=backup_document,
            passphrase=passphrase_final,
            signing_seed=sign_priv,
            doc_id=doc_id,
            doc_hash=doc_hash,
            auth_frame=auth_frame,
            shard_paths=shard_paths,
            signing_key_shard_paths=signing_key_shard_paths,
            qr_payload_codec=qr_payload_codec_mode,
        )
        commit_prepared_output_dir(
            staging_output_dir,
            output_dir,
            durability=publication_durability,
        )
    except BaseException:
        discard_prepared_output_dir(staging_output_dir)
        raise

    final_output_dir = Path(output_dir)
    final_qr_path = str(final_output_dir / Path(qr_path).name)
    final_recovery_path = str(final_output_dir / Path(recovery_path).name)
    final_kit_index_path = (
        None if kit_index_path is None else str(final_output_dir / Path(kit_index_path).name)
    )
    final_shard_paths = tuple(str(final_output_dir / Path(path).name) for path in shard_paths)
    final_signing_key_shard_paths = tuple(
        str(final_output_dir / Path(path).name) for path in signing_key_shard_paths
    )

    return BackupResult(
        doc_id=doc_id,
        doc_hash=doc_hash,
        qr_path=final_qr_path,
        recovery_path=final_recovery_path,
        kit_index_path=final_kit_index_path,
        shard_paths=final_shard_paths,
        signing_key_shard_paths=final_signing_key_shard_paths,
        passphrase_used=passphrase_final,
    )


def _backup_qr_chunk_size(
    ciphertext: bytes,
    config: AppConfig,
    doc_id: bytes,
    qr_payload_codec_mode: QrPayloadCodec,
    quiet: bool,
) -> int:
    main_chunk_size = choose_frame_chunk_size(
        len(ciphertext),
        preferred_chunk_size=config.qr_chunk_size,
        doc_id=doc_id,
        frame_type=FrameType.MAIN_DOCUMENT,
        qr_config=config.qr_config,
        payload_codec=qr_payload_codec_mode,
    )
    if main_chunk_size < config.qr_chunk_size:
        warn(
            (
                f"Requested QR chunk size ({config.qr_chunk_size} bytes) was reduced to "
                f"{main_chunk_size} bytes to fit current QR settings."
            ),
            quiet=quiet,
            code=issue_codes.BACKUP_QR_CHUNK_SIZE_REDUCED,
            details={
                "requested_chunk_size": config.qr_chunk_size,
                "effective_chunk_size": main_chunk_size,
            },
        )
    return main_chunk_size


def _backup_recovery_material(
    plan: DocumentPlan,
    passphrase_final: str,
    ciphertext: bytes,
    sign_priv: bytes,
    sign_pub: bytes,
    shard_signing_key: bool,
    store_signing_key: bool,
) -> tuple[list[str], RecoveryMeta, bytes, bytes, Frame, list[ShardPayload], list[ShardPayload]]:
    # Build key lines for recovery document
    plan_sharding = plan.sharding
    if plan_sharding is not None:
        key_lines = [
            "Passphrase is sharded.",
            f"Recover with {plan_sharding.threshold} of {plan_sharding.shares} shard documents.",
        ]
    else:
        key_lines = ["Passphrase:", passphrase_final]
    recovery_meta = build_recovery_meta(
        passphrase=None if plan_sharding is not None else passphrase_final,
        quorum_threshold=plan_sharding.threshold if plan_sharding is not None else None,
        quorum_shares=plan_sharding.shares if plan_sharding is not None else None,
        signing_pub=sign_pub,
    )

    # Create document identifiers and auth frame
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    auth_frame = _create_auth_frame(doc_id, doc_hash, sign_priv, sign_pub)

    # Create shard payloads if sharding is enabled
    if plan_sharding is not None and passphrase_final is None:
        raise ValueError("passphrase is required for sharding")
    emit_phase(phase="shard", label="Preparing shard documents")
    shard_payloads, signing_key_shard_payloads = _create_shard_payloads(
        plan, passphrase_final or "", doc_hash, sign_priv, sign_pub, shard_signing_key
    )
    emit_progress(
        phase="shard",
        current=len(shard_payloads) + len(signing_key_shard_payloads),
        total=len(shard_payloads) + len(signing_key_shard_payloads),
        unit="documents",
        details={
            "passphrase_shards": len(shard_payloads),
            "signing_key_shards": len(signing_key_shard_payloads),
        },
    )

    append_signing_key_lines(
        key_lines,
        sign_pub=sign_pub,
        sealed=plan.sealed,
        stored_in_main=store_signing_key,
        stored_as_shards=shard_signing_key,
    )

    return (
        key_lines,
        recovery_meta,
        doc_id,
        doc_hash,
        auth_frame,
        shard_payloads,
        signing_key_shard_payloads,
    )


def _backup_signing_material(
    plan: DocumentPlan, signing_seed_override: bytes | None
) -> tuple[bytes, bytes, bool, bool]:
    # Generate signing keypair and determine key storage modes
    if signing_seed_override is None:
        sign_priv, sign_pub = signing_module.generate_signing_keypair()
    else:
        sign_priv = bytes(signing_seed_override)
        sign_pub = derive_public_key(sign_priv)
    store_signing_key = not plan.sealed
    shard_signing_key = (
        plan.sharding is not None
        and not plan.sealed
        and plan.signing_seed_mode == SigningSeedMode.SHARDED
    )
    return sign_priv, sign_pub, store_signing_key, shard_signing_key


def _encrypt_backup_inputs(
    backup_document: bytes,
    producer_passphrase: str | None,
    passphrase_words: int | None,
) -> tuple[bytes, str]:
    # Encrypt payload
    emit_phase(phase="encrypt", label="Encrypting payload")
    ciphertext, passphrase_used = encrypt_bytes_with_passphrase(
        backup_document,
        passphrase=producer_passphrase,
        passphrase_words=passphrase_words,
    )
    emit_progress(
        phase="encrypt",
        current=1,
        total=1,
        unit="step",
        details={"ciphertext_bytes": len(ciphertext)},
    )
    if len(ciphertext) > MAX_CIPHERTEXT_BYTES:
        raise ValueError(
            f"ciphertext exceeds MAX_CIPHERTEXT_BYTES ({MAX_CIPHERTEXT_BYTES}): "
            f"{len(ciphertext)} bytes"
        )
    if passphrase_used is None:
        raise ValueError("passphrase generation failed")
    passphrase_final = passphrase_used

    return ciphertext, passphrase_final


def _encode_backup_inputs(
    input_files: list[InputFile],
    plan: DocumentPlan,
    sign_priv: bytes,
    input_origin: str,
    input_roots: list[str] | None,
    config: AppConfig,
    payload_codec_override: payload_codec_module.PayloadEncodingMode | None,
) -> tuple[bytes, bytes, QrPayloadCodec]:
    # Encode the backup document and handle debug output.
    emit_phase(phase="prepare", label="Preparing payload")
    payload_codec_mode = payload_codec_override or config.cli_defaults.backup.payload_codec
    qr_payload_codec_mode = config.cli_defaults.backup.qr_payload_codec
    backup_document, payload = _prepare_backup_document(
        input_files,
        plan,
        sign_priv,
        input_origin,
        input_roots or [],
        payload_codec_mode=payload_codec_mode,
    )
    manifest = document_codec_module.decode_backup_document(backup_document)[0]
    emit_progress(
        phase="prepare",
        current=1,
        total=1,
        unit="step",
        details={
            "input_count": len(input_files),
            "manifest_file_count": len(manifest.files),
            "payload_bytes": len(payload),
        },
    )

    return backup_document, payload, qr_payload_codec_mode
