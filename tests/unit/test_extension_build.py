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

from ethernity.cli.shared.types import InputFile
from ethernity.core.bounds import MAX_DECOMPRESSED_PAYLOAD_BYTES
from ethernity.extensions import (
    build_extension_document,
    build_virtual_chunk_source,
    default_extension_chunker,
)
from ethernity.formats.extension_envelope import (
    ExtensionChunkingProfile,
)
from ethernity.formats.extension_envelope_constants import (
    CHUNK_ALGORITHM_FASTCDC,
    CHUNK_CODEC_GZIP,
    CHUNK_CODEC_RAW,
)


def _profile() -> ExtensionChunkingProfile:
    return ExtensionChunkingProfile(
        algorithm_id=CHUNK_ALGORITHM_FASTCDC,
        target_size=64 * 1024,
        min_size=16 * 1024,
        max_size=256 * 1024,
    )


class TestExtensionBuild(unittest.TestCase):
    def test_default_extension_chunker_is_deterministic_and_honors_bounds(self) -> None:
        profile = _profile()
        data = bytes(range(256)) * 2048

        first = default_extension_chunker(data, profile)
        second = default_extension_chunker(data, profile)

        self.assertEqual(first, second)
        self.assertGreater(len(first), 1)
        self.assertEqual(sum(len(chunk) for chunk in first), len(data))
        self.assertTrue(all(len(chunk) <= profile.max_size for chunk in first))
        self.assertTrue(all(len(chunk) >= profile.min_size for chunk in first[:-1]))

    def test_default_extension_chunker_reuses_chunks_after_small_prefix_insert(self) -> None:
        profile = _profile()
        base = b"".join(hashlib.sha256(index.to_bytes(4, "big")).digest() for index in range(16000))
        updated = b"prefix-" + base
        existing_chunks = build_virtual_chunk_source(
            (base,),
            chunking=profile,
            chunker=default_extension_chunker,
        )

        built = build_extension_document(
            index=2,
            parent_doc_hash=b"\x11" * 32,
            root_doc_hash=b"\x22" * 32,
            chunking=profile,
            input_files=(
                InputFile(
                    source_path=None,
                    relative_path="updated.bin",
                    data=updated,
                    mtime=1,
                ),
            ),
            input_origin="file",
            input_roots=(),
            chunker=default_extension_chunker,
            existing_chunks=existing_chunks,
        )

        self.assertGreater(built.stats.reused_chunks, 0)
        self.assertGreater(built.stats.new_chunks, 0)

    def test_build_extension_document_dedupes_reused_chunks(self) -> None:
        shared = b"shared"
        suffix_a = b"-a"
        suffix_b = b"-b"

        def chunker(data: bytes, _profile: ExtensionChunkingProfile) -> tuple[bytes, ...]:
            if data == shared + suffix_a:
                return (shared, suffix_a)
            if data == shared + suffix_b:
                return (shared, suffix_b)
            raise AssertionError(f"unexpected file bytes: {data!r}")

        built = build_extension_document(
            index=2,
            parent_doc_hash=b"\x11" * 32,
            root_doc_hash=b"\x22" * 32,
            chunking=_profile(),
            input_files=(
                InputFile(
                    source_path=None,
                    relative_path="alpha.txt",
                    data=shared + suffix_a,
                    mtime=1,
                ),
                InputFile(
                    source_path=None,
                    relative_path="beta.txt",
                    data=shared + suffix_b,
                    mtime=2,
                ),
            ),
            input_origin="file",
            input_roots=(),
            chunker=chunker,
        )

        self.assertEqual(built.stats.changed_file_count, 2)
        self.assertEqual(built.stats.logical_bytes, len(shared + suffix_a) + len(shared + suffix_b))
        self.assertEqual(built.stats.new_chunks, 3)
        self.assertEqual(built.stats.reused_chunks, 1)
        self.assertEqual(len(built.document.files), 2)
        self.assertEqual(len(built.document.chunks), 3)
        self.assertEqual([item.path for item in built.document.files], ["alpha.txt", "beta.txt"])
        self.assertEqual(
            built.document.files[0].chunk_refs[0].chunk_id,
            hashlib.sha256(shared).digest(),
        )
        self.assertEqual(
            built.document.files[1].chunk_refs[0].chunk_id,
            hashlib.sha256(shared).digest(),
        )

    def test_build_extension_document_sorts_by_normalized_manifest_path(self) -> None:
        built = build_extension_document(
            index=2,
            parent_doc_hash=b"\x11" * 32,
            root_doc_hash=b"\x22" * 32,
            chunking=_profile(),
            input_files=(
                InputFile(
                    source_path=None,
                    relative_path="o\u0308.txt",
                    data=b"a",
                    mtime=1,
                ),
                InputFile(
                    source_path=None,
                    relative_path="\u00f1.txt",
                    data=b"b",
                    mtime=2,
                ),
            ),
            input_origin="directory",
            input_roots=("root",),
            chunker=lambda data, _profile: (data,) if data else (),
        )

        self.assertEqual([item.path for item in built.document.files], ["\u00f1.txt", "\u00f6.txt"])

    def test_build_extension_document_supports_zero_length_files(self) -> None:
        built = build_extension_document(
            index=1,
            parent_doc_hash=b"\x10" * 32,
            root_doc_hash=b"\x20" * 32,
            chunking=_profile(),
            input_files=(
                InputFile(
                    source_path=None,
                    relative_path="empty.txt",
                    data=b"",
                    mtime=None,
                ),
            ),
            input_origin="file",
            input_roots=(),
            chunker=lambda data, _profile: (),
        )

        self.assertEqual(len(built.document.files), 1)
        self.assertEqual(len(built.document.files[0].chunk_refs), 0)
        self.assertEqual(len(built.document.chunks), 0)
        self.assertEqual(built.stats.new_chunks, 0)
        self.assertEqual(built.stats.reused_chunks, 0)

    def test_build_extension_document_reuses_virtual_root_chunks(self) -> None:
        shared = b"shared"
        suffix = b"-new"
        shared_chunk_id = hashlib.sha256(shared).digest()

        built = build_extension_document(
            index=2,
            parent_doc_hash=b"\x10" * 32,
            root_doc_hash=b"\x20" * 32,
            chunking=_profile(),
            input_files=(
                InputFile(
                    source_path=None,
                    relative_path="updated.txt",
                    data=shared + suffix,
                    mtime=5,
                ),
            ),
            input_origin="file",
            input_roots=(),
            chunker=lambda data, _profile: (data[: len(shared)], data[len(shared) :]),
            existing_chunks={shared_chunk_id: shared},
        )

        self.assertEqual(built.stats.new_chunks, 1)
        self.assertEqual(built.stats.reused_chunks, 1)
        self.assertEqual(len(built.document.chunks), 1)
        self.assertEqual(built.document.files[0].chunk_refs[0].chunk_id, shared_chunk_id)

    def test_build_extension_document_rejects_chunker_byte_mismatch(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "chunker output must preserve the original input bytes",
        ):
            build_extension_document(
                index=1,
                parent_doc_hash=b"\x10" * 32,
                root_doc_hash=b"\x20" * 32,
                chunking=_profile(),
                input_files=(
                    InputFile(
                        source_path=None,
                        relative_path="mismatch.txt",
                        data=b"abcdefgh",
                        mtime=1,
                    ),
                ),
                input_origin="file",
                input_roots=(),
                chunker=lambda data, _profile: (b"abcd", b"WXYZ"),
            )

    def test_build_extension_document_prefers_gzip_when_chunk_is_smaller(self) -> None:
        compressible = b"A" * 65536

        built = build_extension_document(
            index=1,
            parent_doc_hash=b"\x10" * 32,
            root_doc_hash=b"\x20" * 32,
            chunking=_profile(),
            input_files=(
                InputFile(
                    source_path=None,
                    relative_path="compressible.txt",
                    data=compressible,
                    mtime=1,
                ),
            ),
            input_origin="file",
            input_roots=(),
            chunker=lambda data, _profile: (data,),
        )

        self.assertEqual(len(built.document.chunks), 1)
        self.assertEqual(built.document.chunks[0].codec, CHUNK_CODEC_GZIP)
        self.assertEqual(built.document.chunks[0].decode_data(), compressible)

    def test_build_extension_document_keeps_raw_when_gzip_is_not_smaller(self) -> None:
        incompressible = b"".join(
            hashlib.sha256(f"noise-{index}".encode("ascii")).digest() for index in range(2048)
        )

        built = build_extension_document(
            index=1,
            parent_doc_hash=b"\x10" * 32,
            root_doc_hash=b"\x20" * 32,
            chunking=_profile(),
            input_files=(
                InputFile(
                    source_path=None,
                    relative_path="incompressible.bin",
                    data=incompressible,
                    mtime=1,
                ),
            ),
            input_origin="file",
            input_roots=(),
            chunker=lambda data, _profile: (data,),
        )

        self.assertEqual(len(built.document.chunks), 1)
        self.assertEqual(built.document.chunks[0].codec, CHUNK_CODEC_RAW)
        self.assertEqual(built.document.chunks[0].data, incompressible)

    def test_build_extension_document_rejects_incomplete_chunk_coverage(self) -> None:
        with self.assertRaisesRegex(ValueError, "fully cover"):
            build_extension_document(
                index=1,
                parent_doc_hash=b"\x10" * 32,
                root_doc_hash=b"\x20" * 32,
                chunking=_profile(),
                input_files=(
                    InputFile(
                        source_path=None,
                        relative_path="broken.txt",
                        data=b"abcdef",
                        mtime=None,
                    ),
                ),
                input_origin="file",
                input_roots=(),
                chunker=lambda data, _profile: (data[:3],),
            )

    def test_build_extension_document_rejects_latest_state_size_overflow(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "logical latest state exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES",
        ):
            build_extension_document(
                index=2,
                parent_doc_hash=b"\x10" * 32,
                root_doc_hash=b"\x20" * 32,
                chunking=_profile(),
                input_files=(
                    InputFile(
                        source_path=None,
                        relative_path="grown.bin",
                        data=b"b" * 8,
                        mtime=1,
                    ),
                ),
                input_origin="file",
                input_roots=(),
                chunker=lambda data, _profile: (data,),
                existing_logical_bytes=MAX_DECOMPRESSED_PAYLOAD_BYTES - 4,
                existing_file_sizes={"grown.bin": 0},
            )
