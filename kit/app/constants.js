/*
 * Copyright (C) 2026 Alex Stoyanov
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along with this program.
 * If not, see <https://www.gnu.org/licenses/>.
 */

export const FRAME_MAGIC = [0x41, 0x50]; // "AP"
export const ENVELOPE_MAGIC = [0x41, 0x59]; // "AY"
export const FRAME_VERSION = 1;
export const ENVELOPE_VERSION = 1;
export const FRAME_TYPE_MAIN = 0x44; // "D"
export const FRAME_TYPE_KEY = 0x4b; // "K"
export const FRAME_TYPE_AUTH = 0x41; // "A"
export const DOC_ID_LEN = 8;
export const MANIFEST_VERSION = 1;
export const SHARD_VERSION = 1;
export const SHARD_KEY_PASSPHRASE = "passphrase";
export const SHARD_KEY_SIGNING_SEED = "signing-seed";
export const SIGNING_SEED_LEN = 32;
export const MAX_SHARD_SHARES = 255;
export const AUTH_VERSION = 1;
export const AUTH_DOMAIN = "ETHERNITY-AUTH-V1";
export const SHARD_DOMAIN = "ETHERNITY-SHARD-V1";
export const PATH_ENCODING_DIRECT = "direct";
export const PATH_ENCODING_PREFIX_TABLE = "prefix_table";
export const MAX_CIPHERTEXT_BYTES = 1_048_576;
export const MAX_MAIN_FRAME_DATA_BYTES = 1_048_576;
export const MAX_MAIN_FRAME_TOTAL = 4_096;
export const MAX_QR_PAYLOAD_CHARS = 3_072;
export const MAX_AUTH_CBOR_BYTES = 512;
export const MAX_SHARD_CBOR_BYTES = 2_048;
export const MAX_MANIFEST_CBOR_BYTES = 1_048_576;
export const MAX_MANIFEST_FILES = 2_048;
export const MAX_PATH_BYTES = 512;
export const MAX_FALLBACK_NORMALIZED_CHARS = 2_000_000;
export const MAX_FALLBACK_LINES = 50_000;
export const MAX_RECOVERY_TEXT_BYTES = 10_485_760;
export const MAX_DECOMPRESSED_PAYLOAD_BYTES = 67_108_864;
export const textEncoder = new TextEncoder();
export const textDecoder = new TextDecoder();
