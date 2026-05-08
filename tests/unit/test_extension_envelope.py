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

import gzip
import hashlib
import unittest

from ethernity.core.bounds import MAX_DECOMPRESSED_PAYLOAD_BYTES
from ethernity.encoding.cbor import dumps_canonical
from ethernity.encoding.varint import encode_uvarint
from ethernity.formats.envelope_codec import (
    MAGIC,
    decode_any_envelope,
    decode_extension_envelope,
    encode_extension_envelope,
)
from ethernity.formats.extension_envelope import (
    ExtensionChunkingProfile,
    ExtensionChunkRecord,
    ExtensionChunkRef,
    ExtensionEnvelope,
    ExtensionEnvelopeHeader,
    ExtensionFile,
    build_extension_header,
)
from ethernity.formats.extension_envelope_constants import (
    CHUNK_ALGORITHM_FASTCDC,
    CHUNK_CODEC_GZIP,
    CHUNK_CODEC_RAW,
)

TEST_DOC_HASH = b"\x22" * 32
TEST_ROOT_DOC_HASH = b"\x33" * 32


def _make_profile() -> ExtensionChunkingProfile:
    return ExtensionChunkingProfile(
        algorithm_id=CHUNK_ALGORITHM_FASTCDC,
        target_size=64 * 1024,
        min_size=16 * 1024,
        max_size=256 * 1024,
    )


def _make_test_envelope() -> ExtensionEnvelope:
    chunk_bytes = b"hello extension"
    chunk_id = hashlib.sha256(chunk_bytes).digest()
    return ExtensionEnvelope(
        header=build_extension_header(
            index=1,
            parent_doc_hash=TEST_DOC_HASH,
            root_doc_hash=TEST_ROOT_DOC_HASH,
            chunking=_make_profile(),
            input_origin="file",
            input_roots=(),
            created_at=123,
        ),
        files=(
            ExtensionFile(
                path="docs/update.txt",
                size=len(chunk_bytes),
                sha256=chunk_id,
                mtime=1,
                chunk_refs=(
                    ExtensionChunkRef(
                        chunk_id=chunk_id,
                        uncompressed_len=len(chunk_bytes),
                    ),
                ),
            ),
        ),
        chunks=(
            ExtensionChunkRecord(
                chunk_id=chunk_id,
                codec=CHUNK_CODEC_RAW,
                raw_len=len(chunk_bytes),
                data=chunk_bytes,
            ),
        ),
    )


def _encode_sections(header: dict[int, object], body: dict[int, object]) -> bytes:
    header_bytes = dumps_canonical(header)
    body_bytes = dumps_canonical(body)
    return b"".join(
        (
            MAGIC,
            encode_uvarint(2),
            encode_uvarint(len(header_bytes)),
            header_bytes,
            encode_uvarint(len(body_bytes)),
            body_bytes,
        )
    )


def _non_canonical_uvarint(value: int) -> bytes:
    encoded = encode_uvarint(value)
    return encoded[:-1] + bytes((encoded[-1] | 0x80, 0))


class TestExtensionEnvelope(unittest.TestCase):
    def test_roundtrip_with_raw_chunk(self) -> None:
        chunk_bytes = b"hello extension"
        chunk_id = hashlib.sha256(chunk_bytes).digest()
        header = build_extension_header(
            index=1,
            parent_doc_hash=TEST_DOC_HASH,
            root_doc_hash=TEST_ROOT_DOC_HASH,
            chunking=_make_profile(),
            input_origin="file",
            input_roots=(),
            created_at=123,
        )
        envelope = ExtensionEnvelope(
            header=header,
            files=(
                ExtensionFile(
                    path="docs/update.txt",
                    size=len(chunk_bytes),
                    sha256=chunk_id,
                    mtime=1,
                    chunk_refs=(
                        ExtensionChunkRef(
                            chunk_id=chunk_id,
                            uncompressed_len=len(chunk_bytes),
                        ),
                    ),
                ),
            ),
            chunks=(
                ExtensionChunkRecord(
                    chunk_id=chunk_id,
                    codec=CHUNK_CODEC_RAW,
                    raw_len=len(chunk_bytes),
                    data=chunk_bytes,
                ),
            ),
        )

        decoded = ExtensionEnvelope.decode(envelope.encode())
        self.assertEqual(decoded.header.index, 1)
        reconstructed = decoded.reconstruct_files()
        self.assertEqual(reconstructed[0][0].path, "docs/update.txt")
        self.assertEqual(reconstructed[0][1], chunk_bytes)

    def test_reconstruct_accepts_available_chunks_outside_current_envelope(self) -> None:
        chunk_bytes = b"reused root chunk"
        chunk_id = hashlib.sha256(chunk_bytes).digest()
        header = build_extension_header(
            index=1,
            parent_doc_hash=TEST_DOC_HASH,
            root_doc_hash=TEST_ROOT_DOC_HASH,
            chunking=_make_profile(),
            input_origin="file",
            input_roots=(),
            created_at=123,
        )
        envelope = ExtensionEnvelope(
            header=header,
            files=(
                ExtensionFile(
                    path="docs/update.txt",
                    size=len(chunk_bytes),
                    sha256=chunk_id,
                    mtime=1,
                    chunk_refs=(
                        ExtensionChunkRef(
                            chunk_id=chunk_id,
                            uncompressed_len=len(chunk_bytes),
                        ),
                    ),
                ),
            ),
            chunks=(),
        )

        reconstructed = envelope.reconstruct_files(available_chunks={chunk_id: chunk_bytes})

        self.assertEqual(reconstructed[0][0].path, "docs/update.txt")
        self.assertEqual(reconstructed[0][1], chunk_bytes)

    def test_reconstruct_rejects_noncanonical_chunk_refs(self) -> None:
        file_bytes = b"abcdefgh"
        first = b"abcd"
        second = b"efgh"
        first_id = hashlib.sha256(first).digest()
        second_id = hashlib.sha256(second).digest()
        chunks = tuple(
            sorted(
                (
                    ExtensionChunkRecord(
                        chunk_id=first_id,
                        codec=CHUNK_CODEC_RAW,
                        raw_len=len(first),
                        data=first,
                    ),
                    ExtensionChunkRecord(
                        chunk_id=second_id,
                        codec=CHUNK_CODEC_RAW,
                        raw_len=len(second),
                        data=second,
                    ),
                ),
                key=lambda item: item.chunk_id,
            )
        )
        envelope = ExtensionEnvelope(
            header=build_extension_header(
                index=1,
                parent_doc_hash=TEST_DOC_HASH,
                root_doc_hash=TEST_ROOT_DOC_HASH,
                chunking=_make_profile(),
                input_origin="file",
                input_roots=(),
                created_at=123,
            ),
            files=(
                ExtensionFile(
                    path="docs/update.txt",
                    size=len(file_bytes),
                    sha256=hashlib.sha256(file_bytes).digest(),
                    mtime=1,
                    chunk_refs=(
                        ExtensionChunkRef(chunk_id=first_id, uncompressed_len=len(first)),
                        ExtensionChunkRef(chunk_id=second_id, uncompressed_len=len(second)),
                    ),
                ),
            ),
            chunks=chunks,
        )

        with self.assertRaisesRegex(ValueError, "locked chunking profile"):
            envelope.reconstruct_files()

    def test_directory_input_roots_preserve_whitespace(self) -> None:
        header = build_extension_header(
            index=1,
            parent_doc_hash=TEST_DOC_HASH,
            root_doc_hash=TEST_ROOT_DOC_HASH,
            chunking=_make_profile(),
            input_origin="directory",
            input_roots=(" demo ",),
            created_at=123,
        )

        self.assertEqual(header.input_roots, (" demo ",))

    def test_rejects_unknown_header_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown keys"):
            ExtensionEnvelopeHeader.from_cbor(
                {
                    1: 1,
                    2: 1,
                    4: TEST_DOC_HASH,
                    5: TEST_ROOT_DOC_HASH,
                    7: 123,
                    10: _make_profile().to_cbor(),
                    11: "file",
                    12: [],
                    99: "unexpected",
                }
            )

    def test_rejects_non_integer_header_keys(self) -> None:
        chunk_bytes = b"hello extension"
        chunk_id = hashlib.sha256(chunk_bytes).digest()
        envelope = ExtensionEnvelope(
            header=build_extension_header(
                index=1,
                parent_doc_hash=TEST_DOC_HASH,
                root_doc_hash=TEST_ROOT_DOC_HASH,
                chunking=_make_profile(),
                input_origin="file",
                input_roots=(),
                created_at=123,
            ),
            files=(
                ExtensionFile(
                    path="docs/update.txt",
                    size=len(chunk_bytes),
                    sha256=chunk_id,
                    mtime=1,
                    chunk_refs=(
                        ExtensionChunkRef(
                            chunk_id=chunk_id,
                            uncompressed_len=len(chunk_bytes),
                        ),
                    ),
                ),
            ),
            chunks=(
                ExtensionChunkRecord(
                    chunk_id=chunk_id,
                    codec=CHUNK_CODEC_RAW,
                    raw_len=len(chunk_bytes),
                    data=chunk_bytes,
                ),
            ),
        )
        _header, body = envelope.to_cbor_sections()
        malformed_header = {
            True: 1,
            2: 1,
            4: TEST_DOC_HASH,
            5: TEST_ROOT_DOC_HASH,
            7: 123,
            10: _make_profile().to_cbor(),
            11: "file",
            12: [],
        }
        malformed = b"".join(
            (
                MAGIC,
                encode_uvarint(2),
                encode_uvarint(len(dumps_canonical(malformed_header))),
                dumps_canonical(malformed_header),
                encode_uvarint(len(dumps_canonical(body))),
                dumps_canonical(body),
            )
        )

        with self.assertRaisesRegex(ValueError, "keys must be integers"):
            ExtensionEnvelope.decode(malformed)

    def test_rejects_mixed_type_header_keys_without_typeerror(self) -> None:
        chunk_bytes = b"hello extension"
        chunk_id = hashlib.sha256(chunk_bytes).digest()
        envelope = ExtensionEnvelope(
            header=build_extension_header(
                index=1,
                parent_doc_hash=TEST_DOC_HASH,
                root_doc_hash=TEST_ROOT_DOC_HASH,
                chunking=_make_profile(),
                input_origin="file",
                input_roots=(),
                created_at=123,
            ),
            files=(
                ExtensionFile(
                    path="docs/update.txt",
                    size=len(chunk_bytes),
                    sha256=chunk_id,
                    mtime=1,
                    chunk_refs=(
                        ExtensionChunkRef(
                            chunk_id=chunk_id,
                            uncompressed_len=len(chunk_bytes),
                        ),
                    ),
                ),
            ),
            chunks=(
                ExtensionChunkRecord(
                    chunk_id=chunk_id,
                    codec=CHUNK_CODEC_RAW,
                    raw_len=len(chunk_bytes),
                    data=chunk_bytes,
                ),
            ),
        )
        header, body = envelope.to_cbor_sections()
        header["unexpected"] = 1
        header[b"other"] = 2
        malformed = b"".join(
            (
                MAGIC,
                encode_uvarint(2),
                encode_uvarint(len(dumps_canonical(header))),
                dumps_canonical(header),
                encode_uvarint(len(dumps_canonical(body))),
                dumps_canonical(body),
            )
        )

        with self.assertRaisesRegex(ValueError, "keys must be integers"):
            ExtensionEnvelope.decode(malformed)

    def test_rejects_file_origin_with_non_empty_input_roots(self) -> None:
        with self.assertRaisesRegex(ValueError, "input_roots must be empty"):
            build_extension_header(
                index=1,
                parent_doc_hash=TEST_DOC_HASH,
                root_doc_hash=TEST_ROOT_DOC_HASH,
                chunking=_make_profile(),
                input_origin="file",
                input_roots=("demo",),
                created_at=123,
            )

    def test_rejects_directory_origin_with_empty_input_roots(self) -> None:
        with self.assertRaisesRegex(ValueError, "input_roots must be non-empty"):
            build_extension_header(
                index=1,
                parent_doc_hash=TEST_DOC_HASH,
                root_doc_hash=TEST_ROOT_DOC_HASH,
                chunking=_make_profile(),
                input_origin="directory",
                input_roots=(),
                created_at=123,
            )

    def test_rejects_unsupported_chunking_algorithm(self) -> None:
        with self.assertRaisesRegex(ValueError, "CHUNK_ALGORITHM_FASTCDC"):
            ExtensionChunkingProfile(
                algorithm_id=999,
                target_size=64 * 1024,
                min_size=16 * 1024,
                max_size=256 * 1024,
            )

    def test_rejects_unknown_body_keys(self) -> None:
        chunk_bytes = b"body"
        chunk_id = hashlib.sha256(chunk_bytes).digest()
        envelope = ExtensionEnvelope(
            header=build_extension_header(
                index=1,
                parent_doc_hash=TEST_DOC_HASH,
                root_doc_hash=TEST_ROOT_DOC_HASH,
                chunking=_make_profile(),
                input_origin="file",
                input_roots=(),
                created_at=123,
            ),
            files=(
                ExtensionFile(
                    path="payload.bin",
                    size=len(chunk_bytes),
                    sha256=chunk_id,
                    mtime=None,
                    chunk_refs=(
                        ExtensionChunkRef(
                            chunk_id=chunk_id,
                            uncompressed_len=len(chunk_bytes),
                        ),
                    ),
                ),
            ),
            chunks=(
                ExtensionChunkRecord(
                    chunk_id=chunk_id,
                    codec=CHUNK_CODEC_RAW,
                    raw_len=len(chunk_bytes),
                    data=chunk_bytes,
                ),
            ),
        )

        header, body = envelope.to_cbor_sections()
        body[99] = "unexpected"
        malformed = b"".join(
            (
                MAGIC,
                encode_uvarint(2),
                encode_uvarint(len(dumps_canonical(header))),
                dumps_canonical(header),
                encode_uvarint(len(dumps_canonical(body))),
                dumps_canonical(body),
            )
        )

        with self.assertRaisesRegex(ValueError, "unknown keys"):
            ExtensionEnvelope.decode(malformed)

    def test_reconstruct_rejects_gzip_trailing_bytes(self) -> None:
        chunk_bytes = b"gzip payload"
        compressed = gzip.compress(chunk_bytes, compresslevel=9, mtime=0) + b"tail"
        chunk_id = hashlib.sha256(chunk_bytes).digest()
        header = build_extension_header(
            index=1,
            parent_doc_hash=TEST_DOC_HASH,
            root_doc_hash=TEST_ROOT_DOC_HASH,
            chunking=_make_profile(),
            input_origin="file",
            input_roots=(),
            created_at=123,
        )
        envelope = ExtensionEnvelope(
            header=header,
            files=(
                ExtensionFile(
                    path="payload.bin",
                    size=len(chunk_bytes),
                    sha256=chunk_id,
                    mtime=None,
                    chunk_refs=(
                        ExtensionChunkRef(
                            chunk_id=chunk_id,
                            uncompressed_len=len(chunk_bytes),
                        ),
                    ),
                ),
            ),
            chunks=(
                ExtensionChunkRecord(
                    chunk_id=chunk_id,
                    codec=CHUNK_CODEC_GZIP,
                    raw_len=len(chunk_bytes),
                    data=compressed,
                ),
            ),
        )

        with self.assertRaisesRegex(ValueError, "trailing data|trailing"):
            envelope.reconstruct_files()

    def test_reconstruct_rejects_truncated_gzip_chunk(self) -> None:
        chunk_bytes = b"gzip payload"
        compressed = gzip.compress(chunk_bytes, compresslevel=9, mtime=0)[:-2]
        chunk_id = hashlib.sha256(chunk_bytes).digest()
        header = build_extension_header(
            index=1,
            parent_doc_hash=TEST_DOC_HASH,
            root_doc_hash=TEST_ROOT_DOC_HASH,
            chunking=_make_profile(),
            input_origin="file",
            input_roots=(),
            created_at=123,
        )
        envelope = ExtensionEnvelope(
            header=header,
            files=(
                ExtensionFile(
                    path="payload.bin",
                    size=len(chunk_bytes),
                    sha256=chunk_id,
                    mtime=None,
                    chunk_refs=(
                        ExtensionChunkRef(
                            chunk_id=chunk_id,
                            uncompressed_len=len(chunk_bytes),
                        ),
                    ),
                ),
            ),
            chunks=(
                ExtensionChunkRecord(
                    chunk_id=chunk_id,
                    codec=CHUNK_CODEC_GZIP,
                    raw_len=len(chunk_bytes),
                    data=compressed,
                ),
            ),
        )

        with self.assertRaisesRegex(ValueError, "invalid gzip chunk"):
            envelope.reconstruct_files()

    def test_reconstruct_rejects_gzip_chunk_short_of_raw_len(self) -> None:
        chunk_bytes = b"gzip payload"
        compressed = gzip.compress(chunk_bytes, compresslevel=9, mtime=0)
        chunk_id = hashlib.sha256(chunk_bytes).digest()
        header = build_extension_header(
            index=1,
            parent_doc_hash=TEST_DOC_HASH,
            root_doc_hash=TEST_ROOT_DOC_HASH,
            chunking=_make_profile(),
            input_origin="file",
            input_roots=(),
            created_at=123,
        )
        envelope = ExtensionEnvelope(
            header=header,
            files=(
                ExtensionFile(
                    path="payload.bin",
                    size=len(chunk_bytes),
                    sha256=chunk_id,
                    mtime=None,
                    chunk_refs=(
                        ExtensionChunkRef(
                            chunk_id=chunk_id,
                            uncompressed_len=len(chunk_bytes),
                        ),
                    ),
                ),
            ),
            chunks=(
                ExtensionChunkRecord(
                    chunk_id=chunk_id,
                    codec=CHUNK_CODEC_GZIP,
                    raw_len=len(chunk_bytes) + 1,
                    data=compressed,
                ),
            ),
        )

        with self.assertRaisesRegex(ValueError, "decoded chunk length does not match raw_len"):
            envelope.reconstruct_files()

    def test_encode_rejects_raw_chunk_length_mismatch(self) -> None:
        chunk_bytes = b"payload"
        chunk_id = hashlib.sha256(chunk_bytes).digest()
        envelope = ExtensionEnvelope(
            header=build_extension_header(
                index=1,
                parent_doc_hash=TEST_DOC_HASH,
                root_doc_hash=TEST_ROOT_DOC_HASH,
                chunking=_make_profile(),
                input_origin="file",
                input_roots=(),
                created_at=123,
            ),
            files=(
                ExtensionFile(
                    path="payload.bin",
                    size=len(chunk_bytes),
                    sha256=chunk_id,
                    mtime=None,
                    chunk_refs=(
                        ExtensionChunkRef(
                            chunk_id=chunk_id,
                            uncompressed_len=len(chunk_bytes),
                        ),
                    ),
                ),
            ),
            chunks=(
                ExtensionChunkRecord(
                    chunk_id=chunk_id,
                    codec=CHUNK_CODEC_RAW,
                    raw_len=len(chunk_bytes) + 1,
                    data=chunk_bytes,
                ),
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            "raw extension chunk data length must equal raw_len",
        ):
            envelope.encode()

    def test_decode_rejects_chunk_raw_len_over_payload_bound_before_decompression(self) -> None:
        envelope = _make_test_envelope()
        header, body = envelope.to_cbor_sections()
        chunk_record = list(body[2][0])
        chunk_record[1] = CHUNK_CODEC_GZIP
        chunk_record[2] = MAX_DECOMPRESSED_PAYLOAD_BYTES + 1
        chunk_record[3] = gzip.compress(b"x", compresslevel=9, mtime=0)
        body[2] = [chunk_record]

        with self.assertRaisesRegex(
            ValueError,
            "extension chunk raw_len exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES",
        ):
            ExtensionEnvelope.decode(_encode_sections(header, body))

    def test_decode_rejects_aggregate_inline_chunk_raw_len_over_payload_bound(self) -> None:
        envelope = _make_test_envelope()
        header, body = envelope.to_cbor_sections()
        raw_len = MAX_DECOMPRESSED_PAYLOAD_BYTES // 2 + 1
        body[2] = [
            [b"\x11" * 32, CHUNK_CODEC_GZIP, raw_len, gzip.compress(b"x", mtime=0)],
            [b"\x22" * 32, CHUNK_CODEC_GZIP, raw_len, gzip.compress(b"y", mtime=0)],
        ]

        with self.assertRaisesRegex(
            ValueError,
            "extension inline chunk bytes exceed MAX_DECOMPRESSED_PAYLOAD_BYTES",
        ):
            ExtensionEnvelope.decode(_encode_sections(header, body))

    def test_rejects_unordered_files(self) -> None:
        chunk_bytes = b"x"
        chunk_id = hashlib.sha256(chunk_bytes).digest()
        header = build_extension_header(
            index=2,
            parent_doc_hash=TEST_DOC_HASH,
            root_doc_hash=TEST_ROOT_DOC_HASH,
            chunking=_make_profile(),
            input_origin="directory",
            input_roots=("root",),
            created_at=123,
        )
        with self.assertRaisesRegex(ValueError, "ordered by normalized path"):
            ExtensionEnvelope(
                header=header,
                files=(
                    ExtensionFile(
                        path="z.txt",
                        size=1,
                        sha256=chunk_id,
                        mtime=None,
                        chunk_refs=(ExtensionChunkRef(chunk_id=chunk_id, uncompressed_len=1),),
                    ),
                    ExtensionFile(
                        path="a.txt",
                        size=1,
                        sha256=chunk_id,
                        mtime=None,
                        chunk_refs=(ExtensionChunkRef(chunk_id=chunk_id, uncompressed_len=1),),
                    ),
                ),
                chunks=(
                    ExtensionChunkRecord(
                        chunk_id=chunk_id,
                        codec=CHUNK_CODEC_RAW,
                        raw_len=1,
                        data=chunk_bytes,
                    ),
                ),
            )

    def test_decode_rejects_non_canonical_version_uvarint(self) -> None:
        envelope = _make_test_envelope()
        header, body = envelope.to_cbor_sections()
        header_bytes = dumps_canonical(header)
        body_bytes = dumps_canonical(body)
        malformed = b"".join(
            (
                MAGIC,
                b"\x82\x00",
                encode_uvarint(len(header_bytes)),
                header_bytes,
                encode_uvarint(len(body_bytes)),
                body_bytes,
            )
        )

        with self.assertRaisesRegex(ValueError, "non-canonical varint"):
            ExtensionEnvelope.decode(malformed)

    def test_decode_rejects_non_canonical_header_len_uvarint(self) -> None:
        envelope = _make_test_envelope()
        header, body = envelope.to_cbor_sections()
        header_bytes = dumps_canonical(header)
        body_bytes = dumps_canonical(body)
        malformed = b"".join(
            (
                MAGIC,
                encode_uvarint(2),
                _non_canonical_uvarint(len(header_bytes)),
                header_bytes,
                encode_uvarint(len(body_bytes)),
                body_bytes,
            )
        )

        with self.assertRaisesRegex(ValueError, "non-canonical varint"):
            ExtensionEnvelope.decode(malformed)

    def test_decode_rejects_non_canonical_body_len_uvarint(self) -> None:
        envelope = _make_test_envelope()
        header, body = envelope.to_cbor_sections()
        header_bytes = dumps_canonical(header)
        body_bytes = dumps_canonical(body)
        malformed = b"".join(
            (
                MAGIC,
                encode_uvarint(2),
                encode_uvarint(len(header_bytes)),
                header_bytes,
                _non_canonical_uvarint(len(body_bytes)),
                body_bytes,
            )
        )

        with self.assertRaisesRegex(ValueError, "non-canonical varint"):
            ExtensionEnvelope.decode(malformed)

    def test_decode_rejects_truncated_header_bytes(self) -> None:
        envelope = _make_test_envelope()
        header, _body = envelope.to_cbor_sections()
        header_bytes = dumps_canonical(header)
        malformed = b"".join(
            (
                MAGIC,
                encode_uvarint(2),
                encode_uvarint(len(header_bytes)),
                header_bytes[:-1],
            )
        )

        with self.assertRaisesRegex(ValueError, "truncated extension header"):
            ExtensionEnvelope.decode(malformed)

    def test_decode_rejects_truncated_body_bytes(self) -> None:
        envelope = _make_test_envelope()
        header, body = envelope.to_cbor_sections()
        header_bytes = dumps_canonical(header)
        body_bytes = dumps_canonical(body)
        malformed = b"".join(
            (
                MAGIC,
                encode_uvarint(2),
                encode_uvarint(len(header_bytes)),
                header_bytes,
                encode_uvarint(len(body_bytes)),
                body_bytes[:-1],
            )
        )

        with self.assertRaisesRegex(ValueError, "extension body length mismatch"):
            ExtensionEnvelope.decode(malformed)

    def test_decode_rejects_duplicate_chunk_ids_in_body(self) -> None:
        envelope = _make_test_envelope()
        header, body = envelope.to_cbor_sections()
        body[2] = [*body[2], body[2][0]]

        with self.assertRaisesRegex(ValueError, "duplicate extension chunk_id"):
            ExtensionEnvelope.decode(_encode_sections(header, body))

    def test_extension_codec_dispatch_helpers(self) -> None:
        chunk_bytes = b"dispatch"
        chunk_id = hashlib.sha256(chunk_bytes).digest()
        document = ExtensionEnvelope(
            header=build_extension_header(
                index=1,
                parent_doc_hash=TEST_DOC_HASH,
                root_doc_hash=TEST_ROOT_DOC_HASH,
                chunking=_make_profile(),
                input_origin="file",
                input_roots=(),
                created_at=123,
            ),
            files=(
                ExtensionFile(
                    path="payload.bin",
                    size=len(chunk_bytes),
                    sha256=chunk_id,
                    mtime=None,
                    chunk_refs=(ExtensionChunkRef(chunk_id=chunk_id, uncompressed_len=8),),
                ),
            ),
            chunks=(
                ExtensionChunkRecord(
                    chunk_id=chunk_id,
                    codec=CHUNK_CODEC_RAW,
                    raw_len=len(chunk_bytes),
                    data=chunk_bytes,
                ),
            ),
        )

        encoded = encode_extension_envelope(document)
        decoded = decode_extension_envelope(encoded)
        version, dispatched = decode_any_envelope(encoded)

        self.assertEqual(decoded.header.index, 1)
        self.assertEqual(version, 2)
        self.assertIsInstance(dispatched, ExtensionEnvelope)
