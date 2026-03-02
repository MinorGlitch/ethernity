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

import { readUvarint } from "../lib/encoding.js";
import { crc32 } from "../lib/crc32.js";
import { decodeCanonicalCbor } from "../lib/cbor.js";
import {
  FRAME_MAGIC,
  FRAME_VERSION,
  FRAME_TYPE_MAIN,
  FRAME_TYPE_AUTH,
  FRAME_TYPE_KEY,
  DOC_ID_LEN,
  AUTH_VERSION,
  SHARD_VERSION,
  SHARD_KEY_PASSPHRASE,
  SHARD_KEY_SIGNING_SEED,
  SIGNING_SEED_LEN,
  MAX_SHARD_SHARES,
  MAX_AUTH_CBOR_BYTES,
  MAX_MAIN_FRAME_DATA_BYTES,
  MAX_MAIN_FRAME_TOTAL,
  MAX_SHARD_CBOR_BYTES,
} from "./constants.js";

export function decodeFrame(payload) {
  if (payload.length < FRAME_MAGIC.length + 4) {
    throw new Error("frame too short");
  }
  if (payload[0] !== FRAME_MAGIC[0] || payload[1] !== FRAME_MAGIC[1]) {
    throw new Error("bad magic");
  }
  let idx = 2;
  const versionRes = readUvarint(payload, idx);
  const version = versionRes.value;
  idx = versionRes.offset;
  if (version !== FRAME_VERSION) {
    throw new Error(`unsupported frame version: ${version}`);
  }
  if (idx >= payload.length) throw new Error("missing frame type");
  const frameType = payload[idx++];
  if (
    frameType !== FRAME_TYPE_MAIN &&
    frameType !== FRAME_TYPE_AUTH &&
    frameType !== FRAME_TYPE_KEY
  ) {
    throw new Error(`unsupported frame type: ${frameType}`);
  }
  const docId = payload.slice(idx, idx + DOC_ID_LEN);
  if (docId.length !== DOC_ID_LEN) throw new Error("missing doc_id");
  idx += DOC_ID_LEN;
  const indexRes = readUvarint(payload, idx);
  const index = indexRes.value;
  idx = indexRes.offset;
  const totalRes = readUvarint(payload, idx);
  const total = totalRes.value;
  idx = totalRes.offset;
  if (!Number.isInteger(index) || index < 0) {
    throw new Error("index must be non-negative");
  }
  if (!Number.isInteger(total) || total <= 0) {
    throw new Error("total must be positive");
  }
  if (index >= total) {
    throw new Error("index must be < total");
  }
  const lenRes = readUvarint(payload, idx);
  const dataLen = lenRes.value;
  idx = lenRes.offset;
  if (!Number.isInteger(dataLen) || dataLen < 0) {
    throw new Error("data length must be non-negative");
  }
  if (idx + dataLen + 4 !== payload.length) {
    throw new Error("frame length mismatch");
  }
  if (frameType === FRAME_TYPE_MAIN) {
    if (total > MAX_MAIN_FRAME_TOTAL) {
      throw new Error(
        `MAIN_DOCUMENT total exceeds MAX_MAIN_FRAME_TOTAL (${MAX_MAIN_FRAME_TOTAL}): ${total}`
      );
    }
    if (dataLen > MAX_MAIN_FRAME_DATA_BYTES) {
      throw new Error(
        "MAIN_DOCUMENT data exceeds " +
          `MAX_MAIN_FRAME_DATA_BYTES (${MAX_MAIN_FRAME_DATA_BYTES}): ${dataLen} bytes`
      );
    }
  } else if (frameType === FRAME_TYPE_AUTH) {
    if (total !== 1 || index !== 0) {
      throw new Error("AUTH payload must be a single-frame payload (index=0,total=1)");
    }
    if (dataLen > MAX_AUTH_CBOR_BYTES) {
      throw new Error(
        `AUTH data exceeds MAX_AUTH_CBOR_BYTES (${MAX_AUTH_CBOR_BYTES}): ${dataLen} bytes`
      );
    }
  } else if (frameType === FRAME_TYPE_KEY) {
    if (total !== 1 || index !== 0) {
      throw new Error("KEY_DOCUMENT payload must be a single-frame payload (index=0,total=1)");
    }
    if (dataLen > MAX_SHARD_CBOR_BYTES) {
      throw new Error(
        `KEY_DOCUMENT data exceeds MAX_SHARD_CBOR_BYTES (${MAX_SHARD_CBOR_BYTES}): ${dataLen} bytes`
      );
    }
  }
  const data = payload.slice(idx, idx + dataLen);
  idx += dataLen;
  const crcExpected = (
    (payload[idx] << 24) |
    (payload[idx + 1] << 16) |
    (payload[idx + 2] << 8) |
    payload[idx + 3]
  ) >>> 0;
  const crcActual = crc32(payload.slice(0, idx));
  if (crcExpected !== crcActual) {
    throw new Error("crc mismatch");
  }
  return { version, frameType, docId, index, total, data, raw: payload };
}

export function decodeShardPayload(bytes) {
  const decoded = decodeCanonicalCbor(bytes, "shard payload");
  if (decoded === null || typeof decoded !== "object" || Array.isArray(decoded)) {
    throw new Error("shard payload must be a map");
  }
  for (const key of [
    "version",
    "type",
    "threshold",
    "share_count",
    "share_index",
    "length",
    "share",
    "hash",
    "pub",
    "sig",
  ]) {
    if (!(key in decoded)) {
      throw new Error(`shard payload ${key} is required`);
    }
  }
  const version = decoded.version;
  const keyType = decoded.type;
  const threshold = decoded.threshold;
  const shareCount = decoded.share_count;
  const shareIndex = decoded.share_index;
  const secretLen = decoded.length;
  const share = decoded.share;
  const docHash = decoded.hash;
  const signPub = decoded.pub;
  const signature = decoded.sig;

  if (version !== SHARD_VERSION) {
    throw new Error(`unsupported shard payload version: ${version}`);
  }
  if (keyType !== SHARD_KEY_PASSPHRASE && keyType !== SHARD_KEY_SIGNING_SEED) {
    throw new Error(`unsupported shard key type: ${keyType}`);
  }
  if (!Number.isInteger(threshold) || threshold <= 0) {
    throw new Error("shard threshold must be a positive int");
  }
  if (threshold > MAX_SHARD_SHARES) {
    throw new Error(`shard threshold must be <= ${MAX_SHARD_SHARES}`);
  }
  if (!Number.isInteger(shareCount) || shareCount <= 0) {
    throw new Error("shard share_count must be a positive int");
  }
  if (shareCount > MAX_SHARD_SHARES) {
    throw new Error(`shard share_count must be <= ${MAX_SHARD_SHARES}`);
  }
  if (!Number.isInteger(shareIndex) || shareIndex <= 0) {
    throw new Error("shard share_index must be a positive int");
  }
  if (shareIndex > MAX_SHARD_SHARES) {
    throw new Error(`shard share_index must be <= ${MAX_SHARD_SHARES}`);
  }
  if (threshold > shareCount) {
    throw new Error("shard threshold cannot exceed share_count");
  }
  if (shareIndex > shareCount) {
    throw new Error("shard share_index cannot exceed share_count");
  }
  if (!Number.isInteger(secretLen) || secretLen <= 0) {
    throw new Error("shard secret length must be a positive int");
  }
  if (keyType === SHARD_KEY_SIGNING_SEED && secretLen !== SIGNING_SEED_LEN) {
    throw new Error(`signing-seed shard length must be ${SIGNING_SEED_LEN}`);
  }
  if (!(share instanceof Uint8Array) || !share.length) {
    throw new Error("shard share must be bytes");
  }
  if (share.length % 16 !== 0) {
    throw new Error("shard share length must be a multiple of block size");
  }
  if (secretLen > share.length) {
    throw new Error("shard secret length must be <= shard share length");
  }
  const blockCount = Math.ceil(secretLen / 16);
  const expectedShareLen = blockCount * 16;
  if (share.length !== expectedShareLen) {
    throw new Error("shard share length does not match secret length");
  }
  if (!(docHash instanceof Uint8Array) || docHash.length !== 32) {
    throw new Error("shard doc_hash must be 32 bytes");
  }
  if (!(signPub instanceof Uint8Array) || signPub.length !== 32) {
    throw new Error("shard sign_pub must be 32 bytes");
  }
  if (!(signature instanceof Uint8Array) || signature.length !== 64) {
    throw new Error("shard signature must be 64 bytes");
  }
  return {
    version,
    keyType,
    threshold,
    shareCount,
    shareIndex,
    secretLen,
    share,
    docHash,
    signPub,
    signature,
  };
}

export function decodeAuthPayload(bytes) {
  const decoded = decodeCanonicalCbor(bytes, "auth payload");
  if (decoded === null || typeof decoded !== "object" || Array.isArray(decoded)) {
    throw new Error("auth payload must be a map");
  }
  for (const key of ["version", "hash", "pub", "sig"]) {
    if (!(key in decoded)) {
      throw new Error(`auth payload ${key} is required`);
    }
  }
  const version = decoded.version;
  const docHash = decoded.hash;
  const signPub = decoded.pub;
  const signature = decoded.sig;
  if (version !== AUTH_VERSION) {
    throw new Error(`unsupported auth version: ${version}`);
  }
  if (!(docHash instanceof Uint8Array) || docHash.length !== 32) {
    throw new Error("auth doc_hash must be 32 bytes");
  }
  if (!(signPub instanceof Uint8Array) || signPub.length !== 32) {
    throw new Error("auth sign_pub must be 32 bytes");
  }
  if (!(signature instanceof Uint8Array) || signature.length !== 64) {
    throw new Error("auth signature must be 64 bytes");
  }
  return { version, docHash, signPub, signature };
}
