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

from ethernity.core.bounds import MAX_MANIFEST_FILES
from ethernity.extensions import (
    ExtensionChainLink,
    extract_root_logical_state,
    reconstruct_latest_logical_state,
    validate_extension_chain,
)
from ethernity.formats.envelope_codec import build_manifest_and_payload
from ethernity.formats.envelope_types import PayloadPart
from ethernity.formats.extension_envelope import (
    ExtensionChunkingProfile,
    ExtensionChunkRecord,
    ExtensionChunkRef,
    ExtensionEnvelope,
    ExtensionFile,
    build_extension_header,
)
from ethernity.formats.extension_envelope_constants import CHUNK_ALGORITHM_FASTCDC, CHUNK_CODEC_RAW

ROOT_DOC_HASH = b"\x10" * 32
EXT1_DOC_HASH = b"\x20" * 32
EXT2_DOC_HASH = b"\x30" * 32
SIGNING_SEED = b"\x40" * 32


def _profile() -> ExtensionChunkingProfile:
    return ExtensionChunkingProfile(
        algorithm_id=CHUNK_ALGORITHM_FASTCDC,
        target_size=65536,
        min_size=16384,
        max_size=262144,
    )


def _raw_chunk(data: bytes) -> tuple[bytes, ExtensionChunkRecord]:
    chunk_id = hashlib.sha256(data).digest()
    return chunk_id, ExtensionChunkRecord(
        chunk_id=chunk_id,
        codec=CHUNK_CODEC_RAW,
        raw_len=len(data),
        data=data,
    )


def _payload_parts(count: int) -> tuple[PayloadPart, ...]:
    return tuple(
        PayloadPart(path=f"existing-{index:04d}.txt", data=b"x", mtime=index)
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
    def test_extract_root_logical_state(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (
                PayloadPart(path="alpha.txt", data=b"alpha", mtime=1),
                PayloadPart(path="beta.txt", data=b"beta", mtime=2),
            ),
            sealed=False,
            signing_seed=SIGNING_SEED,
            created_at=1.0,
            input_origin="directory",
            input_roots=("docs",),
        )

        state = extract_root_logical_state(manifest, payload)

        self.assertEqual([item.path for item in state], ["alpha.txt", "beta.txt"])
        self.assertEqual(state[0].data, b"alpha")
        self.assertEqual(state[1].data, b"beta")

    def test_reconstruct_latest_state_supports_chain_global_chunk_reuse(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (
                PayloadPart(path="alpha.txt", data=b"alpha", mtime=1),
                PayloadPart(path="beta.txt", data=b"beta", mtime=2),
            ),
            sealed=False,
            signing_seed=SIGNING_SEED,
            created_at=1.0,
            input_origin="directory",
            input_roots=("docs",),
        )
        alpha_chunk_id = hashlib.sha256(b"alpha").digest()
        changed_chunk_id, changed_chunk = _raw_chunk(b"ALPHA-CHANGED")

        ext1 = ExtensionChainLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionEnvelope(
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

        ext2 = ExtensionChainLink(
            doc_hash=EXT2_DOC_HASH,
            document=ExtensionEnvelope(
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

        latest = reconstruct_latest_logical_state(
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
            (PayloadPart(path="alpha.txt", data=b"alpha", mtime=1),),
            sealed=False,
            signing_seed=SIGNING_SEED,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )
        alpha_chunk_id = hashlib.sha256(b"alpha").digest()
        changed_chunk_id, changed_chunk = _raw_chunk(b"ALPHA-CHANGED")
        duplicate_alpha_chunk_id, duplicate_alpha_chunk = _raw_chunk(b"alpha")
        ext1 = ExtensionChainLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionEnvelope(
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
        ext2 = ExtensionChainLink(
            doc_hash=EXT2_DOC_HASH,
            document=ExtensionEnvelope(
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

        with self.assertRaisesRegex(ValueError, "newly introduced"):
            reconstruct_latest_logical_state(
                manifest,
                payload,
                root_doc_hash=ROOT_DOC_HASH,
                extensions=(ext1, ext2),
            )

    def test_validate_chain_rejects_parent_doc_hash_mismatch(self) -> None:
        chunk_id, chunk = _raw_chunk(b"x")
        link = ExtensionChainLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionEnvelope(
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

    def test_validate_chain_rejects_chunking_profile_drift(self) -> None:
        chunk_id, chunk = _raw_chunk(b"x")
        ext1 = ExtensionChainLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionEnvelope(
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
        ext2 = ExtensionChainLink(
            doc_hash=EXT2_DOC_HASH,
            document=ExtensionEnvelope(
                header=build_extension_header(
                    index=2,
                    parent_doc_hash=EXT1_DOC_HASH,
                    root_doc_hash=ROOT_DOC_HASH,
                    chunking=ExtensionChunkingProfile(
                        algorithm_id=CHUNK_ALGORITHM_FASTCDC,
                        target_size=32 * 1024,
                        min_size=8 * 1024,
                        max_size=128 * 1024,
                    ),
                    input_origin="file",
                    input_roots=(),
                    created_at=3,
                ),
                files=(
                    ExtensionFile(
                        path="y.bin",
                        size=1,
                        sha256=chunk_id,
                        mtime=None,
                        chunk_refs=(ExtensionChunkRef(chunk_id=chunk_id, uncompressed_len=1),),
                    ),
                ),
                chunks=(chunk,),
            ),
        )

        with self.assertRaisesRegex(ValueError, "chunking profile must match"):
            validate_extension_chain(root_doc_hash=ROOT_DOC_HASH, extensions=(ext1, ext2))

    def test_reconstruct_rejects_unresolved_chunk_references(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (PayloadPart(path="alpha.txt", data=b"alpha", mtime=1),),
            sealed=False,
            signing_seed=SIGNING_SEED,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )
        missing_chunk_id = hashlib.sha256(b"missing").digest()
        link = ExtensionChainLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionEnvelope(
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
            reconstruct_latest_logical_state(
                manifest,
                payload,
                root_doc_hash=ROOT_DOC_HASH,
                extensions=(link,),
            )

    def test_reconstruct_rejects_non_canonical_chunk_recipe(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (PayloadPart(path="root.txt", data=b"root", mtime=1),),
            sealed=False,
            signing_seed=SIGNING_SEED,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )
        full_data = b"abcdefgh"
        first_chunk_id, first_chunk = _raw_chunk(full_data[:1])
        second_chunk_id, second_chunk = _raw_chunk(full_data[1:])
        link = ExtensionChainLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionEnvelope(
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
            reconstruct_latest_logical_state(
                manifest,
                payload,
                root_doc_hash=ROOT_DOC_HASH,
                extensions=(link,),
            )

    def test_reconstruct_rejects_refs_exceeding_declared_size_before_concatenation(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (PayloadPart(path="root.txt", data=b"root", mtime=1),),
            sealed=False,
            signing_seed=SIGNING_SEED,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )
        chunk_id, chunk = _raw_chunk(b"ab")
        link = ExtensionChainLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionEnvelope(
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
            reconstruct_latest_logical_state(
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
        link = ExtensionChainLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionEnvelope(
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
            f"logical latest state exceeds MAX_MANIFEST_FILES \\({MAX_MANIFEST_FILES}\\): "
            f"{MAX_MANIFEST_FILES + 1} entries",
        ):
            reconstruct_latest_logical_state(
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
        link = ExtensionChainLink(
            doc_hash=EXT1_DOC_HASH,
            document=ExtensionEnvelope(
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

        latest = reconstruct_latest_logical_state(
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
