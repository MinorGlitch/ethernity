#!/usr/bin/env python3
from __future__ import annotations

import importlib
import os
from pathlib import Path

from ..core.crypto import _doc_hash_from_ciphertext, _doc_id_from_ciphertext
from ..core.types import BackupResult, InputFile
from ..io.outputs import _ensure_output_dir
from ..ui import _progress, _status
from ..ui.debug import (
    _append_signing_key_lines,
    _normalize_debug_max_bytes,
    _print_pre_encryption_debug,
)
from ...encoding.framing import Frame, FrameType, VERSION, encode_frame
from ...core.models import DocumentMode, DocumentPlan, KeyMaterial
from ...encoding.qr_payloads import encode_qr_payload, normalize_qr_payload_encoding


def _cli_module():
    return importlib.import_module("ethernity.cli")


def run_backup(
    *,
    input_files: list[InputFile],
    base_dir: Path | None,
    output_dir: str | None,
    plan: DocumentPlan,
    recipients: list[str],
    passphrase: str | None,
    passphrase_words: int | None = None,
    config,
    title_override: str | None,
    subtitle_override: str | None,
    debug: bool = False,
    debug_max_bytes: int | None = None,
    quiet: bool = False,
) -> BackupResult:
    status_quiet = quiet or debug
    if not input_files:
        raise ValueError("at least one input file is required")

    with _status("Starting backup...", quiet=status_quiet):
        from ...encoding.chunking import chunk_payload
        from ...formats.envelope_codec import build_manifest_and_payload, encode_envelope
        from ...formats.envelope_types import PayloadPart
        from ...render import FallbackSection, RenderInputs, render_frames_to_pdf
        from ...crypto.sharding import ShardPayload, encode_shard_payload, split_passphrase
        from ...crypto.signing import encode_auth_payload, generate_signing_keypair, sign_auth

    with _status("Preparing payload...", quiet=status_quiet):
        parts = [
            PayloadPart(path=item.relative_path, data=item.data, mtime=item.mtime)
            for item in input_files
        ]
        manifest, payload = build_manifest_and_payload(parts, sealed=plan.sealed)
        envelope = encode_envelope(payload, manifest)
        wrapped_envelope = envelope

    encrypt_recipients: list[str] = []
    key_lines: list[str] = []
    identity = None
    recipient_public = None
    passphrase_used: str | None = None
    passphrase_final: str | None = None
    shard_payloads: list[ShardPayload] = []
    normalized_debug_bytes = _normalize_debug_max_bytes(debug_max_bytes)
    cli = _cli_module()

    if plan.mode == DocumentMode.PASSPHRASE:
        if debug:
            _print_pre_encryption_debug(
                payload=payload,
                input_files=input_files,
                base_dir=base_dir,
                manifest=manifest,
                envelope=envelope,
                plan=plan,
                recipients=[],
                passphrase=passphrase,
                identity=None,
                recipient_public=None,
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
    else:
        if recipients:
            encrypt_recipients = recipients
            key_lines = ["Recipients:"] + recipients + ["Private key not included."]
        elif plan.key_material == KeyMaterial.IDENTITY:
            identity, recipient_public = cli.generate_identity()
            encrypt_recipients = [recipient_public]
            key_lines = ["Age Identity:", identity, "Recipient:", recipient_public]
        else:
            raise ValueError("no recipients provided for recipient mode")
        if debug:
            _print_pre_encryption_debug(
                payload=payload,
                input_files=input_files,
                base_dir=base_dir,
                manifest=manifest,
                envelope=envelope,
                plan=plan,
                recipients=encrypt_recipients,
                passphrase=passphrase,
                identity=identity,
                recipient_public=recipient_public,
                debug_max_bytes=normalized_debug_bytes,
            )
        with _status("Encrypting payload...", quiet=status_quiet):
            ciphertext = cli.encrypt_bytes(wrapped_envelope, recipients=encrypt_recipients)

    doc_id = _doc_id_from_ciphertext(ciphertext)
    doc_hash = _doc_hash_from_ciphertext(ciphertext)
    sign_priv, sign_pub = generate_signing_keypair()
    auth_signature = sign_auth(doc_hash, sign_priv=sign_priv)
    auth_payload = encode_auth_payload(doc_hash, sign_pub=sign_pub, signature=auth_signature)
    auth_frame = Frame(
        version=VERSION,
        frame_type=FrameType.AUTH,
        doc_id=doc_id,
        index=0,
        total=1,
        data=auth_payload,
    )

    plan_sharding = plan.sharding
    if plan.mode == DocumentMode.PASSPHRASE and plan_sharding is not None:
        if passphrase_final is None:
            raise ValueError("passphrase is required for sharding")
        with _status("Creating shard payloads...", quiet=status_quiet):
            shard_payloads = split_passphrase(
                passphrase_final,
                threshold=plan_sharding.threshold,
                shares=plan_sharding.shares,
                doc_hash=doc_hash,
                sign_priv=sign_priv,
                sign_pub=sign_pub,
            )

    _append_signing_key_lines(key_lines, sign_pub=sign_pub, sign_priv=sign_priv, sealed=plan.sealed)

    frames = chunk_payload(ciphertext, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT)
    qr_frames = [*frames, auth_frame]

    output_dir = _ensure_output_dir(output_dir, doc_id.hex())
    qr_path = os.path.join(output_dir, "qr_document.pdf")
    recovery_path = os.path.join(output_dir, "recovery_document.pdf")
    shard_paths: list[str] = []

    context = dict(config.context)
    context["title"] = title_override or "Main Document"
    context["subtitle"] = subtitle_override or f"Mode: {plan.mode.value}"
    context["doc_id"] = doc_id.hex()

    qr_payloads = _encode_qr_payloads(qr_frames, config.qr_payload_encoding)
    qr_inputs = RenderInputs(
        frames=qr_frames,
        template_path=config.template_path,
        output_path=qr_path,
        context=context,
        qr_config=config.qr_config,
        qr_payloads=qr_payloads,
        render_fallback=False,
    )

    recovery_context = dict(config.context)
    recovery_context.setdefault("recovery_title", "Recovery Document")
    recovery_context.setdefault("recovery_subtitle", "Keys + Text Fallback")
    recovery_context.setdefault(
        "recovery_instructions",
        [
            "This document contains recovery keys and full text fallback.",
            "Keep it separate from the QR document.",
            "Fallback includes AUTH + MAIN sections; keep the labels when transcribing.",
        ],
    )
    recovery_context.setdefault("key_lines", key_lines)
    recovery_context["doc_id"] = doc_id.hex()

    main_fallback_frame = Frame(
        version=VERSION,
        frame_type=FrameType.MAIN_DOCUMENT,
        doc_id=doc_id,
        index=0,
        total=1,
        data=ciphertext,
    )
    fallback_sections = [
        FallbackSection(label=cli.AUTH_FALLBACK_LABEL, frame=auth_frame),
        FallbackSection(label=cli.MAIN_FALLBACK_LABEL, frame=main_fallback_frame),
    ]

    recovery_inputs = RenderInputs(
        frames=frames,
        template_path=config.recovery_template_path,
        output_path=recovery_path,
        context=recovery_context,
        qr_config=config.qr_config,
        fallback_sections=fallback_sections,
        render_qr=False,
        key_lines=key_lines,
    )
    render_total = 2 + (len(shard_payloads) if shard_payloads else 0)
    with _progress(quiet=status_quiet) as progress:
        if progress:
            task_id = progress.add_task("Rendering documents...", total=render_total)
            progress.update(task_id, description="Rendering QR document...")
            render_frames_to_pdf(qr_inputs)
            progress.advance(task_id)

            progress.update(task_id, description="Rendering recovery document...")
            render_frames_to_pdf(recovery_inputs)
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
                        data=encode_shard_payload(shard),
                    )
                    shard_path = os.path.join(
                        output_dir,
                        f"shard-{doc_id.hex()}-{shard.index}-of-{shard.shares}.pdf",
                    )
                    shard_context = dict(config.context)
                    shard_context.setdefault("shard_title", "Shard Document")
                    shard_context["shard_subtitle"] = (
                        f"Shard {shard.index} of {shard.shares} (Doc ID: {doc_id.hex()})"
                    )
                    shard_context["doc_id"] = doc_id.hex()

                    shard_inputs = RenderInputs(
                        frames=[shard_frame],
                        template_path=config.shard_template_path,
                        output_path=shard_path,
                        context=shard_context,
                        qr_config=config.qr_config,
                        qr_payloads=_encode_qr_payloads(
                            [shard_frame], config.qr_payload_encoding
                        ),
                    )
                    render_frames_to_pdf(shard_inputs)
                    shard_paths.append(shard_path)
                    progress.advance(task_id)
        else:
            with _status("Rendering QR document...", quiet=status_quiet):
                render_frames_to_pdf(qr_inputs)
            with _status("Rendering recovery document...", quiet=status_quiet):
                render_frames_to_pdf(recovery_inputs)
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
                            data=encode_shard_payload(shard),
                        )
                        shard_path = os.path.join(
                            output_dir,
                            f"shard-{doc_id.hex()}-{shard.index}-of-{shard.shares}.pdf",
                        )
                        shard_context = dict(config.context)
                        shard_context.setdefault("shard_title", "Shard Document")
                        shard_context["shard_subtitle"] = (
                            f"Shard {shard.index} of {shard.shares} (Doc ID: {doc_id.hex()})"
                        )
                        shard_context["doc_id"] = doc_id.hex()

                        shard_inputs = RenderInputs(
                            frames=[shard_frame],
                            template_path=config.shard_template_path,
                            output_path=shard_path,
                            context=shard_context,
                            qr_config=config.qr_config,
                            qr_payloads=_encode_qr_payloads(
                                [shard_frame], config.qr_payload_encoding
                            ),
                        )
                        render_frames_to_pdf(shard_inputs)
                        shard_paths.append(shard_path)
    return BackupResult(
        doc_id=doc_id,
        qr_path=qr_path,
        recovery_path=recovery_path,
        shard_paths=tuple(shard_paths),
        passphrase_used=passphrase_used,
        generated_identity=identity,
        generated_recipient=recipient_public,
    )


def _encode_qr_payloads(frames: list[Frame], encoding: str) -> list[bytes | str]:
    normalized = normalize_qr_payload_encoding(encoding)
    return [encode_qr_payload(encode_frame(frame), encoding=normalized) for frame in frames]
