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

from __future__ import annotations

import os
from pathlib import Path

from rich.progress import Progress

from ... import render as render_module
from ...config import AppConfig
from ...config.installer import PACKAGE_ROOT
from ...core.bounds import MAX_CIPHERTEXT_BYTES
from ...core.models import DocumentPlan, SigningSeedMode
from ...crypto import (
    encrypt_bytes_with_passphrase,
    sharding as sharding_module,
    signing as signing_module,
)
from ...crypto.sharding import ShardPayload
from ...encoding.chunking import chunk_payload
from ...encoding.framing import VERSION, Frame, FrameType
from ...formats import envelope_codec as envelope_codec_module
from ...formats.envelope_types import PayloadPart
from ...qr.capacity import choose_frame_chunk_size
from ...render.doc_types import DOC_TYPE_SIGNING_KEY_SHARD
from ...render.service import RenderService
from ...render.types import RenderInputs
from ..api import progress, status
from ..constants import AUTH_FALLBACK_LABEL, MAIN_FALLBACK_LABEL
from ..core.crypto import _doc_id_and_hash_from_ciphertext
from ..core.log import _warn
from ..core.types import BackupResult, InputFile
from ..io.outputs import _ensure_output_dir
from ..ui.debug import (
    _append_signing_key_lines,
    _normalize_debug_max_bytes,
    _print_pre_encryption_debug,
)

_KIT_INDEX_TEMPLATE_NAME = "kit_index_document.html.j2"
_KIT_INDEX_TEMPLATE_MARKER = "kit_index_inventory_artifacts_v3"


def _is_compatible_kit_index_template(path: Path) -> bool:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return _KIT_INDEX_TEMPLATE_MARKER in content


def _resolve_kit_index_template_path(config: AppConfig) -> Path | None:
    kit_template_path = Path(config.kit_template_path)
    candidate = kit_template_path.with_name(_KIT_INDEX_TEMPLATE_NAME)
    package_candidate = (
        PACKAGE_ROOT / "templates" / kit_template_path.parent.name / _KIT_INDEX_TEMPLATE_NAME
    )

    if candidate.is_file() and _is_compatible_kit_index_template(candidate):
        return candidate

    if package_candidate.is_file():
        return package_candidate

    # If the active design is loaded from a user override that predates the
    # index template, fallback to the packaged design copy.
    if candidate.is_file():
        return candidate

    return None


def _build_kit_index_inventory_rows(
    *,
    shard_payloads: list[ShardPayload],
    signing_key_shard_payloads: list[ShardPayload],
) -> list[dict[str, str]]:
    rows = [
        {
            "component_id": "QR-DOC-01",
            "detail": "Encrypted payload and auth QR frames",
            "status": "Generated",
        },
        {
            "component_id": "RECOVERY-DOC-01",
            "detail": "Recovery keys and full fallback text",
            "status": "Generated",
        },
    ]

    if shard_payloads:
        for shard in sorted(shard_payloads, key=lambda item: item.share_index):
            rows.append(
                {
                    "component_id": f"SHARD-{shard.share_index:02d}",
                    "detail": (f"Passphrase shard {shard.share_index} of {shard.share_count}"),
                    "status": "Generated",
                }
            )

    if signing_key_shard_payloads:
        for shard in sorted(signing_key_shard_payloads, key=lambda item: item.share_index):
            rows.append(
                {
                    "component_id": f"SIGNING-SHARD-{shard.share_index:02d}",
                    "detail": (f"Signing-key shard {shard.share_index} of {shard.share_count}"),
                    "status": "Generated",
                }
            )

    return rows


def _render_shard(
    shard: ShardPayload,
    *,
    doc_id: bytes,
    output_dir: str,
    render_service: RenderService,
    filename_prefix: str,
    template_path: str | Path,
    doc_type: str | None = None,
) -> str:
    """Render a single shard document to PDF and return the output path."""
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
        f"{filename_prefix}-{doc_id.hex()}-{shard.share_index}-of-{shard.share_count}.pdf",
    )
    shard_inputs = render_service.shard_inputs(
        shard_frame,
        shard_path,
        shard_index=shard.share_index,
        shard_total=shard.share_count,
        shard_threshold=shard.threshold,
        qr_payloads=render_service.build_qr_payloads([shard_frame]),
        template_path=template_path,
        doc_type=doc_type,
    )
    render_module.render_frames_to_pdf(shard_inputs)
    return shard_path


def _prepare_envelope(
    input_files: list[InputFile],
    plan: DocumentPlan,
    sign_priv: bytes,
) -> tuple[bytes, bytes]:
    """Prepare the envelope from input files. Returns (envelope, payload)."""
    parts = [
        PayloadPart(path=item.relative_path, data=item.data, mtime=item.mtime)
        for item in input_files
    ]
    manifest, payload = envelope_codec_module.build_manifest_and_payload(
        parts,
        sealed=plan.sealed,
        signing_seed=sign_priv if not plan.sealed else None,
    )
    envelope = envelope_codec_module.encode_envelope(payload, manifest)
    return envelope, payload


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
    status_quiet: bool,
) -> tuple[list[ShardPayload], list[ShardPayload]]:
    """Create shard payloads for passphrase and signing key.

    Returns (shard_payloads, signing_key_shard_payloads).
    """
    plan_sharding = plan.sharding
    signing_key_sharding = plan.signing_seed_sharding or plan.sharding
    shard_payloads: list[ShardPayload] = []
    signing_key_shard_payloads: list[ShardPayload] = []

    if plan_sharding is not None:
        with status("Creating shard payloads...", quiet=status_quiet):
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
            with status("Creating signing key shard payloads...", quiet=status_quiet):
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
    config: AppConfig,
    status_quiet: bool,
) -> tuple[list[str], list[str]]:
    """Render all PDF documents. Returns (shard_paths, signing_key_shard_paths)."""
    shard_paths: list[str] = []
    signing_key_shard_paths: list[str] = []

    render_total = (
        2
        + (1 if kit_index_inputs is not None else 0)
        + (len(shard_payloads) if shard_payloads else 0)
        + (len(signing_key_shard_payloads) if signing_key_shard_payloads else 0)
    )

    with progress(quiet=status_quiet) as progress_bar:
        if progress_bar:
            shard_paths, signing_key_shard_paths = _render_with_progress(
                progress_bar=progress_bar,
                render_total=render_total,
                qr_inputs=qr_inputs,
                recovery_inputs=recovery_inputs,
                kit_index_inputs=kit_index_inputs,
                shard_payloads=shard_payloads,
                signing_key_shard_payloads=signing_key_shard_payloads,
                doc_id=doc_id,
                output_dir=output_dir,
                render_service=render_service,
                config=config,
            )
        else:
            shard_paths, signing_key_shard_paths = _render_without_progress(
                qr_inputs=qr_inputs,
                recovery_inputs=recovery_inputs,
                kit_index_inputs=kit_index_inputs,
                shard_payloads=shard_payloads,
                signing_key_shard_payloads=signing_key_shard_payloads,
                doc_id=doc_id,
                output_dir=output_dir,
                render_service=render_service,
                config=config,
                status_quiet=status_quiet,
            )

    return shard_paths, signing_key_shard_paths


def _render_with_progress(
    *,
    progress_bar: Progress,
    render_total: int,
    qr_inputs: RenderInputs,
    recovery_inputs: RenderInputs,
    kit_index_inputs: RenderInputs | None,
    shard_payloads: list[ShardPayload],
    signing_key_shard_payloads: list[ShardPayload],
    doc_id: bytes,
    output_dir: str,
    render_service: RenderService,
    config: AppConfig,
) -> tuple[list[str], list[str]]:
    """Render documents with progress bar."""
    shard_paths: list[str] = []
    signing_key_shard_paths: list[str] = []

    task_id = progress_bar.add_task("Rendering documents...", total=render_total)

    progress_bar.update(task_id, description="Rendering QR document...")
    render_module.render_frames_to_pdf(qr_inputs)
    progress_bar.advance(task_id)

    progress_bar.update(task_id, description="Rendering recovery document...")
    render_module.render_frames_to_pdf(recovery_inputs)
    progress_bar.advance(task_id)

    if kit_index_inputs is not None:
        progress_bar.update(task_id, description="Rendering recovery kit index...")
        render_module.render_frames_to_pdf(kit_index_inputs)
        progress_bar.advance(task_id)

    if shard_payloads:
        sorted_shards = sorted(shard_payloads, key=lambda shard: shard.share_index)
        total_shards = len(sorted_shards)
        for idx, shard in enumerate(sorted_shards, start=1):
            progress_bar.update(
                task_id, description=f"Rendering shard documents... ({idx}/{total_shards})"
            )
            shard_path = _render_shard(
                shard,
                doc_id=doc_id,
                output_dir=output_dir,
                render_service=render_service,
                filename_prefix="shard",
                template_path=config.shard_template_path,
            )
            shard_paths.append(shard_path)
            progress_bar.advance(task_id)

    if signing_key_shard_payloads:
        sorted_shards = sorted(signing_key_shard_payloads, key=lambda shard: shard.share_index)
        total_shards = len(sorted_shards)
        for idx, shard in enumerate(sorted_shards, start=1):
            progress_bar.update(
                task_id, description=f"Rendering signing key shards... ({idx}/{total_shards})"
            )
            shard_path = _render_shard(
                shard,
                doc_id=doc_id,
                output_dir=output_dir,
                render_service=render_service,
                filename_prefix="signing-key-shard",
                template_path=config.signing_key_shard_template_path,
                doc_type=DOC_TYPE_SIGNING_KEY_SHARD,
            )
            signing_key_shard_paths.append(shard_path)
            progress_bar.advance(task_id)

    return shard_paths, signing_key_shard_paths


def _render_without_progress(
    *,
    qr_inputs: RenderInputs,
    recovery_inputs: RenderInputs,
    kit_index_inputs: RenderInputs | None,
    shard_payloads: list[ShardPayload],
    signing_key_shard_payloads: list[ShardPayload],
    doc_id: bytes,
    output_dir: str,
    render_service: RenderService,
    config: AppConfig,
    status_quiet: bool,
) -> tuple[list[str], list[str]]:
    """Render documents without progress bar (using status messages)."""
    shard_paths: list[str] = []
    signing_key_shard_paths: list[str] = []

    with status("Rendering QR document...", quiet=status_quiet):
        render_module.render_frames_to_pdf(qr_inputs)

    with status("Rendering recovery document...", quiet=status_quiet):
        render_module.render_frames_to_pdf(recovery_inputs)

    if kit_index_inputs is not None:
        with status("Rendering recovery kit index...", quiet=status_quiet):
            render_module.render_frames_to_pdf(kit_index_inputs)

    if shard_payloads:
        with status("Rendering shard documents...", quiet=status_quiet):
            sorted_shards = sorted(shard_payloads, key=lambda shard: shard.share_index)
            for shard in sorted_shards:
                shard_path = _render_shard(
                    shard,
                    doc_id=doc_id,
                    output_dir=output_dir,
                    render_service=render_service,
                    filename_prefix="shard",
                    template_path=config.shard_template_path,
                )
                shard_paths.append(shard_path)

    if signing_key_shard_payloads:
        with status("Rendering signing key shards...", quiet=status_quiet):
            sorted_shards = sorted(signing_key_shard_payloads, key=lambda shard: shard.share_index)
            for shard in sorted_shards:
                shard_path = _render_shard(
                    shard,
                    doc_id=doc_id,
                    output_dir=output_dir,
                    render_service=render_service,
                    filename_prefix="signing-key-shard",
                    template_path=config.signing_key_shard_template_path,
                    doc_type=DOC_TYPE_SIGNING_KEY_SHARD,
                )
                signing_key_shard_paths.append(shard_path)

    return shard_paths, signing_key_shard_paths


def run_backup(
    *,
    input_files: list[InputFile],
    base_dir: Path | None,
    output_dir: str | None,
    plan: DocumentPlan,
    passphrase: str | None,
    passphrase_words: int | None = None,
    config: AppConfig,
    debug: bool = False,
    debug_max_bytes: int | None = None,
    quiet: bool = False,
) -> BackupResult:
    """Run the backup process and generate PDF documents."""
    status_quiet = quiet or debug
    if not input_files:
        raise ValueError("at least one input file is required")

    with status("Starting backup...", quiet=status_quiet):
        pass

    # Generate signing keypair and determine key storage modes
    sign_priv, sign_pub = signing_module.generate_signing_keypair()
    store_signing_key = not plan.sealed
    shard_signing_key = (
        plan.sharding is not None
        and not plan.sealed
        and plan.signing_seed_mode == SigningSeedMode.SHARDED
    )

    # Prepare envelope and handle debug output
    with status("Preparing payload...", quiet=status_quiet):
        envelope, payload = _prepare_envelope(input_files, plan, sign_priv)
        manifest = envelope_codec_module.decode_envelope(envelope)[0]

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
            debug_max_bytes=_normalize_debug_max_bytes(debug_max_bytes),
        )

    # Encrypt payload
    with status("Encrypting payload...", quiet=status_quiet):
        ciphertext, passphrase_used = encrypt_bytes_with_passphrase(
            envelope, passphrase=passphrase, passphrase_words=passphrase_words
        )
    if len(ciphertext) > MAX_CIPHERTEXT_BYTES:
        raise ValueError(
            f"ciphertext exceeds MAX_CIPHERTEXT_BYTES ({MAX_CIPHERTEXT_BYTES}): "
            f"{len(ciphertext)} bytes"
        )
    if passphrase_used is None:
        raise ValueError("passphrase generation failed")
    passphrase_final = passphrase if passphrase is not None else passphrase_used

    # Build key lines for recovery document
    plan_sharding = plan.sharding
    if plan_sharding is not None:
        key_lines = [
            "Passphrase is sharded.",
            f"Recover with {plan_sharding.threshold} of {plan_sharding.shares} shard documents.",
        ]
    else:
        key_lines = ["Passphrase:", passphrase_final]

    # Create document identifiers and auth frame
    doc_id, doc_hash = _doc_id_and_hash_from_ciphertext(ciphertext)
    auth_frame = _create_auth_frame(doc_id, doc_hash, sign_priv, sign_pub)

    # Create shard payloads if sharding is enabled
    if plan_sharding is not None and passphrase_final is None:
        raise ValueError("passphrase is required for sharding")
    shard_payloads, signing_key_shard_payloads = _create_shard_payloads(
        plan, passphrase_final or "", doc_hash, sign_priv, sign_pub, shard_signing_key, status_quiet
    )

    _append_signing_key_lines(
        key_lines,
        sign_pub=sign_pub,
        sealed=plan.sealed,
        stored_in_main=store_signing_key,
        stored_as_shards=shard_signing_key,
    )

    # Prepare render inputs
    main_chunk_size = choose_frame_chunk_size(
        len(ciphertext),
        preferred_chunk_size=config.qr_chunk_size,
        doc_id=doc_id,
        frame_type=FrameType.MAIN_DOCUMENT,
        qr_config=config.qr_config,
    )
    if main_chunk_size < config.qr_chunk_size:
        _warn(
            (
                f"Requested QR chunk size ({config.qr_chunk_size} bytes) was reduced to "
                f"{main_chunk_size} bytes to fit current QR settings."
            ),
            quiet=quiet,
        )
    frames = chunk_payload(
        ciphertext,
        doc_id=doc_id,
        frame_type=FrameType.MAIN_DOCUMENT,
        chunk_size=main_chunk_size,
    )
    qr_frames = [*frames, auth_frame]
    output_dir = _ensure_output_dir(output_dir, doc_id.hex())
    qr_path = os.path.join(output_dir, "qr_document.pdf")
    recovery_path = os.path.join(output_dir, "recovery_document.pdf")
    kit_index_template = _resolve_kit_index_template_path(config)
    kit_index_path = None
    if kit_index_template is not None:
        kit_index_path = os.path.join(output_dir, "recovery_kit_index.pdf")

    render_service = RenderService(config)
    qr_payloads = render_service.build_qr_payloads(qr_frames)
    qr_inputs = render_service.qr_inputs(qr_frames, qr_path, qr_payloads=qr_payloads)
    kit_index_context = render_service.base_context(
        {
            "inventory_rows": _build_kit_index_inventory_rows(
                shard_payloads=shard_payloads,
                signing_key_shard_payloads=signing_key_shard_payloads,
            )
        }
    )
    kit_index_inputs = (
        render_service.kit_inputs(
            qr_frames,
            kit_index_path,
            qr_payloads=qr_payloads,
            context=kit_index_context,
            template_path=kit_index_template,
        )
        if kit_index_template is not None and kit_index_path is not None
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
        frames, recovery_path, key_lines=key_lines, fallback_sections=fallback_sections
    )

    # Render all documents
    shard_paths, signing_key_shard_paths = _render_all_documents(
        qr_inputs=qr_inputs,
        recovery_inputs=recovery_inputs,
        kit_index_inputs=kit_index_inputs,
        shard_payloads=shard_payloads,
        signing_key_shard_payloads=signing_key_shard_payloads,
        doc_id=doc_id,
        output_dir=output_dir,
        render_service=render_service,
        config=config,
        status_quiet=status_quiet,
    )

    return BackupResult(
        doc_id=doc_id,
        qr_path=qr_path,
        recovery_path=recovery_path,
        kit_index_path=kit_index_path,
        shard_paths=tuple(shard_paths),
        signing_key_shard_paths=tuple(signing_key_shard_paths),
        passphrase_used=passphrase_used,
    )
