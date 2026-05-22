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

from ethernity.formats.envelope_codec import (
    MAGIC as ENVELOPE_MAGIC,
    VERSION as ENVELOPE_VERSION,
    build_manifest_and_payload,
    build_single_file_manifest,
    decode_any_envelope,
    decode_envelope,
    decode_extension_envelope,
    decode_manifest,
    encode_envelope,
    encode_extension_envelope,
    encode_manifest,
    extract_payloads,
)
from ethernity.formats.envelope_types import EnvelopeManifest, ManifestFile, PayloadPart
from ethernity.formats.extension_envelope import (
    ExtensionChunkingProfile,
    ExtensionChunkRecord,
    ExtensionChunkRef,
    ExtensionEnvelope,
    ExtensionEnvelopeHeader,
    ExtensionFile,
    build_extension_header,
    derive_chain_id,
)
from ethernity.formats.extension_envelope_constants import (
    CHAIN_ID_PERSONALIZATION,
    CHUNK_ALGORITHM_FASTCDC,
    CHUNK_CODEC_GZIP,
    CHUNK_CODEC_RAW,
    EXTENSION_ENVELOPE_VERSION,
    EXTENSION_SCHEMA_VERSION,
)
from ethernity.formats.payload_codec import (
    decode_payload_from_manifest,
    encode_payload_for_manifest,
)

__all__ = [
    "ENVELOPE_MAGIC",
    "ENVELOPE_VERSION",
    "CHAIN_ID_PERSONALIZATION",
    "CHUNK_ALGORITHM_FASTCDC",
    "CHUNK_CODEC_GZIP",
    "CHUNK_CODEC_RAW",
    "EXTENSION_ENVELOPE_VERSION",
    "EXTENSION_SCHEMA_VERSION",
    "EnvelopeManifest",
    "ExtensionEnvelope",
    "ExtensionEnvelopeHeader",
    "ExtensionChunkingProfile",
    "ExtensionChunkRecord",
    "ExtensionChunkRef",
    "ExtensionFile",
    "ManifestFile",
    "PayloadPart",
    "build_manifest_and_payload",
    "build_single_file_manifest",
    "build_extension_header",
    "decode_extension_envelope",
    "decode_any_envelope",
    "decode_envelope",
    "decode_manifest",
    "decode_payload_from_manifest",
    "derive_chain_id",
    "encode_envelope",
    "encode_extension_envelope",
    "encode_manifest",
    "encode_payload_for_manifest",
    "extract_payloads",
]
