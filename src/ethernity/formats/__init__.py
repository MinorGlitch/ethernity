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

from ethernity.formats import extension_constants
from ethernity.formats.document_codec import (
    MAGIC as DOCUMENT_MAGIC,
    VERSION as BACKUP_DOCUMENT_VERSION,
    build_manifest_and_payload,
    build_single_file_manifest,
    decode_backup_document,
    decode_document,
    decode_extension_document,
    decode_manifest,
    encode_backup_document,
    encode_extension_document,
    encode_manifest,
    extract_payloads,
)
from ethernity.formats.extension_constants import (
    CHAIN_ID_PERSONALIZATION as CHAIN_ID_PERSONALIZATION,
    CHUNK_ALGORITHM_FASTCDC as CHUNK_ALGORITHM_FASTCDC,
    CHUNK_CODEC_GZIP as CHUNK_CODEC_GZIP,
    CHUNK_CODEC_RAW as CHUNK_CODEC_RAW,
    EXTENSION_DOCUMENT_VERSION as EXTENSION_DOCUMENT_VERSION,
)
from ethernity.formats.extension_document import (
    ExtensionChunkingProfile,
    ExtensionChunkRecord,
    ExtensionChunkRef,
    ExtensionDocument,
    ExtensionFile,
    ExtensionHeader,
    build_extension_header,
    derive_chain_id,
)
from ethernity.formats.manifest import BackupFile, BackupManifest, ManifestFile
from ethernity.formats.payload_codec import (
    decode_payload_from_manifest,
    encode_payload_for_manifest,
)

__all__ = [
    *(name for name in extension_constants.__all__ if name != "MIN_EXTENSION_CHUNK_SIZE"),
    "DOCUMENT_MAGIC",
    "BACKUP_DOCUMENT_VERSION",
    "BackupManifest",
    "ExtensionDocument",
    "ExtensionHeader",
    "ExtensionChunkingProfile",
    "ExtensionChunkRecord",
    "ExtensionChunkRef",
    "ExtensionFile",
    "ManifestFile",
    "BackupFile",
    "build_manifest_and_payload",
    "build_single_file_manifest",
    "build_extension_header",
    "decode_extension_document",
    "decode_document",
    "decode_backup_document",
    "decode_manifest",
    "decode_payload_from_manifest",
    "derive_chain_id",
    "encode_backup_document",
    "encode_extension_document",
    "encode_manifest",
    "encode_payload_for_manifest",
    "extract_payloads",
]
