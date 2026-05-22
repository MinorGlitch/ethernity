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
from unittest import mock

from ethernity.cli.shared.types import InputFile
from ethernity.core.bounds import MAX_DECOMPRESSED_PAYLOAD_BYTES, MAX_MANIFEST_FILES
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


def _text_profile() -> ExtensionChunkingProfile:
    return ExtensionChunkingProfile(
        algorithm_id=CHUNK_ALGORITHM_FASTCDC,
        target_size=16 * 1024,
        min_size=4 * 1024,
        max_size=64 * 1024,
    )


def _chunk_offsets_and_hashes(chunks: tuple[bytes, ...]) -> tuple[list[int], list[str]]:
    offsets: list[int] = []
    offset = 0
    for chunk in chunks:
        offset += len(chunk)
        offsets.append(offset)
    hashes = [hashlib.sha256(chunk).hexdigest() for chunk in chunks]
    return offsets, hashes


class TestExtensionBuild(unittest.TestCase):
    def test_default_extension_chunker_matches_algorithm_1_conformance_vectors(self) -> None:
        profile = _text_profile()
        vectors = (
            (b"", [], []),
            (
                bytes(range(256)) * 512,
                [65536, 131072],
                [
                    "7daca2095d0438260fa849183dfc67faa459fdf4936e1bc91eec6b281b27e4c2",
                    "7daca2095d0438260fa849183dfc67faa459fdf4936e1bc91eec6b281b27e4c2",
                ],
            ),
            (
                b"".join(
                    hashlib.sha256(index.to_bytes(4, "big")).digest() for index in range(4096)
                ),
                [18096, 26931, 43917, 62046, 73496, 93396, 110690, 125496, 130017, 131072],
                [
                    "2ee1e2166281185f001965a7c45631c880b8732f3f48a3f23d61805da105dda8",
                    "eb1e03f0bac68f0171871be76601ab5e8ff1cd0b6ebe65fec952d4008d49d8ba",
                    "715518ae12c7f500032a27dd79d7605f65e3b407ee2fe4b069f6deb8234ad476",
                    "878633ff4a700041ebd6d4d852aed0215f6710cf6991d4f321a3b2fd2b2be830",
                    "782c360b17d0e7cf76562843a8a199572c79e424f914ec72a79b35c2a5953480",
                    "da2fa8816f90d81e80df05a7728bc46329dc0d77ea994cf91a21d4a4ae7d5fb1",
                    "67b130801247f8d07cd21510e6bc3f37bb5b6a382b68ce9d622e464585647b38",
                    "e8b033381f576d7d299a60c4fde4a718d3ebe2d15f6a914d2e5d5188108cc701",
                    "eb32376d8f8546f442fac429456036034c22a9cee10c70fd39c3f575abe5696e",
                    "dfd9fa02180e25f17871e98fd975ba8145952dc3e48f01b28ba4f1f8bee17df5",
                ],
            ),
            (
                ("alpha beta gamma delta\n" * 4096).encode("utf-8"),
                [65536, 94208],
                [
                    "bfa07175ee95b43642ae3fbcad382d7ecf5dd7fad2d496933ad68e7f14f803af",
                    "d4ffdf00862a1b920325b2fabc25e8621cbb7ce8171803702285b078fd0259c2",
                ],
            ),
        )

        for data, expected_offsets, expected_hashes in vectors:
            with self.subTest(size=len(data), chunks=len(expected_offsets)):
                chunks = default_extension_chunker(data, profile)
                offsets, hashes = _chunk_offsets_and_hashes(chunks)

                self.assertEqual(offsets, expected_offsets)
                self.assertEqual(hashes, expected_hashes)

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
        shared = b"shared bytes"

        built = build_extension_document(
            index=2,
            parent_doc_hash=b"\x11" * 32,
            root_doc_hash=b"\x22" * 32,
            chunking=_profile(),
            input_files=(
                InputFile(
                    source_path=None,
                    relative_path="alpha.txt",
                    data=shared,
                    mtime=1,
                ),
                InputFile(
                    source_path=None,
                    relative_path="beta.txt",
                    data=shared,
                    mtime=2,
                ),
            ),
            input_origin="file",
            input_roots=(),
            chunker=lambda data, _profile: (data,),
        )

        self.assertEqual(built.stats.changed_file_count, 2)
        self.assertEqual(built.stats.logical_bytes, len(shared) * 2)
        self.assertEqual(built.stats.new_chunks, 1)
        self.assertEqual(built.stats.reused_chunks, 1)
        self.assertEqual(len(built.document.files), 2)
        self.assertEqual(len(built.document.chunks), 1)
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
        shared = b"shared root bytes"
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
                    data=shared,
                    mtime=5,
                ),
            ),
            input_origin="file",
            input_roots=(),
            chunker=lambda data, _profile: (data,),
            existing_chunks={shared_chunk_id: shared},
        )

        self.assertEqual(built.stats.new_chunks, 0)
        self.assertEqual(built.stats.reused_chunks, 1)
        self.assertEqual(len(built.document.chunks), 0)
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

    def test_build_extension_document_rejects_noncanonical_chunking_recipe(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "locked extension chunking profile",
        ):
            build_extension_document(
                index=1,
                parent_doc_hash=b"\x10" * 32,
                root_doc_hash=b"\x20" * 32,
                chunking=_profile(),
                input_files=(
                    InputFile(
                        source_path=None,
                        relative_path="split.txt",
                        data=b"abcdefgh",
                        mtime=1,
                    ),
                ),
                input_origin="file",
                input_roots=(),
                chunker=lambda data, _profile: (data[:4], data[4:]),
            )

    def test_build_extension_document_prefers_gzip_when_chunk_is_smaller(self) -> None:
        compressible = b"A" * 8192

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
            hashlib.sha256(f"noise-{index}".encode("ascii")).digest() for index in range(128)
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
                existing_file_sizes={"existing.bin": MAX_DECOMPRESSED_PAYLOAD_BYTES - 4},
            )

    def test_build_extension_document_rejects_negative_existing_logical_bytes(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "existing logical bytes must be a non-negative int"
        ):
            build_extension_document(
                index=2,
                parent_doc_hash=b"\x10" * 32,
                root_doc_hash=b"\x20" * 32,
                chunking=_profile(),
                input_files=(
                    InputFile(
                        source_path=None,
                        relative_path="updated.bin",
                        data=b"updated",
                        mtime=1,
                    ),
                ),
                input_origin="file",
                input_roots=(),
                chunker=lambda data, _profile: (data,),
                existing_logical_bytes=-1,
            )

    def test_build_extension_document_requires_existing_file_sizes_with_existing_bytes(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "existing file sizes are required when existing logical bytes are set",
        ):
            build_extension_document(
                index=2,
                parent_doc_hash=b"\x10" * 32,
                root_doc_hash=b"\x20" * 32,
                chunking=_profile(),
                input_files=(
                    InputFile(
                        source_path=None,
                        relative_path="updated.bin",
                        data=b"updated",
                        mtime=1,
                    ),
                ),
                input_origin="file",
                input_roots=(),
                chunker=lambda data, _profile: (data,),
                existing_logical_bytes=7,
            )

    def test_build_extension_document_rejects_negative_existing_file_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "existing file size must be a non-negative int"):
            build_extension_document(
                index=2,
                parent_doc_hash=b"\x10" * 32,
                root_doc_hash=b"\x20" * 32,
                chunking=_profile(),
                input_files=(
                    InputFile(
                        source_path=None,
                        relative_path="updated.bin",
                        data=b"updated",
                        mtime=1,
                    ),
                ),
                input_origin="file",
                input_roots=(),
                chunker=lambda data, _profile: (data,),
                existing_logical_bytes=0,
                existing_file_sizes={"updated.bin": -1},
            )

    def test_build_extension_document_rejects_inconsistent_existing_state_total(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "existing logical bytes must match existing file size total",
        ):
            build_extension_document(
                index=2,
                parent_doc_hash=b"\x10" * 32,
                root_doc_hash=b"\x20" * 32,
                chunking=_profile(),
                input_files=(
                    InputFile(
                        source_path=None,
                        relative_path="updated.bin",
                        data=b"updated",
                        mtime=1,
                    ),
                ),
                input_origin="file",
                input_roots=(),
                chunker=lambda data, _profile: (data,),
                existing_logical_bytes=10,
                existing_file_sizes={"updated.bin": 2},
            )

    def test_build_extension_document_checks_final_latest_state_size(self) -> None:
        with mock.patch("ethernity.extensions.build.MAX_DECOMPRESSED_PAYLOAD_BYTES", 25):
            built = build_extension_document(
                index=2,
                parent_doc_hash=b"\x10" * 32,
                root_doc_hash=b"\x20" * 32,
                chunking=_profile(),
                input_files=(
                    InputFile(
                        source_path=None,
                        relative_path="a.bin",
                        data=b"a" * 20,
                        mtime=1,
                    ),
                    InputFile(
                        source_path=None,
                        relative_path="z.bin",
                        data=b"z" * 5,
                        mtime=1,
                    ),
                ),
                input_origin="file",
                input_roots=(),
                chunker=lambda data, _profile: (data,),
                existing_logical_bytes=25,
                existing_file_sizes={"a.bin": 5, "z.bin": 20},
            )

        self.assertEqual([item.path for item in built.document.files], ["a.bin", "z.bin"])

    def test_build_extension_document_rejects_latest_state_file_count_overflow(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            f"logical latest state exceeds MAX_MANIFEST_FILES \\({MAX_MANIFEST_FILES}\\): "
            f"{MAX_MANIFEST_FILES + 1} entries",
        ):
            build_extension_document(
                index=2,
                parent_doc_hash=b"\x10" * 32,
                root_doc_hash=b"\x20" * 32,
                chunking=_profile(),
                input_files=(
                    InputFile(
                        source_path=None,
                        relative_path="new-file.txt",
                        data=b"new",
                        mtime=1,
                    ),
                ),
                input_origin="file",
                input_roots=(),
                chunker=lambda data, _profile: (data,),
                existing_logical_bytes=MAX_MANIFEST_FILES,
                existing_file_sizes={
                    f"existing-{index:04d}.txt": 1 for index in range(MAX_MANIFEST_FILES)
                },
            )

    def test_build_extension_document_allows_replacement_at_file_count_limit(self) -> None:
        built = build_extension_document(
            index=2,
            parent_doc_hash=b"\x10" * 32,
            root_doc_hash=b"\x20" * 32,
            chunking=_profile(),
            input_files=(
                InputFile(
                    source_path=None,
                    relative_path="existing-0042.txt",
                    data=b"replacement",
                    mtime=1,
                ),
            ),
            input_origin="file",
            input_roots=(),
            chunker=lambda data, _profile: (data,),
            existing_logical_bytes=MAX_MANIFEST_FILES,
            existing_file_sizes={
                f"existing-{index:04d}.txt": 1 for index in range(MAX_MANIFEST_FILES)
            },
        )

        self.assertEqual([item.path for item in built.document.files], ["existing-0042.txt"])
