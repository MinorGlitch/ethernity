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

import {
  decodePayloadString,
  decodeZBase32,
  filterZBase32Lines,
  readUvarint,
  bytesEqual,
  bytesToHex,
  hexToBytes,
} from "../lib/encoding.js";
import { crc32 } from "../lib/crc32.js";
import { decodeCbor } from "../lib/cbor.js";
import { blake2b256 } from "../lib/blake2b.js";
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
} from "./constants.js";
import { bumpError } from "./state/initial.js";

export function listMissing(total, framesMap) {
  const missing = [];
  for (let i = 0; i < total; i += 1) {
    if (!framesMap.has(i)) missing.push(i);
  }
  return missing.slice(0, 30);
}

function decodeFrame(payload) {
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
  if (idx + dataLen + 4 !== payload.length) {
    throw new Error("frame length mismatch");
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

function decodeShardPayload(bytes) {
  const decoded = decodeCbor(bytes);
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
  if (!Number.isInteger(shareCount) || shareCount <= 0) {
    throw new Error("shard share_count must be a positive int");
  }
  if (!Number.isInteger(shareIndex) || shareIndex <= 0) {
    throw new Error("shard share_index must be a positive int");
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
  if (!(share instanceof Uint8Array) || !share.length) {
    throw new Error("shard share must be bytes");
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

function decodeAuthPayload(bytes) {
  const decoded = decodeCbor(bytes);
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

function addFrame(state, frame) {
  if (frame.frameType === FRAME_TYPE_AUTH) {
    addAuthFrame(state, frame);
    return;
  }
  if (frame.frameType !== FRAME_TYPE_MAIN) {
    state.ignored += 1;
    return;
  }
  const docIdHex = bytesToHex(frame.docId);
  if (!state.docIdHex) {
    state.docIdHex = docIdHex;
  } else if (state.docIdHex !== docIdHex) {
    state.ignored += 1;
    return;
  }
  if (state.total === null) {
    state.total = frame.total;
  } else if (state.total !== frame.total) {
    state.conflicts += 1;
    return;
  }
  if (state.mainFrames.has(frame.index)) {
    const existing = state.mainFrames.get(frame.index);
    if (!bytesEqual(existing.data, frame.data) || existing.total !== frame.total) {
      state.conflicts += 1;
    } else {
      state.duplicates += 1;
    }
    return;
  }
  state.mainFrames.set(frame.index, frame);
  state.ciphertext = null;
  state.cipherDocHashHex = null;
}

function addAuthFrame(state, frame) {
  if (frame.frameType !== FRAME_TYPE_AUTH) {
    state.authErrors += 1;
    return;
  }
  if (frame.total !== 1 || frame.index !== 0) {
    state.authErrors += 1;
    return;
  }
  const docIdHex = bytesToHex(frame.docId);
  if (state.authDocIdHex && state.authDocIdHex !== docIdHex) {
    state.authConflicts += 1;
    return;
  }
  if (state.docIdHex && state.docIdHex !== docIdHex) {
    state.authConflicts += 1;
    return;
  }
  let payload;
  try {
    payload = decodeAuthPayload(frame.data);
  } catch (err) {
    state.authErrors += 1;
    state.authStatus = "invalid payload";
    return;
  }
  if (state.authPayload) {
    if (!bytesEqual(state.authPayload.signature, payload.signature)) {
      state.authConflicts += 1;
      state.authStatus = "conflicting auth payloads";
      return;
    }
    state.authDuplicates += 1;
    return;
  }
  state.authPayload = payload;
  state.authDocIdHex = docIdHex;
  state.authDocHashHex = bytesToHex(payload.docHash);
  state.authSignPubHex = bytesToHex(payload.signPub);
  state.authSignatureHex = bytesToHex(payload.signature);
  state.authStatus = "pending";
}

function addShardFrame(state, frame) {
  if (frame.frameType !== FRAME_TYPE_KEY) {
    state.shardErrors += 1;
    return;
  }
  if (frame.total !== 1 || frame.index !== 0) {
    state.shardErrors += 1;
    return;
  }
  const docIdHex = bytesToHex(frame.docId);
  if (state.docIdHex && state.docIdHex !== docIdHex) {
    state.shardConflicts += 1;
    return;
  }
  if (!state.shardDocIdHex) {
    state.shardDocIdHex = docIdHex;
  } else if (state.shardDocIdHex !== docIdHex) {
    state.shardConflicts += 1;
    return;
  }
  let payload;
  try {
    payload = decodeShardPayload(frame.data);
  } catch (err) {
    state.shardErrors += 1;
    return;
  }
  if (state.shardThreshold === null) {
    state.shardThreshold = payload.threshold;
    state.shardShares = payload.shareCount;
    state.shardKeyType = payload.keyType;
    state.shardSecretLen = payload.secretLen;
    state.shardDocHashHex = bytesToHex(payload.docHash);
    state.shardSignPubHex = bytesToHex(payload.signPub);
  } else {
    if (state.shardThreshold !== payload.threshold || state.shardShares !== payload.shareCount) {
      state.shardConflicts += 1;
      return;
    }
    if (state.shardKeyType !== payload.keyType || state.shardSecretLen !== payload.secretLen) {
      state.shardConflicts += 1;
      return;
    }
    if (state.shardDocHashHex !== bytesToHex(payload.docHash)) {
      state.shardConflicts += 1;
      return;
    }
    if (state.shardSignPubHex !== bytesToHex(payload.signPub)) {
      state.shardConflicts += 1;
      return;
    }
  }

  const existing = state.shardFrames.get(payload.shareIndex);
  if (existing) {
    if (!bytesEqual(existing.share, payload.share)) {
      state.shardConflicts += 1;
    } else {
      state.shardDuplicates += 1;
    }
    return;
  }
  state.shardFrames.set(payload.shareIndex, payload);
}

function parsePayloadLinesWith(state, text, addFrameFn, errorKey) {
  const lines = text.split(/\r?\n/);
  let added = 0;
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const bytes = decodePayloadString(trimmed);
    if (!bytes) {
      bumpError(state, errorKey);
      continue;
    }
    try {
      const frame = decodeFrame(bytes);
      addFrameFn(state, frame);
      added += 1;
    } catch (err) {
      bumpError(state, errorKey);
    }
  }
  return added;
}

function parsePayloadLines(state, text) {
  return parsePayloadLinesWith(state, text, addFrame, "errors");
}

function nonEmptyLines(text) {
  return text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

function hasMarker(lines, markers) {
  for (const line of lines) {
    const lower = line.toLowerCase();
    if (markers.some((marker) => lower.includes(marker))) {
      return true;
    }
  }
  return false;
}

function allLinesDecodeFrames(lines) {
  if (!lines.length) return false;
  for (const line of lines) {
    const bytes = decodePayloadString(line);
    if (!bytes) return false;
    try {
      decodeFrame(bytes);
    } catch {
      return false;
    }
  }
  return true;
}

function allLinesDecodeShardFrames(lines) {
  if (!lines.length) return false;
  for (const line of lines) {
    const bytes = decodePayloadString(line);
    if (!bytes) return false;
    try {
      const frame = decodeFrame(bytes);
      if (frame.frameType !== FRAME_TYPE_KEY) {
        return false;
      }
    } catch {
      return false;
    }
  }
  return true;
}

function allLinesLookLikeFallback(lines) {
  if (!lines.length) return false;
  const filtered = filterZBase32Lines(lines.join("\n"));
  return filtered.length === lines.length;
}

export function parseAutoPayload(state, text) {
  const lines = nonEmptyLines(text);
  if (!lines.length) {
    throw new Error("no input lines found");
  }
  if (hasMarker(lines, ["main frame", "auth frame"])) {
    return parseFallbackText(state, text);
  }
  if (allLinesDecodeFrames(lines)) {
    return parsePayloadLines(state, text);
  }
  if (allLinesLookLikeFallback(lines)) {
    return parseFallbackText(state, text);
  }
  throw new Error("input is neither valid QR payloads nor valid fallback text");
}

function parseFallbackText(state, text) {
  const lines = text.split(/\r?\n/);
  const sections = { main: [], auth: [], any: [] };
  let current = null;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    const lower = line.toLowerCase();
    if (lower.includes("main frame")) {
      current = "main";
      continue;
    }
    if (lower.includes("auth frame")) {
      current = "auth";
      continue;
    }
    if (current) {
      sections[current].push(line);
    } else {
      sections.any.push(line);
    }
  }
  const target = sections.main.length ? sections.main : sections.any;
  const filtered = filterZBase32Lines(target.join("\n"));
  if (!filtered.length) {
    throw new Error("no fallback lines found");
  }
  const bytes = decodeZBase32(filtered.join(""));
  const frame = decodeFrame(bytes);
  addFrame(state, frame);

  let added = 1;
  if (sections.auth.length) {
    try {
      const authLines = filterZBase32Lines(sections.auth.join("\n"));
      if (authLines.length) {
        const authBytes = decodeZBase32(authLines.join(""));
        const authFrame = decodeFrame(authBytes);
        addFrame(state, authFrame);
        added += 1;
      }
    } catch (err) {
      state.authErrors += 1;
    }
  }
  return added;
}

function parseShardFallbackText(state, text) {
  const filtered = filterZBase32Lines(text);
  if (!filtered.length) {
    throw new Error("no shard fallback lines found");
  }
  const bytes = decodeZBase32(filtered.join(""));
  const frame = decodeFrame(bytes);
  addShardFrame(state, frame);
  return 1;
}

function parseShardPayloadLines(state, text) {
  return parsePayloadLinesWith(state, text, addShardFrame, "shardErrors");
}

export function parseAutoShard(state, text) {
  const lines = nonEmptyLines(text);
  if (!lines.length) {
    throw new Error("no input lines found");
  }
  if (hasMarker(lines, ["shard frame", "shard payload"])) {
    return parseShardFallbackText(state, text);
  }
  if (allLinesDecodeShardFrames(lines)) {
    return parseShardPayloadLines(state, text);
  }
  if (allLinesLookLikeFallback(lines)) {
    return parseShardFallbackText(state, text);
  }
  throw new Error("input is neither valid shard payloads nor valid fallback text");
}

export function reassembleCiphertext(state) {
  if (state.total === null || state.mainFrames.size !== state.total) {
    throw new Error("missing frames");
  }
  const chunks = [];
  for (let i = 0; i < state.total; i += 1) {
    const frame = state.mainFrames.get(i);
    if (!frame) throw new Error(`missing frame ${i}`);
    chunks.push(frame.data);
  }
  const totalLen = chunks.reduce((sum, arr) => sum + arr.length, 0);
  const out = new Uint8Array(totalLen);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

export function ensureCiphertextAndHash(state) {
  if (!state.total || state.mainFrames.size !== state.total) {
    return null;
  }
  if (!state.ciphertext) {
    state.ciphertext = reassembleCiphertext(state);
  }
  if (!state.cipherDocHashHex) {
    const hash = blake2b256(state.ciphertext);
    state.cipherDocHashHex = bytesToHex(hash);
    return hash;
  }
  return hexToBytes(state.cipherDocHashHex);
}

export function syncCollectedCiphertext(state) {
  if (state.total && state.mainFrames.size === state.total) {
    try {
      state.ciphertext = reassembleCiphertext(state);
    } catch (err) {
      // leave ciphertext unset if reassembly fails
    }
  }
}
