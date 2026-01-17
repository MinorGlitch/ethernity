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

from .envelope_codec import (
    MAGIC as ENVELOPE_MAGIC,
    VERSION as ENVELOPE_VERSION,
    build_manifest_and_payload,
    build_single_file_manifest,
    decode_envelope,
    decode_manifest,
    encode_envelope,
    encode_manifest,
    extract_payloads,
)
from .envelope_types import EnvelopeManifest, ManifestFile, PayloadPart

__all__ = [
    "ENVELOPE_MAGIC",
    "ENVELOPE_VERSION",
    "EnvelopeManifest",
    "ManifestFile",
    "PayloadPart",
    "build_manifest_and_payload",
    "build_single_file_manifest",
    "decode_envelope",
    "decode_manifest",
    "encode_envelope",
    "encode_manifest",
    "extract_payloads",
]
