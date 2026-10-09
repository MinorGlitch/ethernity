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

"""Recovery trust validation and diagnostics shared by execution and inspection."""

from __future__ import annotations

import hmac
from collections.abc import Sequence
from dataclasses import dataclass

from ethernity.crypto.age_policy import RecoveryResourceLimitError
from ethernity.crypto.signing import AuthPayload, derive_public_key, verify_auth
from ethernity.extensions import chain, errors
from ethernity.formats.extension_document import ExtensionDocument
from ethernity.formats.manifest import BackupManifest


@dataclass(frozen=True)
class RootSigningKeyBinding:
    embedded_sign_pub: bytes | None
    mismatch: bool


def resolve_root_signing_key_binding(
    manifest: BackupManifest, auth_payload: AuthPayload | None
) -> RootSigningKeyBinding:
    if manifest.signing_seed is None:
        return RootSigningKeyBinding(embedded_sign_pub=None, mismatch=False)
    embedded_sign_pub = derive_public_key(manifest.signing_seed)
    mismatch = auth_payload is not None and auth_payload.sign_pub != embedded_sign_pub
    return RootSigningKeyBinding(embedded_sign_pub=embedded_sign_pub, mismatch=mismatch)


def validate_root_signing_key_binding(
    manifest: BackupManifest,
    auth_payload: AuthPayload | None,
    *,
    doc_hash: bytes,
) -> bytes | None:
    """Cryptographically validate root AUTH and its embedded signing key."""
    if auth_payload is not None:
        if not hmac.compare_digest(auth_payload.doc_hash, doc_hash):
            raise errors.ExtensionRecoveryError(
                code=errors.AUTH_DOC_HASH_MISMATCH,
                message="root AUTH doc_hash does not match the recovered root ciphertext",
                details={"stage": "auth"},
            )
        if not verify_auth(
            doc_hash, sign_pub=auth_payload.sign_pub, signature=auth_payload.signature
        ):
            raise errors.ExtensionRecoveryError(
                code=errors.AUTH_SIGNATURE_INVALID,
                message="root AUTH signature verification failed",
                details={"stage": "auth"},
            )
    key_binding = resolve_root_signing_key_binding(manifest, auth_payload)
    if key_binding.mismatch:
        raise errors.ExtensionRecoveryError(
            code=errors.ROOT_SIGNING_KEY_MISMATCH,
            message="embedded signing seed does not match the verified root AUTH signing key",
            details={"stage": "auth"},
        )
    return key_binding.embedded_sign_pub


@dataclass(frozen=True)
class RootValidationResult:
    signing_key: bytes | None
    signing_key_verified: bool | None
    error: errors.ExtensionRecoveryError | None = None

    def require_valid(self) -> bytes | None:
        if self.error is not None:
            raise self.error
        return self.signing_key


def inspect_root_validation(
    manifest: BackupManifest,
    auth_payload: AuthPayload | None,
    *,
    doc_hash: bytes,
    auth_status: str | None,
    require_signing_key: bool = False,
) -> RootValidationResult:
    """Assess authenticated recovery without replacing cryptographic checks with status text."""
    try:
        if auth_status != "verified" or auth_payload is None:
            raise errors.ExtensionRecoveryError(
                code=errors.RECOVERY_HEAD_UNTRUSTED,
                message=(
                    "extension import recovery requires verified root AUTH"
                    if require_signing_key
                    else f"root AUTH validation failed ({auth_status or 'missing'})"
                ),
                details={"stage": "auth", "root_auth_status": auth_status},
            )
        signing_key = validate_root_signing_key_binding(manifest, auth_payload, doc_hash=doc_hash)
        if require_signing_key and signing_key is None:
            raise errors.ExtensionRecoveryError(
                code=errors.RECOVERY_HEAD_UNTRUSTED,
                message="extension import recovery requires an unsealed root signing key",
                details={"stage": "auth"},
            )
    except errors.ExtensionRecoveryError as exc:
        exc.details.update(validated_head_index=None, validated_head_doc_hash=None)
        verified = False if exc.code == errors.ROOT_SIGNING_KEY_MISMATCH else None
        return RootValidationResult(None, verified, exc)
    return RootValidationResult(signing_key, True if signing_key is not None else None)


@dataclass(frozen=True)
class DecodedChainExtension:
    """Decoded extension input whose trust must still be checked."""

    doc_hash: bytes
    document: ExtensionDocument
    auth_payload: AuthPayload | None
    auth_status: str | None


@dataclass(frozen=True)
class ChainValidationResult:
    """Replay output or its structured failure, retaining the authenticated inputs."""

    root: RootValidationResult
    links: tuple[chain.AuthenticatedExtensionChainLink, ...] = ()
    state: chain.ValidatedChainState | None = None
    error: ValueError | None = None

    def require_state(self) -> chain.ValidatedChainState:
        if self.error is not None:
            raise self.error
        if self.state is None:
            raise RuntimeError("chain validation produced neither a state nor an error")
        return self.state


def _authenticate_extension(
    extension: DecodedChainExtension | chain.AuthenticatedExtensionChainLink,
    signing_key: bytes,
) -> chain.AuthenticatedExtensionChainLink:
    if isinstance(extension, chain.AuthenticatedExtensionChainLink):
        return extension
    if extension.auth_payload is None:
        raise ValueError("extension AUTH payload is missing")
    return chain.AuthenticatedExtensionChainLink(
        doc_hash=extension.doc_hash,
        document=extension.document,
        auth_payload=extension.auth_payload,
        expected_sign_pub=signing_key,
        auth_status=extension.auth_status or "missing",
    )


def inspect_chain_validation(
    manifest: BackupManifest,
    payload: bytes,
    *,
    root_doc_hash: bytes,
    root_auth_payload: AuthPayload | None,
    root_auth_status: str | None,
    extensions: Sequence[DecodedChainExtension | chain.AuthenticatedExtensionChainLink],
) -> ChainValidationResult:
    """Use the same root binding, extension authentication, and replay rules for both callers."""
    root = inspect_root_validation(
        manifest,
        root_auth_payload,
        doc_hash=root_doc_hash,
        auth_status=root_auth_status,
        require_signing_key=True,
    )
    if root.error is not None:
        return ChainValidationResult(root=root, error=root.error)
    assert root.signing_key is not None and root_auth_payload is not None
    links: list[chain.AuthenticatedExtensionChainLink] = []
    for extension in extensions:
        try:
            link = _authenticate_extension(extension, root.signing_key)
        except ValueError as exc:
            failure = chain.ExtensionReplayError(
                str(exc),
                failure_phase="auth",
                failing_index=extension.document.header.index,
                failing_hash=extension.doc_hash,
                last_validated_head_index=0,
                last_validated_head_hash=root_doc_hash,
            )
            failure.__cause__ = exc
            return ChainValidationResult(root=root, links=tuple(links), error=failure)
        links.append(link)
    try:
        if not links:
            raise ValueError("chain validation requires at least one extension")
        state = chain.replay_authenticated_chain(
            manifest,
            payload,
            root_doc_hash=root_doc_hash,
            root_auth_payload=root_auth_payload,
            expected_sign_pub=root.signing_key,
            extensions=links,
            root_chunking=links[0].document.header.chunking,
        )
    except RecoveryResourceLimitError:
        raise
    except ValueError as exc:
        return ChainValidationResult(root=root, links=tuple(links), error=exc)
    return ChainValidationResult(root=root, links=tuple(links), state=state)


__all__ = [
    "ChainValidationResult",
    "DecodedChainExtension",
    "RootSigningKeyBinding",
    "RootValidationResult",
    "inspect_chain_validation",
    "inspect_root_validation",
    "resolve_root_signing_key_binding",
    "validate_root_signing_key_binding",
]
