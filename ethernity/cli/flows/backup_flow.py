#!/usr/bin/env python3
from __future__ import annotations

import importlib
import os
from pathlib import Path

from ..core.crypto import _doc_hash_from_ciphertext, _doc_id_from_ciphertext
from ..core.types import BackupResult, InputFile
from ..io.outputs import _ensure_output_dir
from ..api import _progress, _status
from ..ui.debug import (
    _append_signing_key_lines,
    _normalize_debug_max_bytes,
    _print_pre_encryption_debug,
)
from ...encoding.framing import Frame, FrameType, VERSION, encode_frame
from ...core.models import DocumentPlan, SigningSeedMode
from ...encoding.chunking import chunk_payload
from ...formats import envelope_codec as envelope_codec_module
from ...formats.envelope_types import PayloadPart
from ... import render as render_module
from ...crypto import sharding as sharding_module
from ...crypto.sharding import ShardPayload
from ...crypto import signing as signing_module
from ...encoding.qr_payloads import encode_qr_payload, normalize_qr_payload_encoding


def _cli_module():
    return importlib.import_module("ethernity.cli")


def run_backup(
    *,
    input_files: list[InputFile],
    base_dir: Path | None,
    output_dir: str | None,
    plan: DocumentPlan,
    passphrase: str | None,
    passphrase_words: int | None = None,
    config,
    debug: bool = False,
    debug_max_bytes: int | None = None,
    quiet: bool = False,
) -> BackupResult:
    status_quiet = quiet or debug
    if not input_files:
        raise ValueError("at least one input file is required")

    with _status("Starting backup...", quiet=status_quiet):
        pass

    sign_priv, sign_pub = signing_module.generate_signing_keypair()
    store_signing_key = (
        plan.sharding is not None
        and not plan.sealed
        and plan.signing_seed_mode == SigningSeedMode.EMBEDDED
    )
    shard_signing_key = (
        plan.sharding is not None
        and not plan.sealed
        and plan.signing_seed_mode == SigningSeedMode.SHARDED
    )
    with _status("Preparing payload...", quiet=status_quiet):
        parts = [
            PayloadPart(path=item.relative_path, data=item.data, mtime=item.mtime)
            for item in input_files
        ]
        manifest, payload = envelope_codec_module.build_manifest_and_payload(
            parts,
            sealed=plan.sealed,
            signing_seed=sign_priv if store_signing_key else None,
        )
        envelope = envelope_codec_module.encode_envelope(payload, manifest)
        wrapped_envelope = envelope

    key_lines: list[str] = []
    passphrase_used: str | None = None
    passphrase_final: str | None = None
    shard_payloads: list[ShardPayload] = []
    signing_key_shard_payloads: list[ShardPayload] = []
    normalized_debug_bytes = _normalize_debug_max_bytes(debug_max_bytes)
    cli = _cli_module()

    if debug:
        _print_pre_encryption_debug(
            payload=payload,
            input_files=input_files,
            base_dir=base_dir,
            manifest=manifest,
            envelope=envelope,
            plan=plan,
            passphrase=passphrase,
            signing_seed=sign_priv,
            signing_pub=sign_pub,
            signing_seed_stored=store_signing_key,
            debug_max_bytes=normalized_debug_bytes,
        )
    with _status("Encrypting payload...", quiet=status_quiet):
        ciphertext, passphrase_used = cli.encrypt_bytes_with_passphrase(
            wrapped_envelope, passphrase=passphrase, passphrase_words=passphrase_words
        )
    if passphrase_used is None:
        raise ValueError("passphrase generation failed")
    passphrase_final = passphrase if passphrase is not None else passphrase_used
    plan_sharding = plan.sharding
    if plan_sharding is not None:
        key_lines = [
            "Passphrase is sharded.",
            f"Recover with {plan_sharding.threshold} of {plan_sharding.shares} shard documents.",
        ]
    else:
        key_lines = ["Passphrase:", passphrase_final]

    doc_id = _doc_id_from_ciphertext(ciphertext)
    doc_hash = _doc_hash_from_ciphertext(ciphertext)
    auth_signature = signing_module.sign_auth(doc_hash, sign_priv=sign_priv)
    auth_payload = signing_module.encode_auth_payload(
        doc_hash,
        sign_pub=sign_pub,
        signature=auth_signature,
    )
    auth_frame = Frame(
        version=VERSION,
        frame_type=FrameType.AUTH,
        doc_id=doc_id,
        index=0,
        total=1,
        data=auth_payload,
    )

    plan_sharding = plan.sharding
    signing_key_sharding = plan.signing_seed_sharding or plan.sharding
    if plan_sharding is not None:
        if passphrase_final is None:
            raise ValueError("passphrase is required for sharding")
        with _status("Creating shard payloads...", quiet=status_quiet):
            shard_payloads = sharding_module.split_passphrase(
                passphrase_final,
                threshold=plan_sharding.threshold,
                shares=plan_sharding.shares,
                doc_hash=doc_hash,
                sign_priv=sign_priv,
                sign_pub=sign_pub,
            )
        if shard_signing_key:
            if signing_key_sharding is None:
                raise ValueError("signing key sharding requires a shard quorum")
            with _status("Creating signing key shard payloads...", quiet=status_quiet):
                signing_key_shard_payloads = sharding_module.split_signing_seed(
                    sign_priv,
                    threshold=signing_key_sharding.threshold,
                    shares=signing_key_sharding.shares,
                    doc_hash=doc_hash,
                    sign_priv=sign_priv,
                    sign_pub=sign_pub,
                )

    _append_signing_key_lines(
        key_lines,
        sign_pub=sign_pub,
        sealed=plan.sealed,
        stored_in_main=store_signing_key,
        stored_as_shards=shard_signing_key,
    )

    frames = chunk_payload(ciphertext, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT)
    qr_frames = [*frames, auth_frame]

    output_dir = _ensure_output_dir(output_dir, doc_id.hex())
    qr_path = os.path.join(output_dir, "qr_document.pdf")
    recovery_path = os.path.join(output_dir, "recovery_document.pdf")
    shard_paths: list[str] = []
    signing_key_shard_paths: list[str] = []

    context: dict[str, object] = {"paper_size": config.paper_size}

    qr_payloads = _encode_qr_payloads(qr_frames, config.qr_payload_encoding)
    qr_inputs = render_module.RenderInputs(
        frames=qr_frames,
        template_path=config.template_path,
        output_path=qr_path,
        context=context,
        qr_config=config.qr_config,
        qr_payloads=qr_payloads,
        render_fallback=False,
    )

    recovery_context: dict[str, object] = {"paper_size": config.paper_size}

    main_fallback_frame = Frame(
        version=VERSION,
        frame_type=FrameType.MAIN_DOCUMENT,
        doc_id=doc_id,
        index=0,
        total=1,
        data=ciphertext,
    )
    fallback_sections = [
        render_module.FallbackSection(label=cli.AUTH_FALLBACK_LABEL, frame=auth_frame),
        render_module.FallbackSection(label=cli.MAIN_FALLBACK_LABEL, frame=main_fallback_frame),
    ]

    recovery_inputs = render_module.RenderInputs(
        frames=frames,
        template_path=config.recovery_template_path,
        output_path=recovery_path,
        context=recovery_context,
        qr_config=config.qr_config,
        fallback_sections=fallback_sections,
        render_qr=False,
        key_lines=key_lines,
    )
    render_total = (
        2
        + (len(shard_payloads) if shard_payloads else 0)
        + (len(signing_key_shard_payloads) if signing_key_shard_payloads else 0)
    )
    with _progress(quiet=status_quiet) as progress:
        if progress:
            task_id = progress.add_task("Rendering documents...", total=render_total)
            progress.update(task_id, description="Rendering QR document...")
            render_module.render_frames_to_pdf(qr_inputs)
            progress.advance(task_id)

            progress.update(task_id, description="Rendering recovery document...")
            render_module.render_frames_to_pdf(recovery_inputs)
            progress.advance(task_id)

            if shard_payloads:
                sorted_shards = sorted(shard_payloads, key=lambda shard: shard.index)
                total_shards = len(sorted_shards)
                for idx, shard in enumerate(sorted_shards, start=1):
                    progress.update(
                        task_id,
                        description=f"Rendering shard documents... ({idx}/{total_shards})",
                    )
                    shard_frame = Frame(
                        version=VERSION,
                        frame_type=FrameType.KEY_DOCUMENT,
                        doc_id=doc_id,
                        index=0,
                        total=1,
                        data=sharding_module.encode_shard_payload(shard),
                    )
                    shard_path = os.path.join(
                        output_dir,
                        f"shard-{doc_id.hex()}-{shard.index}-of-{shard.shares}.pdf",
                    )
                    shard_context = {
                        "paper_size": config.paper_size,
                        "shard_index": shard.index,
                        "shard_total": shard.shares,
                    }

                    shard_inputs = render_module.RenderInputs(
                        frames=[shard_frame],
                        template_path=config.shard_template_path,
                        output_path=shard_path,
                        context=shard_context,
                        qr_config=config.qr_config,
                        qr_payloads=_encode_qr_payloads(
                            [shard_frame], config.qr_payload_encoding
                        ),
                    )
                    render_module.render_frames_to_pdf(shard_inputs)
                    shard_paths.append(shard_path)
                    progress.advance(task_id)
            if signing_key_shard_payloads:
                sorted_shards = sorted(signing_key_shard_payloads, key=lambda shard: shard.index)
                total_shards = len(sorted_shards)
                for idx, shard in enumerate(sorted_shards, start=1):
                    progress.update(
                        task_id,
                        description=f"Rendering signing key shards... ({idx}/{total_shards})",
                    )
                    shard_frame = Frame(
                        version=VERSION,
                        frame_type=FrameType.KEY_DOCUMENT,
                        doc_id=doc_id,
                        index=0,
                        total=1,
                        data=sharding_module.encode_shard_payload(shard),
                    )
                    shard_path = os.path.join(
                        output_dir,
                        f"signing-key-shard-{doc_id.hex()}-{shard.index}-of-{shard.shares}.pdf",
                    )
                    shard_context = {
                        "paper_size": config.paper_size,
                        "shard_index": shard.index,
                        "shard_total": shard.shares,
                    }

                    shard_inputs = render_module.RenderInputs(
                        frames=[shard_frame],
                        template_path=config.signing_key_shard_template_path,
                        output_path=shard_path,
                        context=shard_context,
                        qr_config=config.qr_config,
                        qr_payloads=_encode_qr_payloads(
                            [shard_frame], config.qr_payload_encoding
                        ),
                    )
                    render_module.render_frames_to_pdf(shard_inputs)
                    signing_key_shard_paths.append(shard_path)
                    progress.advance(task_id)
        else:
            with _status("Rendering QR document...", quiet=status_quiet):
                render_module.render_frames_to_pdf(qr_inputs)
            with _status("Rendering recovery document...", quiet=status_quiet):
                render_module.render_frames_to_pdf(recovery_inputs)
            if shard_payloads:
                with _status("Rendering shard documents...", quiet=status_quiet):
                    sorted_shards = sorted(shard_payloads, key=lambda shard: shard.index)
                    for shard in sorted_shards:
                        shard_frame = Frame(
                            version=VERSION,
                            frame_type=FrameType.KEY_DOCUMENT,
                            doc_id=doc_id,
                            index=0,
                            total=1,
                            data=sharding_module.encode_shard_payload(shard),
                        )
                        shard_path = os.path.join(
                            output_dir,
                            f"shard-{doc_id.hex()}-{shard.index}-of-{shard.shares}.pdf",
                        )
                        shard_context = {
                            "paper_size": config.paper_size,
                            "shard_index": shard.index,
                            "shard_total": shard.shares,
                        }

                        shard_inputs = render_module.RenderInputs(
                            frames=[shard_frame],
                            template_path=config.shard_template_path,
                            output_path=shard_path,
                            context=shard_context,
                            qr_config=config.qr_config,
                            qr_payloads=_encode_qr_payloads(
                                [shard_frame], config.qr_payload_encoding
                            ),
                        )
                        render_module.render_frames_to_pdf(shard_inputs)
                        shard_paths.append(shard_path)
            if signing_key_shard_payloads:
                with _status("Rendering signing key shards...", quiet=status_quiet):
                    sorted_shards = sorted(signing_key_shard_payloads, key=lambda shard: shard.index)
                    for shard in sorted_shards:
                        shard_frame = Frame(
                            version=VERSION,
                            frame_type=FrameType.KEY_DOCUMENT,
                            doc_id=doc_id,
                            index=0,
                            total=1,
                            data=sharding_module.encode_shard_payload(shard),
                        )
                        shard_path = os.path.join(
                            output_dir,
                            f"signing-key-shard-{doc_id.hex()}-{shard.index}-of-{shard.shares}.pdf",
                        )
                        shard_context = {
                            "paper_size": config.paper_size,
                            "shard_index": shard.index,
                            "shard_total": shard.shares,
                        }

                        shard_inputs = render_module.RenderInputs(
                            frames=[shard_frame],
                            template_path=config.signing_key_shard_template_path,
                            output_path=shard_path,
                            context=shard_context,
                            qr_config=config.qr_config,
                            qr_payloads=_encode_qr_payloads(
                                [shard_frame], config.qr_payload_encoding
                            ),
                        )
                        render_module.render_frames_to_pdf(shard_inputs)
                        signing_key_shard_paths.append(shard_path)
    return BackupResult(
        doc_id=doc_id,
        qr_path=qr_path,
        recovery_path=recovery_path,
        shard_paths=tuple(shard_paths),
        signing_key_shard_paths=tuple(signing_key_shard_paths),
        passphrase_used=passphrase_used,
    )


def _encode_qr_payloads(frames: list[Frame], encoding: str) -> list[bytes | str]:
    normalized = normalize_qr_payload_encoding(encoding)
    return [encode_qr_payload(encode_frame(frame), encoding=normalized) for frame in frames]
