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

import { readDocumentHeader } from "../document_header.js";
import { sha256 } from "@noble/hashes/sha2.js";

import { decodeDeterministicCbor } from "../../lib/cbor.js";
import { bytesEqual, bytesToHex, concatByteParts } from "../../lib/bytes.js";
import { readUvarint } from "../../lib/encoding.js";
import { gunzipBytesBounded } from "../../lib/gzip.js";
import {
  CHUNK_ALGORITHM_FASTCDC,
  CHUNK_CODEC_GZIP,
  CHUNK_CODEC_RAW,
  DOCUMENT_KIND_UPDATE,
  MAX_DECOMPRESSED_PAYLOAD_BYTES,
  MAX_EXTENSION_INDEX,
  MAX_MANIFEST_CBOR_BYTES,
  MAX_MANIFEST_FILES,
  MAX_RECOVERY_DECODED_CHUNK_BYTES,
  MIN_EXTENSION_CHUNK_SIZE,
} from "../constants.js";
import { validateManifestFileTree, validateManifestPath } from "../../lib/path_validation.js";
import { chunkRefsForBytes, defaultExtensionChunker } from "./chunking.js";

const HEADER_KEYS = new Set([2, 4, 5, 7, 10, 13]);
const BODY_KEYS = new Set([1, 2]);

export function decodeExtensionDocumentHeader(bytes) {
  return readExtensionDocumentHeader(bytes).header;
}

export async function decodeExtensionDocument(bytes, { decodeChunks = true } = {}) {
  const { header, bodyStart, bodyEnd } = readExtensionDocumentHeader(bytes);
  const body = await parseExtensionBody(
    decodeDeterministicCbor(bytes.slice(bodyStart, bodyEnd), "extension body", {
      preserveFloatType: true,
      preserveMapType: true,
    }),
    header,
    { decodeChunks },
  );
  return { header, files: body.files, chunks: body.chunks };
}

function readExtensionDocumentHeader(bytes) {
  const { kind, bodyOffset } = readDocumentHeader(bytes);
  if (kind !== DOCUMENT_KIND_UPDATE) throw new Error("expected update document kind");
  let idx = bodyOffset;

  const headerLenRes = readUvarint(bytes, idx);
  idx = headerLenRes.offset;
  const headerLen = headerLenRes.value;
  if (headerLen > MAX_MANIFEST_CBOR_BYTES) {
    throw new Error(
      `extension header exceeds MAX_MANIFEST_CBOR_BYTES (${MAX_MANIFEST_CBOR_BYTES})`,
    );
  }
  const headerEnd = idx + headerLen;
  if (headerEnd > bytes.length) {
    throw new Error("truncated extension header");
  }
  const header = parseExtensionHeader(
    decodeDeterministicCbor(bytes.slice(idx, headerEnd), "extension header", {
      preserveFloatType: true,
      preserveMapType: true,
    }),
  );
  idx = headerEnd;

  const bodyLenRes = readUvarint(bytes, idx);
  idx = bodyLenRes.offset;
  const bodyLen = bodyLenRes.value;
  if (bodyLen > MAX_MANIFEST_CBOR_BYTES) {
    throw new Error(`extension body exceeds MAX_MANIFEST_CBOR_BYTES (${MAX_MANIFEST_CBOR_BYTES})`);
  }
  const bodyEnd = idx + bodyLen;
  if (bodyEnd !== bytes.length) {
    throw new Error("extension body length mismatch");
  }
  return { header, bodyStart: idx, bodyEnd };
}

function parseExtensionHeader(value) {
  const header = requireIntKeyMap(value, HEADER_KEYS, "extension header");
  for (const key of HEADER_KEYS) {
    if (!header.has(key)) {
      throw new Error(`extension header key ${key} is required`);
    }
  }
  const updateMode = header.get(13);
  if (!["cumulative", "incremental"].includes(updateMode)) {
    throw new Error("unsupported extension update mode");
  }
  const index = requirePositiveInt(header.get(2), "extension header index");
  if (index > MAX_EXTENSION_INDEX) {
    throw new Error(`extension header index exceeds MAX_EXTENSION_INDEX (${MAX_EXTENSION_INDEX})`);
  }
  const parentDocHash = requireBytes(header.get(4), 32, "extension header parent_doc_hash");
  const rootDocHash = requireBytes(header.get(5), 32, "extension header root_doc_hash");
  const createdAt = requireInt(header.get(7), "extension header created_at");
  const chunking = parseChunking(header.get(10));
  return {
    updateMode,
    index,
    parentDocHash,
    rootDocHash,
    createdAt,
    chunking,
  };
}

function parseChunking(value) {
  const fields = requireArray(value, "extension chunking");
  if (fields.length !== 4) {
    throw new Error("extension chunking must contain exactly 4 items");
  }
  const profile = {
    algorithmId: requireInt(fields[0], "extension chunking algorithm_id"),
    targetSize: requirePositiveInt(fields[1], "extension chunking target_size"),
    minSize: requirePositiveInt(fields[2], "extension chunking min_size"),
    maxSize: requirePositiveInt(fields[3], "extension chunking max_size"),
  };
  if (profile.algorithmId !== CHUNK_ALGORITHM_FASTCDC) {
    throw new Error("extension chunking algorithm_id must be CHUNK_ALGORITHM_FASTCDC (1)");
  }
  for (const [label, size] of [
    ["target_size", profile.targetSize],
    ["min_size", profile.minSize],
    ["max_size", profile.maxSize],
  ]) {
    if (size < MIN_EXTENSION_CHUNK_SIZE) {
      throw new Error(`extension chunking ${label} must be >= ${MIN_EXTENSION_CHUNK_SIZE}`);
    }
    if (size > MAX_DECOMPRESSED_PAYLOAD_BYTES) {
      throw new Error(`extension chunking ${label} must be <= MAX_DECOMPRESSED_PAYLOAD_BYTES`);
    }
  }
  if (!(profile.minSize <= profile.targetSize && profile.targetSize <= profile.maxSize)) {
    throw new Error("extension chunking sizes must satisfy min_size <= target_size <= max_size");
  }
  return profile;
}

async function parseExtensionBody(value, header, { decodeChunks }) {
  const body = requireIntKeyMap(value, BODY_KEYS, "extension body");
  if (!body.has(1) || !body.has(2)) {
    throw new Error("extension body files and chunks are required");
  }
  const files = requireArray(body.get(1), "extension body files").map(parseExtensionFile);
  if (!files.length && header.updateMode !== "cumulative") {
    throw new Error("extension body files are required");
  }
  if (files.length > MAX_MANIFEST_FILES) {
    throw new Error(`extension files exceed MAX_MANIFEST_FILES (${MAX_MANIFEST_FILES})`);
  }
  validateSortedUnique(
    files,
    "path",
    "extension files must be ordered by normalized path",
    compareUnicodeCodePointStrings,
  );
  validateManifestFileTree(
    files.map((file) => file.path),
    "extension file paths",
  );
  const chunks = requireArray(body.get(2), "extension body chunks").map(parseExtensionChunk);
  validateSortedUnique(chunks, "chunkIdHex", "extension chunks must be ordered by raw chunk_id");
  const referenced = new Set();
  for (const file of files) {
    for (const chunkRef of file.chunkRefs) {
      referenced.add(chunkRef.chunkIdHex);
    }
  }
  let totalInlineBytes = 0;
  for (const chunk of chunks) {
    totalInlineBytes += chunk.rawLen;
    if (totalInlineBytes > MAX_DECOMPRESSED_PAYLOAD_BYTES) {
      throw new Error("extension inline chunk bytes exceed MAX_DECOMPRESSED_PAYLOAD_BYTES");
    }
    if (!referenced.has(chunk.chunkIdHex)) {
      throw new Error("extension inline chunks must be referenced by files in the same document");
    }
  }
  if (decodeChunks) {
    for (const chunk of chunks) {
      chunk.decoded = await decodeChunkData(chunk);
    }
  }
  return { files, chunks };
}

function parseExtensionFile(value) {
  const fields = requireArray(value, "extension file");
  if (fields.length !== 5) {
    throw new Error("extension file must contain exactly 5 items");
  }
  const path = validateManifestPath(requireString(fields[0], "extension file path"));
  const size = requireNonNegativeInt(fields[1], "extension file size");
  if (size > MAX_DECOMPRESSED_PAYLOAD_BYTES) {
    throw new Error("extension file size exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES");
  }
  const sha = requireBytes(fields[2], 32, "extension file sha256");
  const mtime = fields[3] === null ? null : requireInt(fields[3], "extension file mtime");
  const chunkRefs = requireArray(fields[4], "extension file chunk_refs").map(parseChunkRef);
  if (size === 0 && chunkRefs.length) {
    throw new Error("zero-length extension files must have empty chunk_refs");
  }
  if (size > 0 && !chunkRefs.length) {
    throw new Error("non-empty extension files must include chunk_refs");
  }
  const refSize = chunkRefs.reduce((sum, ref) => sum + ref.uncompressedLen, 0);
  if (refSize !== size) {
    throw new Error("extension file chunk_refs must sum to file size");
  }
  return { path, size, sha, mtime, chunkRefs };
}

function parseChunkRef(value) {
  const fields = requireArray(value, "extension chunk_ref");
  if (fields.length !== 2) {
    throw new Error("extension chunk_ref must contain exactly 2 items");
  }
  const chunkId = requireBytes(fields[0], 32, "extension chunk_ref chunk_id");
  const uncompressedLen = requirePositiveInt(fields[1], "extension chunk_ref uncompressed_len");
  if (uncompressedLen > MAX_DECOMPRESSED_PAYLOAD_BYTES) {
    throw new Error("extension chunk_ref uncompressed_len exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES");
  }
  return {
    chunkId,
    chunkIdHex: bytesToHex(chunkId),
    uncompressedLen,
  };
}

function parseExtensionChunk(value) {
  const fields = requireArray(value, "extension chunk");
  if (fields.length !== 4) {
    throw new Error("extension chunk must contain exactly 4 items");
  }
  const chunkId = requireBytes(fields[0], 32, "extension chunk chunk_id");
  const codec = requireInt(fields[1], "extension chunk codec");
  if (codec !== CHUNK_CODEC_RAW && codec !== CHUNK_CODEC_GZIP) {
    throw new Error("extension chunk codec must be one of: 0, 1");
  }
  const rawLen = requirePositiveInt(fields[2], "extension chunk raw_len");
  if (rawLen > MAX_DECOMPRESSED_PAYLOAD_BYTES) {
    throw new Error("extension chunk raw_len exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES");
  }
  const data = requireNonEmptyBytes(fields[3], "extension chunk data");
  return {
    chunkId,
    chunkIdHex: bytesToHex(chunkId),
    codec,
    rawLen,
    data,
    decoded: null,
  };
}

export async function reconstructLatestFilesFromDocuments(
  rootFiles,
  rootDocHash,
  extensionDocuments,
  { decodeDocument = decodeExtensionDocument, onExtensionReplayed = null } = {},
) {
  validateManifestFileTree(rootFiles.map((file) => file.path));
  if (!extensionDocuments.length) {
    return rootFiles.map((file) => ({ ...file, data: file.data.slice() }));
  }
  validateExtensionChain(rootDocHash, extensionDocuments);
  const neededRefs = new Map();
  let decodedChunkBytes = 0;
  for (const item of extensionDocuments) {
    const metadata = await decodeDocument(item.plaintext, { decodeChunks: false });
    requireMatchingDocumentHeader(metadata.header, item.header);
    addExtensionChunkRefCounts(neededRefs, metadata);
    decodedChunkBytes = addDecodedChunkBytes(decodedChunkBytes, metadata);
  }

  const replay = createExtensionReplay(
    rootFiles,
    extensionDocuments[0].header.chunking,
    neededRefs,
  );
  for (const item of extensionDocuments) {
    const extension = await decodeDocument(item.plaintext);
    requireMatchingDocumentHeader(extension.header, item.header);
    replayExtension(replay, extension);
    onExtensionReplayed?.({
      index: item.header.index,
      retainedChunkBytes: availableChunkBytes(replay.availableChunks),
    });
  }
  return replayFiles(replay);
}

function createExtensionReplay(rootFiles, lockedChunking, neededRefs) {
  const state = new Map(rootFiles.map((file) => [file.path, { ...file, data: file.data.slice() }]));
  const seenChunkIds = new Set();
  const availableChunks = virtualRootChunkMap(rootFiles, lockedChunking, neededRefs, seenChunkIds);
  return { rootFiles, state, lockedChunking, neededRefs, seenChunkIds, availableChunks };
}

function replayExtension(replay, extension) {
  if (extension.header.updateMode === "cumulative") {
    Object.assign(
      replay,
      createExtensionReplay(replay.rootFiles, replay.lockedChunking, replay.neededRefs),
    );
  }
  const { state, lockedChunking, neededRefs, seenChunkIds, availableChunks } = replay;
  mergeNewExtensionChunks(availableChunks, extension, neededRefs, seenChunkIds);
  const projected = new Map(state);
  for (const file of extension.files) {
    projected.set(file.path, file);
  }
  validateManifestFileTree(projected.keys(), "logical latest file paths");
  if (projected.size > MAX_MANIFEST_FILES) {
    throw new Error(`logical latest state exceeds MAX_MANIFEST_FILES (${MAX_MANIFEST_FILES})`);
  }
  const logicalBytes = Array.from(projected.values()).reduce(
    (sum, file) => sum + logicalFileSize(file),
    0,
  );
  if (logicalBytes > MAX_DECOMPRESSED_PAYLOAD_BYTES) {
    throw new Error("logical latest state exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES");
  }
  for (const file of extension.files) {
    state.set(file.path, resolveExtensionFileState(file, availableChunks, lockedChunking));
  }
  consumeExtensionChunkRefs(neededRefs, availableChunks, extension);
}

function replayFiles(replay) {
  return Array.from(replay.state.keys())
    .sort(compareUnicodeCodePointStrings)
    .map((path) => replay.state.get(path));
}

function requireMatchingDocumentHeader(actual, expected) {
  if (
    actual.updateMode !== expected.updateMode ||
    actual.index !== expected.index ||
    !bytesEqual(actual.parentDocHash, expected.parentDocHash) ||
    !bytesEqual(actual.rootDocHash, expected.rootDocHash) ||
    actual.createdAt !== expected.createdAt ||
    !chunkingEqual(actual.chunking, expected.chunking)
  ) {
    throw new Error("decoded extension header changed after authenticated selection");
  }
}

function inlineChunkRawBytes(extension) {
  return extension.chunks.reduce((total, chunk) => total + chunk.rawLen, 0);
}

function addDecodedChunkBytes(currentBytes, extension) {
  const decodedChunkBytes = currentBytes + inlineChunkRawBytes(extension);
  if (decodedChunkBytes > MAX_RECOVERY_DECODED_CHUNK_BYTES) {
    throw new Error(
      `extension chain inline chunk bytes exceed MAX_RECOVERY_DECODED_CHUNK_BYTES (${MAX_RECOVERY_DECODED_CHUNK_BYTES}); rebuild the latest logical state as a fresh standalone backup before adding more files`,
    );
  }
  return decodedChunkBytes;
}

function availableChunkBytes(chunks) {
  let total = 0;
  for (const chunk of chunks.values()) {
    total += chunk.length;
  }
  return total;
}

function logicalFileSize(file) {
  if (Number.isInteger(file.size) && file.size >= 0) {
    return file.size;
  }
  if (file.data instanceof Uint8Array) {
    return file.data.length;
  }
  throw new Error("logical file size is unavailable");
}

export function validateExtensionChain(rootDocHash, extensions) {
  let expectedParentDocHash = rootDocHash;
  let expectedIndex = 1;
  let lockedChunking = null;
  const lockedMode = extensions[0]?.header.updateMode;
  let previousIndex = 0;
  for (const extension of extensions) {
    const header = extension.header;
    if (header.updateMode !== lockedMode) {
      throw new Error("update mode must match the locked series mode");
    }
    const cumulative = header.updateMode === "cumulative";
    if (header.index <= previousIndex || (!cumulative && header.index !== expectedIndex)) {
      throw new Error(`extension index sequence is invalid: expected ${expectedIndex}`);
    }
    if (!bytesEqual(header.rootDocHash, rootDocHash)) {
      throw new Error("extension root_doc_hash does not match root backup");
    }
    if (!bytesEqual(header.parentDocHash, cumulative ? rootDocHash : expectedParentDocHash)) {
      throw new Error("extension parent_doc_hash does not match previous document");
    }
    if (!lockedChunking) {
      lockedChunking = header.chunking;
    } else if (!chunkingEqual(lockedChunking, header.chunking)) {
      throw new Error("extension chunking profile must match the locked chain profile");
    }
    expectedParentDocHash = extension.docHash;
    expectedIndex += 1;
    previousIndex = header.index;
  }
}

function resolveExtensionFileState(file, availableChunks, chunking) {
  const chunks = [];
  let size = 0;
  for (const ref of file.chunkRefs) {
    const chunk = availableChunks.get(ref.chunkIdHex);
    if (!chunk) {
      throw new Error(`extension file references unresolved chunk_id: ${file.path}`);
    }
    if (chunk.length !== ref.uncompressedLen) {
      throw new Error("extension chunk_ref length does not match resolved chunk");
    }
    chunks.push(chunk);
    size += chunk.length;
  }
  if (size !== file.size) {
    throw new Error("extension reconstructed file size mismatch");
  }
  // Resolve and validate each file once, with both root and update chunks available.
  const data = concatByteParts(chunks);
  if (!bytesEqual(sha256(data), file.sha)) {
    throw new Error(`extension file sha256 mismatch for ${file.path}`);
  }
  requireMatchingChunkRefs(file, data, chunking);
  return { path: file.path, size: file.size, sha: file.sha, mtime: file.mtime, data };
}

function requireMatchingChunkRefs(file, data, chunking) {
  const expected = chunkRefsForBytes(data, chunking);
  if (expected.length !== file.chunkRefs.length) {
    throw new Error("extension file chunk_refs do not match locked chunking profile");
  }
  for (let idx = 0; idx < expected.length; idx += 1) {
    const ref = file.chunkRefs[idx];
    const [chunkId, length] = expected[idx];
    if (!bytesEqual(ref.chunkId, chunkId) || ref.uncompressedLen !== length) {
      throw new Error("extension file chunk_refs do not match locked chunking profile");
    }
  }
}

function virtualRootChunkMap(rootFiles, chunking, neededRefs, seenChunkIds) {
  const chunks = new Map();
  for (const file of rootFiles) {
    for (const chunk of defaultExtensionChunker(file.data, chunking)) {
      const chunkId = sha256(chunk);
      const chunkIdHex = bytesToHex(chunkId);
      seenChunkIds.add(chunkIdHex);
      if (neededRefs && (neededRefs.get(chunkIdHex) ?? 0) <= 0) {
        continue;
      }
      const existing = chunks.get(chunkIdHex);
      if (existing && !bytesEqual(existing, chunk)) {
        throw new Error("virtual root chunk payload collision for identical chunk_id");
      }
      chunks.set(chunkIdHex, chunk);
    }
  }
  return chunks;
}

function mergeNewExtensionChunks(target, extension, neededRefs, seenChunkIds) {
  for (const chunk of extension.chunks) {
    if (seenChunkIds.has(chunk.chunkIdHex)) {
      throw new Error("extension chunks must be newly introduced");
    }
    seenChunkIds.add(chunk.chunkIdHex);
    if (neededRefs && (neededRefs.get(chunk.chunkIdHex) ?? 0) <= 0) {
      continue;
    }
    if (target.has(chunk.chunkIdHex)) {
      throw new Error("extension chunks must be newly introduced");
    }
    target.set(chunk.chunkIdHex, chunk.decoded);
  }
}

function addExtensionChunkRefCounts(counts, extension) {
  for (const file of extension.files) {
    for (const ref of file.chunkRefs) {
      counts.set(ref.chunkIdHex, (counts.get(ref.chunkIdHex) ?? 0) + 1);
    }
  }
}

function consumeExtensionChunkRefs(refCounts, availableChunks, extension) {
  for (const file of extension.files) {
    for (const ref of file.chunkRefs) {
      const remaining = (refCounts.get(ref.chunkIdHex) ?? 0) - 1;
      if (remaining <= 0) {
        refCounts.delete(ref.chunkIdHex);
        availableChunks.delete(ref.chunkIdHex);
      } else {
        refCounts.set(ref.chunkIdHex, remaining);
      }
    }
  }
}

async function decodeChunkData(chunk) {
  if (chunk.codec === CHUNK_CODEC_RAW) {
    if (chunk.data.length !== chunk.rawLen) {
      throw new Error("raw extension chunk data length must equal raw_len");
    }
    if (!bytesEqual(sha256(chunk.data), chunk.chunkId)) {
      throw new Error("extension chunk bytes do not hash to chunk_id");
    }
    return chunk.data;
  }
  const decoded = await gunzipBytesBounded(chunk.data, chunk.rawLen);
  if (!bytesEqual(sha256(decoded), chunk.chunkId)) {
    throw new Error("extension chunk bytes do not hash to chunk_id");
  }
  return decoded;
}

function requireIntKeyMap(value, allowedKeys, label) {
  if (!(value instanceof Map)) {
    throw new Error(`${label} must be a map`);
  }
  for (const key of value.keys()) {
    if (!Number.isInteger(key) || !allowedKeys.has(key)) {
      throw new Error(`${label} contains unknown keys`);
    }
  }
  return value;
}

function requireArray(value, label) {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be a list`);
  }
  return value;
}

function requireString(value, label) {
  if (typeof value !== "string") {
    throw new Error(`${label} must be a string`);
  }
  return value;
}

function requireInt(value, label) {
  if (!Number.isInteger(value)) {
    throw new Error(`${label} must be an int`);
  }
  return value;
}

function requirePositiveInt(value, label) {
  const parsed = requireInt(value, label);
  if (parsed <= 0) {
    throw new Error(`${label} must be a positive int`);
  }
  return parsed;
}

function requireNonNegativeInt(value, label) {
  const parsed = requireInt(value, label);
  if (parsed < 0) {
    throw new Error(`${label} must be a non-negative int`);
  }
  return parsed;
}

function requireBytes(value, length, label) {
  if (!(value instanceof Uint8Array) || value.length !== length) {
    throw new Error(`${label} must be ${length} bytes`);
  }
  return value;
}

function requireNonEmptyBytes(value, label) {
  if (!(value instanceof Uint8Array) || !value.length) {
    throw new Error(`${label} must be non-empty bytes`);
  }
  return value;
}

function validateSortedUnique(items, key, message, compare = compareStrings) {
  let previous = "";
  const seen = new Set();
  for (const item of items) {
    const value = item[key];
    if (seen.has(value)) {
      throw new Error(`duplicate extension ${key}`);
    }
    if (previous && compare(value, previous) < 0) {
      throw new Error(message);
    }
    seen.add(value);
    previous = value;
  }
}

function compareStrings(left, right) {
  if (left === right) {
    return 0;
  }
  return left < right ? -1 : 1;
}

function compareUnicodeCodePointStrings(left, right) {
  const leftPoints = Array.from(left, (char) => char.codePointAt(0));
  const rightPoints = Array.from(right, (char) => char.codePointAt(0));
  const sharedLength = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < sharedLength; index += 1) {
    if (leftPoints[index] !== rightPoints[index]) {
      return leftPoints[index] - rightPoints[index];
    }
  }
  return leftPoints.length - rightPoints.length;
}

function chunkingEqual(left, right) {
  return (
    left.algorithmId === right.algorithmId &&
    left.targetSize === right.targetSize &&
    left.minSize === right.minSize &&
    left.maxSize === right.maxSize
  );
}
