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

import hashlib
import unittest
from dataclasses import replace
from unittest import mock

import ethernity.extensions as extension_api
import ethernity.extensions.chain as chain_module
from ethernity.core.bounds import MAX_MANIFEST_FILES
from ethernity.crypto.signing import (
    AuthPayload,
    derive_public_key,
    generate_signing_keypair,
    sign_auth,
)
from ethernity.extensions import (
    AuthenticatedExtensionChainLink,
    ExtensionReplayError,
    replay_authenticated_chain,
)
from ethernity.extensions.chain import (
    _ExtensionDocumentLink,
    _replay_extension_candidate,
    extract_root_files,
)
from ethernity.formats.document_codec import build_manifest_and_payload
from ethernity.formats.extension_constants import CHUNK_ALGORITHM_FASTCDC, CHUNK_CODEC_RAW
from ethernity.formats.extension_document import (
    ExtensionChunkingProfile,
    ExtensionChunkRecord,
    ExtensionChunkRef,
    ExtensionDocument,
    ExtensionFile,
    build_extension_header,
)
from ethernity.formats.manifest import BackupFile, ManifestFile

ROOT_DOC_HASH = b"\x10" * 32
EXT1_DOC_HASH = b"\x20" * 32
EXT2_DOC_HASH = b"\x30" * 32
SIGNING_SEED = b"\x40" * 32


def _auth_payload(doc_hash: bytes, *, signing_seed: bytes = SIGNING_SEED) -> AuthPayload:
    sign_pub = derive_public_key(signing_seed)
    return AuthPayload(
        version=1,
        doc_hash=doc_hash,
        sign_pub=sign_pub,
        signature=sign_auth(doc_hash, sign_pub=sign_pub, sign_priv=signing_seed),
    )


def _authenticated_links(
    extensions: tuple[_ExtensionDocumentLink, ...],
) -> tuple[AuthenticatedExtensionChainLink, ...]:
    sign_pub = derive_public_key(SIGNING_SEED)
    return tuple(
        AuthenticatedExtensionChainLink(
            doc_hash=link.doc_hash,
            document=link.document,
            auth_payload=_auth_payload(link.doc_hash),
            expected_sign_pub=sign_pub,
        )
        for link in extensions
    )


def _replay_chain(
    manifest,
    payload: bytes,
    *,
    root_doc_hash: bytes,
    extensions: tuple[_ExtensionDocumentLink, ...],
):
    return replay_authenticated_chain(
        manifest,
        payload,
        root_doc_hash=root_doc_hash,
        root_auth_payload=_auth_payload(root_doc_hash),
        expected_sign_pub=derive_public_key(SIGNING_SEED),
        extensions=_authenticated_links(extensions),
        root_chunking=extensions[0].document.header.chunking if extensions else _profile(),
    )


def reconstruct_latest_files(
    manifest,
    payload: bytes,
    *,
    root_doc_hash: bytes,
    extensions: tuple[_ExtensionDocumentLink, ...],
):
    return _replay_chain(
        manifest,
        payload,
        root_doc_hash=root_doc_hash,
        extensions=extensions,
    ).files


def validate_extension_chain(
    *,
    root_doc_hash: bytes,
    extensions: tuple[_ExtensionDocumentLink, ...],
) -> ExtensionChunkingProfile:
    manifest, payload = build_manifest_and_payload(
        (BackupFile(path="root.txt", data=b"root", mtime=1),),
        sealed=False,
        signing_seed=SIGNING_SEED,
        input_origin="file",
        input_roots=(),
    )
    return _replay_chain(
        manifest,
        payload,
        root_doc_hash=root_doc_hash,
        extensions=extensions,
    ).chunking


def _profile() -> ExtensionChunkingProfile:
    return ExtensionChunkingProfile(
        algorithm_id=CHUNK_ALGORITHM_FASTCDC,
        target_size=16384,
        min_size=4096,
        max_size=65536,
    )


def _raw_chunk(data: bytes) -> tuple[bytes, ExtensionChunkRecord]:
    chunk_id = hashlib.sha256(data).digest()
    return chunk_id, ExtensionChunkRecord(
        chunk_id=chunk_id,
        codec=CHUNK_CODEC_RAW,
        raw_len=len(data),
        data=data,
    )


def _payload_parts(count: int) -> tuple[BackupFile, ...]:
    return tuple(
        BackupFile(path=f"existing-{index:04d}.txt", data=b"x", mtime=index)
        for index in range(count)
    )


def _malformed_extension_file(
    *,
    path: str,
    size: int,
    sha256: bytes,
    chunk_refs: tuple[ExtensionChunkRef, ...],
) -> ExtensionFile:
    file_entry = object.__new__(ExtensionFile)
    object.__setattr__(file_entry, "path", path)
    object.__setattr__(file_entry, "size", size)
    object.__setattr__(file_entry, "sha256", sha256)
    object.__setattr__(file_entry, "mtime", None)
    object.__setattr__(file_entry, "chunk_refs", chunk_refs)
    return file_entry


class TestExtensionChain(unittest.TestCase):
    def test_root_replay_rejects_file_ancestor_paths_without_encoding(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (BackupFile(path="a", data=b"root", mtime=1),),
            sealed=False,
            signing_seed=SIGNING_SEED,
        )
        manifest = replace(
            manifest,
            files=(
                *manifest.files,
                ManifestFile(path="a/b", size=0, sha256=hashlib.sha256(b"").digest(), mtime=1),
            ),
        )
        with self.assertRaisesRegex(ValueError, "ancestor of file"):
            _replay_chain(manifest, payload, root_doc_hash=ROOT_DOC_HASH, extensions=())

    def test_replay_rejects_ancestor_conflicts_with_retained_paths(self) -> None:
        for root_path, new_path in (
            ("a", "a/b"),
            ("a/b", "a"),
            ("caf\u00e9", "cafe\u0301/file"),
        ):
            with self.subTest(root_path=root_path, new_path=new_path):
                manifest, payload = build_manifest_and_payload(
                    (BackupFile(path=root_path, data=b"root", mtime=1),),
                    sealed=False,
                    signing_seed=SIGNING_SEED,
                )
                chunk_id, chunk = _raw_chunk(b"new")
                extension = ExtensionDocument(
                    header=build_extension_header(
                        index=1,
                        parent_doc_hash=ROOT_DOC_HASH,
                        root_doc_hash=ROOT_DOC_HASH,
                        chunking=_profile(),
                        input_origin="file",
                        input_roots=(),
                        created_at=2,
                    ),
                    files=(
                        ExtensionFile(
                            path=new_path,
                            size=3,
                            sha256=chunk_id,
                            mtime=2,
                            chunk_refs=(ExtensionChunkRef(chunk_id, 3),),
                        ),
                    ),
                    chunks=(chunk,),
                )
                validated_root = _replay_chain(
                    manifest,
                    payload,
                    root_doc_hash=ROOT_DOC_HASH,
                    extensions=(),
                )
                with self.assertRaisesRegex(ValueError, "ancestor of file"):
                    _replay_extension_candidate(validated_root, extension)
                with self.assertRaisesRegex(ExtensionReplayError, "ancestor of file") as caught:
                    _replay_chain(
                        manifest,
                        payload,
                        root_doc_hash=ROOT_DOC_HASH,
                        extensions=(_ExtensionDocumentLink(EXT1_DOC_HASH, extension),),
                    )
                self.assertEqual(caught.exception.failure_phase, "files")
                self.assertEqual(caught.exception.failing_index, 1)
                self.assertEqual(caught.exception.last_validated_head_index, 0)
                self.assertEqual(caught.exception.last_validated_head_hash, ROOT_DOC_HASH)

    def test_top_level_extension_facade_excludes_structural_chain_plumbing(self) -> None:
        self.assertIn("AuthenticatedExtensionChainLink", extension_api.__all__)
        self.assertIs(
            extension_api.AuthenticatedExtensionChainLink,
            AuthenticatedExtensionChainLink,
        )
        self.assertNotIn("ExtensionChainLink", extension_api.__all__)
        self.assertNotIn("build_chain_available_chunks", extension_api.__all__)
        self.assertIn("replay_authenticated_chain", extension_api.__all__)
        self.assertNotIn("reconstruct_authenticated_latest_files", extension_api.__all__)
        self.assertNotIn("validate_authenticated_extension_chain", extension_api.__all__)
        self.assertFalse(hasattr(extension_api, "ExtensionChainLink"))
        self.assertFalse(hasattr(extension_api, "build_chain_available_chunks"))

    def test_extract_root_files(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (
                BackupFile(path="alpha.txt", data=b"alpha", mtime=1),
                BackupFile(path="beta.txt", data=b"beta", mtime=2),
            ),
            sealed=False,
            signing_seed=SIGNING_SEED,
            created_at=1.0,
            input_origin="directory",
            input_roots=("docs",),
        )

        state = extract_root_files(manifest, payload)

        self.assertEqual([item.path for item in state], ["alpha.txt", "beta.txt"])
        self.assertEqual(state[0].data, b"alpha")
        self.assertEqual(state[1].data, b"beta")

    def test_known_chunk_ids_include_derived_root_and_extension_history(self) -> None:
        root_bytes = b"root A"
        extension_bytes = b"extension A"
        root_chunk_id = hashlib.sha256(root_bytes).digest()
        extension_chunk_id, extension_chunk = _raw_chunk(extension_bytes)
        extension = ExtensionDocument(
            header=build_extension_header(
                index=1,
                parent_doc_hash=ROOT_DOC_HASH,
                root_doc_hash=ROOT_DOC_HASH,
                chunking=_profile(),
                input_origin="file",
                input_roots=(),
                created_at=2,
            ),
            files=(
                ExtensionFile(
                    path="state.txt",
                    size=len(extension_bytes),
                    sha256=extension_chunk_id,
                    mtime=2,
                    chunk_refs=(ExtensionChunkRef(extension_chunk_id, len(extension_bytes)),),
                ),
            ),
            chunks=(extension_chunk,),
        )

        manifest, payload = build_manifest_and_payload(
            (BackupFile(path="state.txt", data=root_bytes, mtime=1),),
            sealed=False,
            signing_seed=SIGNING_SEED,
            input_origin="file",
            input_roots=(),
        )
        validated = _replay_chain(
            manifest,
            payload,
            root_doc_hash=ROOT_DOC_HASH,
            extensions=(_ExtensionDocumentLink(EXT1_DOC_HASH, extension),),
        )

        self.assertEqual(
            {chunk_id for chunk_id, _data in validated.available_chunks},
            {root_chunk_id, extension_chunk_id},
        )

    def test_authenticated_chain_link_verifies_root_signing_key(self) -> None:
        sign_priv, sign_pub = generate_signing_keypair()
        payload_bytes = b"extension payload"
        chunk_id, chunk = _raw_chunk(payload_bytes)
        document = ExtensionDocument(
            header=build_extension_header(
                index=1,
                parent_doc_hash=ROOT_DOC_HASH,
                root_doc_hash=ROOT_DOC_HASH,
                chunking=_profile(),
                input_origin="file",
                input_roots=(),
                created_at=2,
            ),
            files=(
                ExtensionFile(
                    path="new.txt",
                    size=len(payload_bytes),
                    sha256=chunk_id,
                    mtime=3,
                    chunk_refs=(
                        ExtensionChunkRef(
                            chunk_id=chunk_id,
                            uncompressed_len=len(payload_bytes),
                        ),
                    ),
                ),
            ),
            chunks=(chunk,),
        )
        auth_payload = AuthPayload(
            version=1,
            doc_hash=EXT1_DOC_HASH,
            sign_pub=sign_pub,
            signature=sign_auth(EXT1_DOC_HASH, sign_pub=sign_pub, sign_priv=sign_priv),
        )

        link = AuthenticatedExtensionChainLink(
            doc_hash=EXT1_DOC_HASH,
            document=document,
            auth_payload=auth_payload,
            expected_sign_pub=sign_pub,
        )

        manifest, payload = build_manifest_and_payload(
            (BackupFile(path="alpha.txt", data=b"alpha", mtime=1),),
            sealed=False,
            signing_seed=SIGNING_SEED,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )
        root_auth = AuthPayload(
            version=1,
            doc_hash=ROOT_DOC_HASH,
            sign_pub=sign_pub,
            signature=sign_auth(ROOT_DOC_HASH, sign_pub=sign_pub, sign_priv=sign_priv),
        )
        validated = replay_authenticated_chain(
            manifest,
            payload,
            root_doc_hash=ROOT_DOC_HASH,
            root_auth_payload=root_auth,
            expected_sign_pub=sign_pub,
            extensions=(link,),
            root_chunking=_profile(),
        )
        self.assertEqual(
            {item.path: item.data for item in validated.files}["new.txt"],
            payload_bytes,
        )

        with self.assertRaisesRegex(ValueError, "signing key"):
            AuthenticatedExtensionChainLink(
                doc_hash=EXT1_DOC_HASH,
                document=document,
                auth_payload=auth_payload,
                expected_sign_pub=b"\xff" * 32,
            )
        with self.assertRaisesRegex(ValueError, "signature"):
            AuthenticatedExtensionChainLink(
                doc_hash=EXT1_DOC_HASH,
                document=document,
                auth_payload=AuthPayload(
                    version=1,
                    doc_hash=EXT1_DOC_HASH,
                    sign_pub=sign_pub,
                    signature=b"\x00" * 64,
                ),
                expected_sign_pub=sign_pub,
            )

    def test_reconstruct_latest_state_supports_chain_global_chunk_reuse(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (
                BackupFile(path="alpha.txt", data=b"alpha", mtime=1),
                BackupFile(path="beta.txt", data=b"beta", mtime=2),
            ),
            sealed=False,
            signing_seed=SIGNING_SEED,
            created_at=1.0,
            input_origin="directory",
            input_roots=("docs",),
        )
        alpha_chunk_id = hashlib.sha256(b"alpha").digest()
        changed_chunk_id, changed_chunk = _raw_chunk(b"ALPHA-CHANGED")

        ext1 = _ExtensionDocumentLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionDocument(
                header=build_extension_header(
                    index=1,
                    parent_doc_hash=ROOT_DOC_HASH,
                    root_doc_hash=ROOT_DOC_HASH,
                    chunking=_profile(),
                    input_origin="directory",
                    input_roots=("docs",),
                    created_at=2,
                ),
                files=(
                    ExtensionFile(
                        path="alpha.txt",
                        size=len(b"ALPHA-CHANGED"),
                        sha256=changed_chunk_id,
                        mtime=3,
                        chunk_refs=(
                            ExtensionChunkRef(
                                chunk_id=changed_chunk_id,
                                uncompressed_len=len(b"ALPHA-CHANGED"),
                            ),
                        ),
                    ),
                    ExtensionFile(
                        path="copied-root.txt",
                        size=len(b"alpha"),
                        sha256=alpha_chunk_id,
                        mtime=4,
                        chunk_refs=(
                            ExtensionChunkRef(
                                chunk_id=alpha_chunk_id,
                                uncompressed_len=len(b"alpha"),
                            ),
                        ),
                    ),
                ),
                chunks=(changed_chunk,),
            ),
        )

        ext2 = _ExtensionDocumentLink(
            doc_hash=EXT2_DOC_HASH,
            document=ExtensionDocument(
                header=build_extension_header(
                    index=2,
                    parent_doc_hash=EXT1_DOC_HASH,
                    root_doc_hash=ROOT_DOC_HASH,
                    chunking=_profile(),
                    input_origin="directory",
                    input_roots=("docs",),
                    created_at=3,
                ),
                files=(
                    ExtensionFile(
                        path="copy-of-alpha.txt",
                        size=len(b"ALPHA-CHANGED"),
                        sha256=changed_chunk_id,
                        mtime=5,
                        chunk_refs=(
                            ExtensionChunkRef(
                                chunk_id=changed_chunk_id,
                                uncompressed_len=len(b"ALPHA-CHANGED"),
                            ),
                        ),
                    ),
                    ExtensionFile(
                        path="late-root-copy.txt",
                        size=len(b"alpha"),
                        sha256=alpha_chunk_id,
                        mtime=6,
                        chunk_refs=(
                            ExtensionChunkRef(
                                chunk_id=alpha_chunk_id,
                                uncompressed_len=len(b"alpha"),
                            ),
                        ),
                    ),
                ),
                chunks=(),
            ),
        )

        latest = reconstruct_latest_files(
            manifest,
            payload,
            root_doc_hash=ROOT_DOC_HASH,
            extensions=(ext1, ext2),
        )

        self.assertEqual(
            [item.path for item in latest],
            [
                "alpha.txt",
                "beta.txt",
                "copied-root.txt",
                "copy-of-alpha.txt",
                "late-root-copy.txt",
            ],
        )
        self.assertEqual({item.path: item.data for item in latest}["alpha.txt"], b"ALPHA-CHANGED")
        self.assertEqual(
            {item.path: item.data for item in latest}["copied-root.txt"],
            b"alpha",
        )
        self.assertEqual(
            {item.path: item.data for item in latest}["copy-of-alpha.txt"],
            b"ALPHA-CHANGED",
        )
        self.assertEqual(
            {item.path: item.data for item in latest}["late-root-copy.txt"],
            b"alpha",
        )

    def test_reconstruct_rejects_current_extension_chunk_already_available(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (BackupFile(path="alpha.txt", data=b"alpha", mtime=1),),
            sealed=False,
            signing_seed=SIGNING_SEED,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )
        alpha_chunk_id = hashlib.sha256(b"alpha").digest()
        changed_chunk_id, changed_chunk = _raw_chunk(b"ALPHA-CHANGED")
        duplicate_alpha_chunk_id, duplicate_alpha_chunk = _raw_chunk(b"alpha")
        ext1 = _ExtensionDocumentLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionDocument(
                header=build_extension_header(
                    index=1,
                    parent_doc_hash=ROOT_DOC_HASH,
                    root_doc_hash=ROOT_DOC_HASH,
                    chunking=_profile(),
                    input_origin="file",
                    input_roots=(),
                    created_at=2,
                ),
                files=(
                    ExtensionFile(
                        path="alpha.txt",
                        size=len(b"ALPHA-CHANGED"),
                        sha256=changed_chunk_id,
                        mtime=2,
                        chunk_refs=(
                            ExtensionChunkRef(
                                chunk_id=changed_chunk_id,
                                uncompressed_len=len(b"ALPHA-CHANGED"),
                            ),
                        ),
                    ),
                ),
                chunks=(changed_chunk,),
            ),
        )
        ext2 = _ExtensionDocumentLink(
            doc_hash=EXT2_DOC_HASH,
            document=ExtensionDocument(
                header=build_extension_header(
                    index=2,
                    parent_doc_hash=EXT1_DOC_HASH,
                    root_doc_hash=ROOT_DOC_HASH,
                    chunking=_profile(),
                    input_origin="file",
                    input_roots=(),
                    created_at=3,
                ),
                files=(
                    ExtensionFile(
                        path="root-copy.txt",
                        size=len(b"alpha"),
                        sha256=alpha_chunk_id,
                        mtime=3,
                        chunk_refs=(
                            ExtensionChunkRef(
                                chunk_id=alpha_chunk_id,
                                uncompressed_len=len(b"alpha"),
                            ),
                        ),
                    ),
                ),
                chunks=(duplicate_alpha_chunk,),
            ),
        )
        self.assertEqual(duplicate_alpha_chunk_id, alpha_chunk_id)

        with self.assertRaises(ExtensionReplayError) as caught:
            reconstruct_latest_files(
                manifest,
                payload,
                root_doc_hash=ROOT_DOC_HASH,
                extensions=(ext1, ext2),
            )
        self.assertIn("newly introduced", str(caught.exception))
        self.assertEqual(caught.exception.failure_phase, "chunks")
        self.assertEqual(caught.exception.failing_index, 2)
        self.assertEqual(caught.exception.failing_hash, EXT2_DOC_HASH)
        self.assertEqual(caught.exception.last_validated_head_index, 1)
        self.assertEqual(caught.exception.last_validated_head_hash, EXT1_DOC_HASH)

    def test_validated_chain_retains_chunks_for_future_append_deduplication(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (BackupFile(path="root.txt", data=b"root", mtime=1),),
            sealed=False,
            signing_seed=SIGNING_SEED,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )
        first_chunk_id, first_chunk = _raw_chunk(b"first")
        second_chunk_id, second_chunk = _raw_chunk(b"second")
        ext1 = _ExtensionDocumentLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionDocument(
                header=build_extension_header(
                    index=1,
                    parent_doc_hash=ROOT_DOC_HASH,
                    root_doc_hash=ROOT_DOC_HASH,
                    chunking=_profile(),
                    input_origin="file",
                    input_roots=(),
                    created_at=2,
                ),
                files=(
                    ExtensionFile(
                        path="first.txt",
                        size=len(b"first"),
                        sha256=first_chunk_id,
                        mtime=2,
                        chunk_refs=(
                            ExtensionChunkRef(
                                chunk_id=first_chunk_id,
                                uncompressed_len=len(b"first"),
                            ),
                        ),
                    ),
                ),
                chunks=(first_chunk,),
            ),
        )
        ext2 = _ExtensionDocumentLink(
            doc_hash=EXT2_DOC_HASH,
            document=ExtensionDocument(
                header=build_extension_header(
                    index=2,
                    parent_doc_hash=EXT1_DOC_HASH,
                    root_doc_hash=ROOT_DOC_HASH,
                    chunking=_profile(),
                    input_origin="file",
                    input_roots=(),
                    created_at=3,
                ),
                files=(
                    ExtensionFile(
                        path="second.txt",
                        size=len(b"second"),
                        sha256=second_chunk_id,
                        mtime=3,
                        chunk_refs=(
                            ExtensionChunkRef(
                                chunk_id=second_chunk_id,
                                uncompressed_len=len(b"second"),
                            ),
                        ),
                    ),
                ),
                chunks=(second_chunk,),
            ),
        )
        original_resolve = chain_module._resolve_extension_file_state
        snapshots: dict[str, set[bytes]] = {}

        def capture_available_chunks(file_entry, available_chunks, chunking):
            snapshots[file_entry.path] = set(available_chunks)
            return original_resolve(file_entry, available_chunks, chunking)

        with mock.patch(
            "ethernity.extensions.chain._resolve_extension_file_state",
            side_effect=capture_available_chunks,
        ):
            reconstruct_latest_files(
                manifest,
                payload,
                root_doc_hash=ROOT_DOC_HASH,
                extensions=(ext1, ext2),
            )

        self.assertIn(first_chunk_id, snapshots["second.txt"])
        self.assertIn(second_chunk_id, snapshots["second.txt"])

    def test_reconstruct_rejects_prior_extension_chunk_reintroduced_after_eviction(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (BackupFile(path="root.txt", data=b"root", mtime=1),),
            sealed=False,
            signing_seed=SIGNING_SEED,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )
        first_chunk_id, first_chunk = _raw_chunk(b"first")
        second_chunk_id, second_chunk = _raw_chunk(b"second")
        ext1 = _ExtensionDocumentLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionDocument(
                header=build_extension_header(
                    index=1,
                    parent_doc_hash=ROOT_DOC_HASH,
                    root_doc_hash=ROOT_DOC_HASH,
                    chunking=_profile(),
                    input_origin="file",
                    input_roots=(),
                    created_at=2,
                ),
                files=(
                    ExtensionFile(
                        path="first.txt",
                        size=len(b"first"),
                        sha256=first_chunk_id,
                        mtime=2,
                        chunk_refs=(
                            ExtensionChunkRef(
                                chunk_id=first_chunk_id,
                                uncompressed_len=len(b"first"),
                            ),
                        ),
                    ),
                ),
                chunks=(first_chunk,),
            ),
        )
        ext2 = _ExtensionDocumentLink(
            doc_hash=EXT2_DOC_HASH,
            document=ExtensionDocument(
                header=build_extension_header(
                    index=2,
                    parent_doc_hash=EXT1_DOC_HASH,
                    root_doc_hash=ROOT_DOC_HASH,
                    chunking=_profile(),
                    input_origin="file",
                    input_roots=(),
                    created_at=3,
                ),
                files=(
                    ExtensionFile(
                        path="first-copy.txt",
                        size=len(b"first"),
                        sha256=first_chunk_id,
                        mtime=3,
                        chunk_refs=(
                            ExtensionChunkRef(
                                chunk_id=first_chunk_id,
                                uncompressed_len=len(b"first"),
                            ),
                        ),
                    ),
                    ExtensionFile(
                        path="second.txt",
                        size=len(b"second"),
                        sha256=second_chunk_id,
                        mtime=3,
                        chunk_refs=(
                            ExtensionChunkRef(
                                chunk_id=second_chunk_id,
                                uncompressed_len=len(b"second"),
                            ),
                        ),
                    ),
                ),
                chunks=tuple(sorted((first_chunk, second_chunk), key=lambda item: item.chunk_id)),
            ),
        )

        with self.assertRaisesRegex(ValueError, "newly introduced"):
            reconstruct_latest_files(
                manifest,
                payload,
                root_doc_hash=ROOT_DOC_HASH,
                extensions=(ext1, ext2),
            )

    def test_validate_chain_rejects_parent_doc_hash_mismatch(self) -> None:
        chunk_id, chunk = _raw_chunk(b"x")
        link = _ExtensionDocumentLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionDocument(
                header=build_extension_header(
                    index=1,
                    parent_doc_hash=b"\x99" * 32,
                    root_doc_hash=ROOT_DOC_HASH,
                    chunking=_profile(),
                    input_origin="file",
                    input_roots=(),
                    created_at=2,
                ),
                files=(
                    ExtensionFile(
                        path="x.bin",
                        size=1,
                        sha256=chunk_id,
                        mtime=None,
                        chunk_refs=(ExtensionChunkRef(chunk_id=chunk_id, uncompressed_len=1),),
                    ),
                ),
                chunks=(chunk,),
            ),
        )

        with self.assertRaisesRegex(ValueError, "parent_doc_hash"):
            validate_extension_chain(root_doc_hash=ROOT_DOC_HASH, extensions=(link,))

    def test_reconstruct_rejects_unresolved_chunk_references(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (BackupFile(path="alpha.txt", data=b"alpha", mtime=1),),
            sealed=False,
            signing_seed=SIGNING_SEED,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )
        missing_chunk_id = hashlib.sha256(b"missing").digest()
        link = _ExtensionDocumentLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionDocument(
                header=build_extension_header(
                    index=1,
                    parent_doc_hash=ROOT_DOC_HASH,
                    root_doc_hash=ROOT_DOC_HASH,
                    chunking=_profile(),
                    input_origin="file",
                    input_roots=(),
                    created_at=2,
                ),
                files=(
                    ExtensionFile(
                        path="missing.bin",
                        size=len(b"missing"),
                        sha256=missing_chunk_id,
                        mtime=None,
                        chunk_refs=(
                            ExtensionChunkRef(
                                chunk_id=missing_chunk_id,
                                uncompressed_len=len(b"missing"),
                            ),
                        ),
                    ),
                ),
                chunks=(),
            ),
        )

        with self.assertRaisesRegex(ValueError, "unresolved chunk_id"):
            reconstruct_latest_files(
                manifest,
                payload,
                root_doc_hash=ROOT_DOC_HASH,
                extensions=(link,),
            )

    def test_reconstruct_rejects_mismatched_chunk_recipe(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (BackupFile(path="root.txt", data=b"root", mtime=1),),
            sealed=False,
            signing_seed=SIGNING_SEED,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )
        full_data = b"abcdefgh"
        first_chunk_id, first_chunk = _raw_chunk(full_data[:1])
        second_chunk_id, second_chunk = _raw_chunk(full_data[1:])
        link = _ExtensionDocumentLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionDocument(
                header=build_extension_header(
                    index=1,
                    parent_doc_hash=ROOT_DOC_HASH,
                    root_doc_hash=ROOT_DOC_HASH,
                    chunking=_profile(),
                    input_origin="file",
                    input_roots=(),
                    created_at=2,
                ),
                files=(
                    ExtensionFile(
                        path="bad.txt",
                        size=len(full_data),
                        sha256=hashlib.sha256(full_data).digest(),
                        mtime=None,
                        chunk_refs=(
                            ExtensionChunkRef(
                                chunk_id=first_chunk_id,
                                uncompressed_len=1,
                            ),
                            ExtensionChunkRef(
                                chunk_id=second_chunk_id,
                                uncompressed_len=7,
                            ),
                        ),
                    ),
                ),
                chunks=tuple(sorted((first_chunk, second_chunk), key=lambda item: item.chunk_id)),
            ),
        )

        with self.assertRaisesRegex(ValueError, "locked chunking profile"):
            reconstruct_latest_files(
                manifest,
                payload,
                root_doc_hash=ROOT_DOC_HASH,
                extensions=(link,),
            )

    def test_reconstruct_rejects_refs_exceeding_declared_size_before_concatenation(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (BackupFile(path="root.txt", data=b"root", mtime=1),),
            sealed=False,
            signing_seed=SIGNING_SEED,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )
        chunk_id, chunk = _raw_chunk(b"ab")
        link = _ExtensionDocumentLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionDocument(
                header=build_extension_header(
                    index=1,
                    parent_doc_hash=ROOT_DOC_HASH,
                    root_doc_hash=ROOT_DOC_HASH,
                    chunking=_profile(),
                    input_origin="file",
                    input_roots=(),
                    created_at=2,
                ),
                files=(
                    _malformed_extension_file(
                        path="bad-size.txt",
                        size=1,
                        sha256=hashlib.sha256(b"ab").digest(),
                        chunk_refs=(ExtensionChunkRef(chunk_id=chunk_id, uncompressed_len=2),),
                    ),
                ),
                chunks=(chunk,),
            ),
        )

        with self.assertRaisesRegex(ValueError, "exceed declared file size"):
            reconstruct_latest_files(
                manifest,
                payload,
                root_doc_hash=ROOT_DOC_HASH,
                extensions=(link,),
            )

    def test_reconstruct_latest_state_rejects_file_count_overflow(self) -> None:
        manifest, payload = build_manifest_and_payload(
            _payload_parts(MAX_MANIFEST_FILES),
            sealed=False,
            signing_seed=SIGNING_SEED,
            created_at=1.0,
            input_origin="directory",
            input_roots=("docs",),
        )
        chunk_id, chunk = _raw_chunk(b"new")
        link = _ExtensionDocumentLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionDocument(
                header=build_extension_header(
                    index=1,
                    parent_doc_hash=ROOT_DOC_HASH,
                    root_doc_hash=ROOT_DOC_HASH,
                    chunking=_profile(),
                    input_origin="directory",
                    input_roots=("docs",),
                    created_at=2,
                ),
                files=(
                    ExtensionFile(
                        path="new-file.txt",
                        size=len(b"new"),
                        sha256=chunk_id,
                        mtime=2,
                        chunk_refs=(
                            ExtensionChunkRef(chunk_id=chunk_id, uncompressed_len=len(b"new")),
                        ),
                    ),
                ),
                chunks=(chunk,),
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            f"latest file set exceeds MAX_MANIFEST_FILES \\({MAX_MANIFEST_FILES}\\): "
            f"{MAX_MANIFEST_FILES + 1} entries",
        ):
            reconstruct_latest_files(
                manifest,
                payload,
                root_doc_hash=ROOT_DOC_HASH,
                extensions=(link,),
            )

    def test_reconstruct_latest_state_allows_replacement_at_file_count_limit(self) -> None:
        manifest, payload = build_manifest_and_payload(
            _payload_parts(MAX_MANIFEST_FILES),
            sealed=False,
            signing_seed=SIGNING_SEED,
            created_at=1.0,
            input_origin="directory",
            input_roots=("docs",),
        )
        chunk_id, chunk = _raw_chunk(b"replacement")
        link = _ExtensionDocumentLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionDocument(
                header=build_extension_header(
                    index=1,
                    parent_doc_hash=ROOT_DOC_HASH,
                    root_doc_hash=ROOT_DOC_HASH,
                    chunking=_profile(),
                    input_origin="directory",
                    input_roots=("docs",),
                    created_at=2,
                ),
                files=(
                    ExtensionFile(
                        path="existing-0042.txt",
                        size=len(b"replacement"),
                        sha256=chunk_id,
                        mtime=2,
                        chunk_refs=(
                            ExtensionChunkRef(
                                chunk_id=chunk_id,
                                uncompressed_len=len(b"replacement"),
                            ),
                        ),
                    ),
                ),
                chunks=(chunk,),
            ),
        )

        latest = reconstruct_latest_files(
            manifest,
            payload,
            root_doc_hash=ROOT_DOC_HASH,
            extensions=(link,),
        )

        self.assertEqual(len(latest), MAX_MANIFEST_FILES)
        self.assertEqual(
            {item.path: item.data for item in latest}["existing-0042.txt"],
            b"replacement",
        )

    def test_reconstruct_latest_state_checks_final_latest_state_size(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (
                BackupFile(path="a.bin", data=b"a" * 5, mtime=1),
                BackupFile(path="z.bin", data=b"z" * 20, mtime=1),
            ),
            sealed=False,
            signing_seed=SIGNING_SEED,
            created_at=1.0,
            input_origin="directory",
            input_roots=("docs",),
        )
        grown_chunk_id, grown_chunk = _raw_chunk(b"a" * 20)
        shrunk_chunk_id, shrunk_chunk = _raw_chunk(b"z" * 5)
        link = _ExtensionDocumentLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionDocument(
                header=build_extension_header(
                    index=1,
                    parent_doc_hash=ROOT_DOC_HASH,
                    root_doc_hash=ROOT_DOC_HASH,
                    chunking=_profile(),
                    input_origin="directory",
                    input_roots=("docs",),
                    created_at=2,
                ),
                files=(
                    ExtensionFile(
                        path="a.bin",
                        size=20,
                        sha256=grown_chunk_id,
                        mtime=2,
                        chunk_refs=(
                            ExtensionChunkRef(chunk_id=grown_chunk_id, uncompressed_len=20),
                        ),
                    ),
                    ExtensionFile(
                        path="z.bin",
                        size=5,
                        sha256=shrunk_chunk_id,
                        mtime=2,
                        chunk_refs=(
                            ExtensionChunkRef(chunk_id=shrunk_chunk_id, uncompressed_len=5),
                        ),
                    ),
                ),
                chunks=tuple(sorted((grown_chunk, shrunk_chunk), key=lambda item: item.chunk_id)),
            ),
        )

        with mock.patch("ethernity.extensions.chain.MAX_DECOMPRESSED_PAYLOAD_BYTES", 25):
            latest = reconstruct_latest_files(
                manifest,
                payload,
                root_doc_hash=ROOT_DOC_HASH,
                extensions=(link,),
            )

        self.assertEqual({item.path: item.size for item in latest}, {"a.bin": 20, "z.bin": 5})
