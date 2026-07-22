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
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

"""Published root-plus-extension chain inspection services."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ethernity.core.bounds import MAX_RECOVERY_DECODED_CHUNK_BYTES
from ethernity.crypto import sharding as sharding_module
from ethernity.crypto.document_identity import doc_id_from_doc_hash
from ethernity.encoding.frame_sets import deduplicate_identical_frames
from ethernity.encoding.framing import Frame, FrameType
from ethernity.extensions import errors as extension_errors
from ethernity.extensions.chain import (
    ExtensionReplayError,
    extract_root_logical_state,
    reconstruct_authenticated_latest_logical_state,
)
from ethernity.extensions.discovery import (
    DiscoveredExtensionMainCarrier,
    DiscoveredExtensionShardCarrier,
    discover_validated_extension_directories,
    payload_main_carriers,
)
from ethernity.extensions.recovery import (
    DecodedExtensionLink,
    ImportedRecoveryDocument,
    RecoveryChainInspection,
    RecoveryExtensionInventory,
    RecoveryHeadTrustRefusal,
    RecoveryReplayFailure,
    decode_authenticated_extension_link,
    resolve_required_auth_payload,
    validated_head_details,
)
from ethernity.formats import EnvelopeManifest

PublishedCarrierReader = Callable[[DiscoveredExtensionMainCarrier], ImportedRecoveryDocument]
PublishedShardFramesReader = Callable[[DiscoveredExtensionShardCarrier], list[Frame]]
PublishedRecoveryDocumentValidator = Callable[
    [DiscoveredExtensionMainCarrier, ImportedRecoveryDocument, bytes],
    None,
]


def inspect_published_extension_inventory(
    root_dir: Path,
    *,
    read_carrier_document: PublishedCarrierReader,
    read_shard_frames: PublishedShardFramesReader,
    validate_recovery_document_carrier: PublishedRecoveryDocumentValidator,
) -> RecoveryExtensionInventory:
    discovery = discover_validated_extension_directories(root_dir)
    extensions: list[ImportedRecoveryDocument] = []
    failure: RecoveryReplayFailure | None = None
    for item in discovery.directories:
        try:
            document, auth_sign_pub = _scan_published_extension_payload_carriers(
                item_dir_name=item.dir_name,
                filename_doc_id_hex=item.doc_id_hex,
                main_carriers=tuple(item.main_carriers),
                read_carrier_document=read_carrier_document,
                shard_carriers=tuple(item.shard_carriers),
                read_shard_frames=read_shard_frames,
                validate_recovery_document_carrier=validate_recovery_document_carrier,
            )
        except ValueError as exc:
            failure = RecoveryReplayFailure(
                stage="scan",
                message=str(exc),
                head_index=item.index,
                head_dir_name=item.dir_name,
            )
            break
        extensions.append(
            ImportedRecoveryDocument.from_ciphertext(
                ciphertext=document.ciphertext,
                auth_frames=document.auth_frames,
                source_label=item.dir_name,
                extension_index=item.index,
                extension_dir_name=item.dir_name,
            )
        )

    if failure is None and discovery.first_invalid_message is not None:
        failure = RecoveryReplayFailure(
            stage="layout",
            message=discovery.first_invalid_message,
            head_index=len(extensions) + 1,
            head_dir_name=discovery.first_invalid_dir_name,
        )
    latest = extensions[-1] if extensions else None
    return RecoveryExtensionInventory(
        extensions=tuple(extensions),
        latest_head_index=None if latest is None else latest.index,
        latest_head_doc_hash=None if latest is None else latest.doc_hash.hex(),
        latest_head_dir_name=None if latest is None else latest.dir_name,
        failure=failure,
    )


def _scan_published_extension_payload_carriers(
    *,
    item_dir_name: str,
    filename_doc_id_hex: str,
    main_carriers: tuple[DiscoveredExtensionMainCarrier, ...],
    read_carrier_document: PublishedCarrierReader,
    shard_carriers: tuple[DiscoveredExtensionShardCarrier, ...],
    read_shard_frames: PublishedShardFramesReader,
    validate_recovery_document_carrier: PublishedRecoveryDocumentValidator,
) -> tuple[ImportedRecoveryDocument, bytes]:
    document: ImportedRecoveryDocument | None = None
    auth_sign_pub: bytes | None = None
    for carrier in payload_main_carriers(main_carriers):
        candidate_document, candidate_auth_sign_pub = _scan_published_extension_payload_carrier(
            item_dir_name=item_dir_name,
            carrier=carrier,
            read_carrier_document=read_carrier_document,
        )
        if document is None:
            document = candidate_document
            auth_sign_pub = candidate_auth_sign_pub
            continue
        if candidate_document.ciphertext != document.ciphertext:
            raise ValueError(
                f"extension {item_dir_name} machine-readable MAIN carriers reconstruct "
                "different documents"
            )
        if candidate_auth_sign_pub != auth_sign_pub:
            raise ValueError(
                f"extension {item_dir_name} machine-readable MAIN carrier AUTH signing "
                "authorities differ"
            )
    if document is None or auth_sign_pub is None:
        raise ValueError(f"extension {item_dir_name} MAIN carriers could not be reconstructed")
    if filename_doc_id_hex != document.doc_id.hex():
        raise ValueError(
            f"extension {item_dir_name} canonical filename doc_id {filename_doc_id_hex} "
            f"does not match derived ciphertext doc_id {document.doc_id.hex()}"
        )
    recovery_document_carrier = _required_published_extension_main_carrier(
        item_dir_name=item_dir_name,
        main_carriers=main_carriers,
        doc_type="recovery_document",
    )
    try:
        validate_recovery_document_carrier(
            recovery_document_carrier,
            document,
            auth_sign_pub,
        )
    except Exception as exc:
        raise ValueError(
            f"extension {item_dir_name} recovery_document carrier could not be validated: {exc}"
        ) from exc
    _validate_published_extension_shard_carriers(
        item_dir_name=item_dir_name,
        shard_carriers=shard_carriers,
        read_shard_frames=read_shard_frames,
        document=document,
        expected_sign_pub=auth_sign_pub,
    )
    return document, auth_sign_pub


def _validate_published_extension_shard_carriers(
    *,
    item_dir_name: str,
    shard_carriers: tuple[DiscoveredExtensionShardCarrier, ...],
    read_shard_frames: PublishedShardFramesReader,
    document: ImportedRecoveryDocument,
    expected_sign_pub: bytes,
) -> None:
    payloads_by_type: dict[str, list[sharding_module.ShardPayload]] = {}
    for carrier in shard_carriers:
        try:
            frames = deduplicate_identical_frames(read_shard_frames(carrier))
            if len(frames) != 1:
                raise ValueError("carrier must contain exactly one shard payload")
            frame = frames[0]
            if frame.frame_type != FrameType.KEY_DOCUMENT:
                raise ValueError("carrier must contain a KEY_DOCUMENT frame")
            if frame.doc_id != document.doc_id:
                raise ValueError("shard frame doc_id does not match extension ciphertext")
            if frame.index != 0 or frame.total != 1:
                raise ValueError("shard payload must use one frame")
            payload = sharding_module.decode_shard_payload(frame.data)
            expected_key_type = (
                sharding_module.KEY_TYPE_PASSPHRASE
                if carrier.doc_type == "shard"
                else sharding_module.KEY_TYPE_SIGNING_SEED
            )
            if payload.key_type != expected_key_type:
                raise ValueError("shard key type does not match artifact role")
            if payload.share_index != carrier.share_index:
                raise ValueError("shard share_index does not match artifact filename")
            if payload.share_count != carrier.share_count:
                raise ValueError("shard share_count does not match artifact filename")
            if payload.doc_hash != document.doc_hash:
                raise ValueError("shard doc_hash does not match extension ciphertext")
            if payload.sign_pub != expected_sign_pub:
                raise ValueError("shard signing authority does not match extension AUTH")
        except Exception as exc:
            raise ValueError(
                f"extension {item_dir_name} {carrier.doc_type} carrier "
                f"{carrier.filename} could not be validated: {exc}"
            ) from exc
        payloads_by_type.setdefault(carrier.doc_type, []).append(payload)

    for doc_type, payloads in payloads_by_type.items():
        try:
            sharding_module.validate_shard_set_consistency(payloads)
        except ValueError as exc:
            raise ValueError(
                f"extension {item_dir_name} {doc_type} carrier set could not be validated: {exc}"
            ) from exc


def _required_published_extension_main_carrier(
    *,
    item_dir_name: str,
    main_carriers: tuple[DiscoveredExtensionMainCarrier, ...],
    doc_type: str,
) -> DiscoveredExtensionMainCarrier:
    for carrier in main_carriers:
        if carrier.doc_type == doc_type:
            return carrier
    raise ValueError(f"extension {item_dir_name} is missing required {doc_type} carrier")


def _scan_published_extension_payload_carrier(
    *,
    item_dir_name: str,
    carrier: DiscoveredExtensionMainCarrier,
    read_carrier_document: PublishedCarrierReader,
) -> tuple[ImportedRecoveryDocument, bytes]:
    try:
        if carrier.doc_type != "qr_document":
            raise ValueError(f"{carrier.doc_type} is not a machine-readable extension carrier")
        document = read_carrier_document(carrier)
        auth_payload, _auth_status = resolve_required_auth_payload(
            document.auth_frames,
            doc_id=document.doc_id,
            doc_hash=document.doc_hash,
        )
    except Exception as exc:
        raise ValueError(
            f"extension {item_dir_name} {carrier.doc_type} carrier could not be "
            f"independently reconstructed: {exc}"
        ) from exc
    return document, auth_payload.sign_pub


def extension_carrier_scan_failure(failure: Any) -> bool:
    message = str(getattr(failure, "message", ""))
    return (
        "MAIN carriers could not be reconstructed" in message
        or "MAIN carrier is not independently recoverable" in message
    )


def extension_chain_present(inventory: RecoveryExtensionInventory) -> bool:
    return bool(inventory.extensions) or inventory.failure is not None


def discovered_extension_indices(inventory: RecoveryExtensionInventory) -> tuple[int, ...]:
    if inventory.failure is not None and inventory.extensions:
        return ()
    indices = [item.index for item in inventory.extensions]
    if (
        inventory.failure is not None
        and inventory.failure.head_index is not None
        and extension_carrier_scan_failure(inventory.failure)
    ):
        if inventory.failure.head_index not in indices:
            indices.append(inventory.failure.head_index)
    return tuple(indices)


def inspect_published_extension_chain(
    *,
    manifest: EnvelopeManifest,
    payload: bytes,
    root_doc_hash: bytes,
    passphrase: str,
    expected_sign_pub: bytes | None,
    root_auth_status: str | None,
    quiet: bool,
    debug: bool,
    inventory: RecoveryExtensionInventory,
) -> RecoveryChainInspection:
    root_state = extract_root_logical_state(manifest, payload)
    if expected_sign_pub is None:
        return RecoveryChainInspection(
            inventory=inventory,
            links=(),
            latest_state=root_state,
            locked_chunking=None,
            refusal=RecoveryHeadTrustRefusal(
                code=extension_errors.RECOVERY_HEAD_UNTRUSTED,
                message="extension replay requires an unsealed root signing authority",
                details={"stage": "auth", "validated_head_index": 0},
            ),
            validated_head_index=0,
            validated_head_doc_hash=root_doc_hash.hex(),
            validated_head_auth_status=None,
            validated_head_root_authority_verified=False,
        )
    if inventory.extensions and root_auth_status != "verified":
        return RecoveryChainInspection(
            inventory=inventory,
            links=(),
            latest_state=root_state,
            locked_chunking=None,
            refusal=RecoveryHeadTrustRefusal(
                code=extension_errors.RECOVERY_HEAD_UNTRUSTED,
                message="extension replay requires verified root AUTH",
                details={
                    "stage": "auth",
                    "root_auth_status": root_auth_status,
                    "failed_extension_index": inventory.extensions[0].index,
                    "validated_head_index": 0,
                    "validated_head_doc_hash": root_doc_hash.hex(),
                },
            ),
            validated_head_index=0,
            validated_head_doc_hash=root_doc_hash.hex(),
            validated_head_auth_status=root_auth_status,
            validated_head_root_authority_verified=False,
        )

    links: list[DecodedExtensionLink] = []
    remaining_inline_chunk_bytes = MAX_RECOVERY_DECODED_CHUNK_BYTES
    for item in inventory.extensions:
        try:
            decoded = decode_authenticated_extension_link(
                item,
                passphrase=passphrase,
                expected_sign_pub=expected_sign_pub,
                quiet=quiet,
                debug=debug,
                max_inline_chunk_bytes=remaining_inline_chunk_bytes,
            )
            _validate_published_extension_header_index(item=item, decoded=decoded)
        except ValueError as exc:
            head_index, head_hash, head_auth, head_verified = validated_head_details(
                root_doc_hash,
                links,
            )
            return RecoveryChainInspection(
                inventory=inventory,
                links=tuple(links),
                latest_state=None,
                locked_chunking=None,
                refusal=RecoveryHeadTrustRefusal(
                    code=extension_errors.RECOVERY_HEAD_UNTRUSTED,
                    message=str(exc),
                    details={
                        "stage": "auth",
                        "failed_extension_index": item.index,
                        "validated_head_index": head_index,
                        "validated_head_doc_hash": head_hash,
                    },
                ),
                validated_head_index=head_index,
                validated_head_doc_hash=head_hash,
                validated_head_auth_status=head_auth,
                validated_head_root_authority_verified=head_verified,
            )
        remaining_inline_chunk_bytes -= decoded.link.document.inline_chunk_raw_bytes
        links.append(decoded)

    if not links:
        return RecoveryChainInspection(
            inventory=inventory,
            links=(),
            latest_state=root_state,
            locked_chunking=None,
            refusal=None,
            validated_head_index=0,
            validated_head_doc_hash=root_doc_hash.hex(),
            validated_head_auth_status=root_auth_status,
            validated_head_root_authority_verified=root_head_root_authority_verified(
                root_auth_status=root_auth_status,
                expected_sign_pub=expected_sign_pub,
            ),
        )

    try:
        latest_state = reconstruct_authenticated_latest_logical_state(
            manifest,
            payload,
            root_doc_hash=root_doc_hash,
            expected_sign_pub=expected_sign_pub,
            extensions=tuple(item.link for item in links),
        )
        locked_chunking = links[0].link.document.header.chunking
    except ExtensionReplayError as exc:
        validated_link = next(
            (
                item
                for item in links
                if item.link.document.header.index == exc.last_validated_head_index
                and item.link.doc_hash == exc.last_validated_head_hash
            ),
            None,
        )
        head_index = exc.last_validated_head_index
        head_hash = exc.last_validated_head_hash.hex()
        head_auth = None if validated_link is None else validated_link.auth_status
        head_verified = None if validated_link is None else validated_link.root_authority_verified
        return RecoveryChainInspection(
            inventory=inventory,
            links=tuple(links),
            latest_state=None,
            locked_chunking=None,
            refusal=RecoveryHeadTrustRefusal(
                code=extension_errors.RECOVERY_HEAD_UNTRUSTED,
                message=str(exc),
                details={
                    "stage": "replay",
                    "failure_stage": exc.failure_phase,
                    "failure_head_index": exc.failing_index,
                    "failure_head_doc_hash": exc.failing_hash.hex(),
                    "validated_head_index": head_index,
                    "validated_head_doc_hash": head_hash,
                },
            ),
            validated_head_index=head_index,
            validated_head_doc_hash=head_hash,
            validated_head_auth_status=head_auth,
            validated_head_root_authority_verified=head_verified,
        )

    latest = links[-1]
    return RecoveryChainInspection(
        inventory=inventory,
        links=tuple(links),
        latest_state=latest_state,
        locked_chunking=locked_chunking,
        refusal=None,
        validated_head_index=latest.link.document.header.index,
        validated_head_doc_hash=latest.link.doc_hash.hex(),
        validated_head_auth_status=latest.auth_status,
        validated_head_root_authority_verified=latest.root_authority_verified,
    )


def _validate_published_extension_header_index(
    *,
    item: ImportedRecoveryDocument,
    decoded: DecodedExtensionLink,
) -> None:
    filename_index = item.extension_index
    if filename_index is None:
        raise ValueError("published extension is missing its canonical filename index")
    header_index = decoded.link.document.header.index
    if filename_index != header_index:
        raise ValueError(
            f"canonical filename index {filename_index} does not match decrypted "
            f"header index {header_index}"
        )


def root_head_root_authority_verified(
    *,
    root_auth_status: str | None,
    expected_sign_pub: bytes | None,
) -> bool:
    return root_auth_status == "verified" and expected_sign_pub is not None


def available_extensions_from_recovery_chain(
    chain_inspection: RecoveryChainInspection,
) -> tuple[dict[str, object], ...]:
    available_extensions: list[dict[str, object]] = []
    inventory_by_identity = {
        (item.index, item.doc_hash): item for item in chain_inspection.inventory.extensions
    }
    for decoded_link in chain_inspection.links:
        index = decoded_link.link.document.header.index
        item = inventory_by_identity.get((index, decoded_link.link.doc_hash))
        extension_payload: dict[str, object] = {
            "index": index,
            "dir_name": item.dir_name if item is not None else f"extension-{index:02d}",
            "doc_id": (
                item.doc_id_hex
                if item is not None
                else doc_id_from_doc_hash(decoded_link.link.doc_hash).hex()
            ),
            "doc_hash": decoded_link.link.doc_hash.hex(),
        }
        extension_payload["auth_status"] = decoded_link.auth_status
        extension_payload["root_authority_verified"] = decoded_link.root_authority_verified
        available_extensions.append(extension_payload)
    return tuple(available_extensions)


def sorted_chunk_items(chunk_map: dict[bytes, bytes]) -> tuple[tuple[bytes, bytes], ...]:
    return tuple((chunk_id, chunk_map[chunk_id]) for chunk_id in sorted(chunk_map))


__all__ = [
    "PublishedCarrierReader",
    "PublishedShardFramesReader",
    "available_extensions_from_recovery_chain",
    "discovered_extension_indices",
    "extension_carrier_scan_failure",
    "extension_chain_present",
    "inspect_published_extension_chain",
    "inspect_published_extension_inventory",
    "root_head_root_authority_verified",
    "sorted_chunk_items",
]
