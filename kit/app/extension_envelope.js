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

import { sha256 } from "@noble/hashes/sha2.js";

import { decodeCanonicalCbor } from "../lib/cbor.js";
import { crc32 } from "../lib/crc32.js";
import { bytesEqual, bytesToHex, readUvarint } from "../lib/encoding.js";
import {
  CHUNK_ALGORITHM_FASTCDC,
  CHUNK_CODEC_GZIP,
  CHUNK_CODEC_RAW,
  ENVELOPE_MAGIC,
  EXTENSION_ENVELOPE_VERSION,
  EXTENSION_SCHEMA_VERSION,
  MAX_DECOMPRESSED_PAYLOAD_BYTES,
  MAX_MANIFEST_CBOR_BYTES,
  MAX_MANIFEST_FILES,
} from "./constants.js";
import { validateManifestPath } from "../lib/path_validation.js";

const HEADER_KEYS = new Set([1, 2, 4, 5, 7, 10, 11, 12]);
const BODY_KEYS = new Set([1, 2]);
const ROLLING_HASH_MASK = (1n << 64n) - 1n;
const ROLLING_WINDOW_SIZE = 64;
const MIN_MASK_BITS = 4;
const MIN_EXTENSION_CHUNK_SIZE = 4 * 1024;
const GEAR_TABLE = buildGearTable();
const LENGTH_EXTRA_BITS = [
  0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0,
];
const DISTANCE_EXTRA_BITS = [
  0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13,
];

export async function decodeExtensionEnvelope(bytes) {
  let idx = 0;
  if (bytes.length < ENVELOPE_MAGIC.length + 1) {
    throw new Error("extension envelope too short");
  }
  if (bytes[0] !== ENVELOPE_MAGIC[0] || bytes[1] !== ENVELOPE_MAGIC[1]) {
    throw new Error("invalid envelope magic");
  }
  idx += ENVELOPE_MAGIC.length;

  const versionRes = readUvarint(bytes, idx);
  idx = versionRes.offset;
  if (versionRes.value !== EXTENSION_ENVELOPE_VERSION) {
    throw new Error(`unsupported envelope version: ${versionRes.value}`);
  }

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
    decodeCanonicalCbor(bytes.slice(idx, headerEnd), "extension header", {
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
  const body = await parseExtensionBody(
    decodeCanonicalCbor(bytes.slice(idx, bodyEnd), "extension body", {
      preserveFloatType: true,
      preserveMapType: true,
    }),
    header,
  );
  return { header, files: body.files, chunks: body.chunks };
}

function parseExtensionHeader(value) {
  const header = requireIntKeyMap(value, HEADER_KEYS, "extension header");
  for (const key of HEADER_KEYS) {
    if (!header.has(key)) {
      throw new Error(`extension header key ${key} is required`);
    }
  }
  const version = requireInt(header.get(1), "extension header version");
  if (version !== EXTENSION_SCHEMA_VERSION) {
    throw new Error(`unsupported extension header version: ${version}`);
  }
  const index = requirePositiveInt(header.get(2), "extension header index");
  const parentDocHash = requireBytes(header.get(4), 32, "extension header parent_doc_hash");
  const rootDocHash = requireBytes(header.get(5), 32, "extension header root_doc_hash");
  const createdAt = requireInt(header.get(7), "extension header created_at");
  const chunking = parseChunking(header.get(10));
  const inputOrigin = requireString(header.get(11), "extension header input_origin");
  if (!["file", "directory", "mixed"].includes(inputOrigin)) {
    throw new Error("extension header input_origin must be one of: file, directory, mixed");
  }
  const inputRoots = requireArray(header.get(12), "extension header input_roots").map((root) =>
    normalizeRootLabel(root),
  );
  if (inputOrigin === "file" && inputRoots.length) {
    throw new Error("extension header input_roots must be empty when input_origin is file");
  }
  if ((inputOrigin === "directory" || inputOrigin === "mixed") && !inputRoots.length) {
    throw new Error("extension header input_roots must be non-empty for directory or mixed input");
  }
  return {
    version,
    index,
    parentDocHash,
    rootDocHash,
    createdAt,
    chunking,
    inputOrigin,
    inputRoots,
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
  if (profile.minSize > profile.targetSize || profile.targetSize > profile.maxSize) {
    throw new Error("extension chunking sizes must satisfy min <= target <= max");
  }
  for (const [label, value] of [
    ["target_size", profile.targetSize],
    ["min_size", profile.minSize],
    ["max_size", profile.maxSize],
  ]) {
    if (value < MIN_EXTENSION_CHUNK_SIZE) {
      throw new Error(
        `extension chunking ${label} must be >= MIN_EXTENSION_CHUNK_SIZE (${MIN_EXTENSION_CHUNK_SIZE})`,
      );
    }
    if (value > MAX_DECOMPRESSED_PAYLOAD_BYTES) {
      throw new Error(`extension chunking ${label} exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES`);
    }
  }
  return profile;
}

async function parseExtensionBody(value, header) {
  const body = requireIntKeyMap(value, BODY_KEYS, "extension body");
  if (!body.has(1) || !body.has(2)) {
    throw new Error("extension body files and chunks are required");
  }
  const files = requireArray(body.get(1), "extension body files").map(parseExtensionFile);
  if (!files.length) {
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
      throw new Error("extension inline chunks must be referenced by files in the same envelope");
    }
  }
  for (const chunk of chunks) {
    chunk.decoded = await decodeChunkData(chunk);
  }
  for (const file of files) {
    validateCanonicalChunkRefs(file, new Map(), chunks, header.chunking, {
      allowUnresolved: true,
    });
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
  return {
    chunkId,
    chunkIdHex: bytesToHex(chunkId),
    uncompressedLen: requirePositiveInt(fields[1], "extension chunk_ref uncompressed_len"),
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

export async function reconstructLatestFiles(rootFiles, rootDocHash, extensions) {
  if (!extensions.length) {
    return rootFiles.map((file) => ({ ...file, data: file.data.slice() }));
  }
  validateExtensionChain(rootDocHash, extensions);
  const lockedChunking = extensions[0].header.chunking;
  const state = new Map(rootFiles.map((file) => [file.path, { ...file, data: file.data.slice() }]));
  const neededRefs = extensionChunkRefCounts(extensions);
  const seenChunkIds = new Set();
  const availableChunks = virtualRootChunkMap(rootFiles, lockedChunking, neededRefs, seenChunkIds);

  for (const extension of extensions) {
    mergeNewExtensionChunks(availableChunks, extension, neededRefs, seenChunkIds);
    const projected = new Map(state);
    for (const file of extension.files) {
      projected.set(file.path, { ...file, data: new Uint8Array(file.size) });
    }
    if (projected.size > MAX_MANIFEST_FILES) {
      throw new Error(`logical latest state exceeds MAX_MANIFEST_FILES (${MAX_MANIFEST_FILES})`);
    }
    const logicalBytes = Array.from(projected.values()).reduce((sum, file) => sum + file.size, 0);
    if (logicalBytes > MAX_DECOMPRESSED_PAYLOAD_BYTES) {
      throw new Error("logical latest state exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES");
    }
    for (const file of extension.files) {
      state.set(file.path, resolveExtensionFileState(file, availableChunks, lockedChunking));
    }
    consumeExtensionChunkRefs(neededRefs, availableChunks, extension);
  }

  return Array.from(state.keys())
    .sort(compareUnicodeCodePointStrings)
    .map((path) => state.get(path));
}

export function validateExtensionChain(rootDocHash, extensions) {
  let expectedParentDocHash = rootDocHash;
  let expectedIndex = 1;
  let lockedChunking = null;
  for (const extension of extensions) {
    const header = extension.header;
    if (header.index !== expectedIndex) {
      throw new Error(`extension index sequence is invalid: expected ${expectedIndex}`);
    }
    if (!bytesEqual(header.rootDocHash, rootDocHash)) {
      throw new Error("extension root_doc_hash does not match root backup");
    }
    if (!bytesEqual(header.parentDocHash, expectedParentDocHash)) {
      throw new Error("extension parent_doc_hash does not match previous document");
    }
    if (!lockedChunking) {
      lockedChunking = header.chunking;
    } else if (!chunkingEqual(lockedChunking, header.chunking)) {
      throw new Error("extension chunking profile must match the locked chain profile");
    }
    expectedParentDocHash = extension.docHash;
    expectedIndex += 1;
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
  const data = concatByteParts(chunks);
  if (!bytesEqual(sha256(data), file.sha)) {
    throw new Error(`extension file sha256 mismatch for ${file.path}`);
  }
  requireCanonicalChunkRefs(file, data, chunking);
  return { path: file.path, size: file.size, sha: file.sha, mtime: file.mtime, data };
}

function validateCanonicalChunkRefs(file, availableChunks, chunks, chunking, options = {}) {
  if (options.allowUnresolved) {
    const inlineChunks = new Map(chunks.map((chunk) => [chunk.chunkIdHex, chunk.decoded]));
    for (const ref of file.chunkRefs) {
      if (!inlineChunks.has(ref.chunkIdHex)) {
        return;
      }
    }
  }
  const data = concatByteParts(
    file.chunkRefs.map((ref) => {
      const chunk = availableChunks.get(ref.chunkIdHex);
      if (!chunk) {
        const inline = chunks.find((item) => item.chunkIdHex === ref.chunkIdHex);
        return inline?.decoded ?? new Uint8Array();
      }
      return chunk;
    }),
  );
  if (data.length === file.size) {
    requireCanonicalChunkRefs(file, data, chunking);
  }
}

function requireCanonicalChunkRefs(file, data, chunking) {
  const expected = canonicalChunkRefsForBytes(data, chunking);
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

function extensionChunkRefCounts(extensions) {
  const counts = new Map();
  for (const extension of extensions) {
    for (const file of extension.files) {
      for (const ref of file.chunkRefs) {
        counts.set(ref.chunkIdHex, (counts.get(ref.chunkIdHex) ?? 0) + 1);
      }
    }
  }
  return counts;
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

async function gunzipBytesBounded(bytes, expectedLen) {
  if (typeof DecompressionStream !== "function") {
    throw new Error("gzip extension chunks require DecompressionStream support");
  }
  const gzipTrailer = validateSingleGzipMember(bytes, expectedLen);
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  const reader = stream.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      if (!(value instanceof Uint8Array)) continue;
      total += value.length;
      if (total > expectedLen) {
        throw new Error("decoded chunk exceeds raw_len");
      }
      chunks.push(value);
    }
  } catch (err) {
    try {
      await reader.cancel();
    } catch {
      // Ignore cancellation failures while surfacing the primary decode error.
    }
    if (err instanceof Error && err.message === "decoded chunk exceeds raw_len") {
      throw err;
    }
    throw new Error("invalid gzip chunk");
  } finally {
    reader.releaseLock();
  }
  const decoded = concatByteParts(chunks);
  if (decoded.length !== expectedLen) {
    throw new Error("decoded chunk length does not match raw_len");
  }
  if (crc32(decoded) !== gzipTrailer.crc32) {
    throw new Error("invalid gzip chunk");
  }
  return decoded;
}

export function validateSingleGzipMember(bytes, expectedLen) {
  const dataStart = gzipDeflateDataStart(bytes);
  const trailerStart = deflateStreamEndOffset(bytes, dataStart);
  if (trailerStart + 8 !== bytes.length) {
    throw new Error("gzip chunk contains trailing data");
  }
  const expectedSize = readLittleUint32(bytes, trailerStart + 4);
  if (expectedSize !== expectedLen) {
    throw new Error("decoded chunk length does not match raw_len");
  }
  return { crc32: readLittleUint32(bytes, trailerStart) };
}

function gzipDeflateDataStart(bytes) {
  if (bytes.length < 18) {
    throw new Error("invalid gzip chunk");
  }
  if (bytes[0] !== 0x1f || bytes[1] !== 0x8b || bytes[2] !== 8) {
    throw new Error("invalid gzip chunk");
  }
  const flags = bytes[3];
  if (flags & 0xe0) {
    throw new Error("invalid gzip chunk");
  }
  let offset = 10;
  if (flags & 0x04) {
    if (offset + 2 > bytes.length) throw new Error("invalid gzip chunk");
    const extraLen = bytes[offset] | (bytes[offset + 1] << 8);
    offset += 2 + extraLen;
    if (offset > bytes.length) throw new Error("invalid gzip chunk");
  }
  if (flags & 0x08) {
    offset = skipNulTerminatedGzipField(bytes, offset);
  }
  if (flags & 0x10) {
    offset = skipNulTerminatedGzipField(bytes, offset);
  }
  if (flags & 0x02) {
    offset += 2;
    if (offset > bytes.length) throw new Error("invalid gzip chunk");
  }
  if (offset + 8 > bytes.length) {
    throw new Error("invalid gzip chunk");
  }
  return offset;
}

function skipNulTerminatedGzipField(bytes, offset) {
  while (offset < bytes.length) {
    if (bytes[offset] === 0) {
      return offset + 1;
    }
    offset += 1;
  }
  throw new Error("invalid gzip chunk");
}

function deflateStreamEndOffset(bytes, startOffset) {
  const reader = new BitReader(bytes, startOffset);
  let finalBlock = false;
  while (!finalBlock) {
    finalBlock = reader.readBits(1) === 1;
    const blockType = reader.readBits(2);
    if (blockType === 0) {
      reader.alignToByte();
      const len = reader.readUint16();
      const nlen = reader.readUint16();
      if (((len ^ 0xffff) & 0xffff) !== nlen) {
        throw new Error("invalid gzip chunk");
      }
      reader.skipBytes(len);
    } else if (blockType === 1) {
      skipCompressedDeflateBlock(reader, fixedLiteralLengthTree(), fixedDistanceTree());
    } else if (blockType === 2) {
      const trees = dynamicDeflateTrees(reader);
      skipCompressedDeflateBlock(reader, trees.literalLengthTree, trees.distanceTree);
    } else {
      throw new Error("invalid gzip chunk");
    }
  }
  return reader.byteOffset();
}

function skipCompressedDeflateBlock(reader, literalLengthTree, distanceTree) {
  while (true) {
    const symbol = literalLengthTree.readSymbol(reader);
    if (symbol < 256) {
      continue;
    }
    if (symbol === 256) {
      return;
    }
    if (symbol < 257 || symbol > 285) {
      throw new Error("invalid gzip chunk");
    }
    const lengthIndex = symbol - 257;
    reader.readBits(LENGTH_EXTRA_BITS[lengthIndex]);
    const distanceSymbol = distanceTree.readSymbol(reader);
    if (distanceSymbol < 0 || distanceSymbol >= DISTANCE_EXTRA_BITS.length) {
      throw new Error("invalid gzip chunk");
    }
    reader.readBits(DISTANCE_EXTRA_BITS[distanceSymbol]);
  }
}

function dynamicDeflateTrees(reader) {
  const literalLengthCount = reader.readBits(5) + 257;
  const distanceCount = reader.readBits(5) + 1;
  const codeLengthCount = reader.readBits(4) + 4;
  const codeLengthOrder = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];
  const codeLengthLengths = new Array(19).fill(0);
  for (let index = 0; index < codeLengthCount; index += 1) {
    codeLengthLengths[codeLengthOrder[index]] = reader.readBits(3);
  }
  const codeLengthTree = HuffmanTree.fromCodeLengths(codeLengthLengths);
  const lengths = [];
  const totalLengths = literalLengthCount + distanceCount;
  while (lengths.length < totalLengths) {
    const symbol = codeLengthTree.readSymbol(reader);
    if (symbol <= 15) {
      lengths.push(symbol);
    } else if (symbol === 16) {
      if (!lengths.length) throw new Error("invalid gzip chunk");
      const repeat = reader.readBits(2) + 3;
      appendRepeatedLength(lengths, lengths.at(-1), repeat, totalLengths);
    } else if (symbol === 17) {
      appendRepeatedLength(lengths, 0, reader.readBits(3) + 3, totalLengths);
    } else if (symbol === 18) {
      appendRepeatedLength(lengths, 0, reader.readBits(7) + 11, totalLengths);
    } else {
      throw new Error("invalid gzip chunk");
    }
  }
  const literalLengthLengths = lengths.slice(0, literalLengthCount);
  const distanceLengths = lengths.slice(literalLengthCount);
  return {
    literalLengthTree: HuffmanTree.fromCodeLengths(literalLengthLengths),
    distanceTree: HuffmanTree.fromCodeLengths(distanceLengths),
  };
}

function appendRepeatedLength(lengths, value, repeat, maxLength) {
  if (lengths.length + repeat > maxLength) {
    throw new Error("invalid gzip chunk");
  }
  for (let index = 0; index < repeat; index += 1) {
    lengths.push(value);
  }
}

let cachedFixedLiteralLengthTree = null;
let cachedFixedDistanceTree = null;

function fixedLiteralLengthTree() {
  if (!cachedFixedLiteralLengthTree) {
    const lengths = new Array(288);
    lengths.fill(8, 0, 144);
    lengths.fill(9, 144, 256);
    lengths.fill(7, 256, 280);
    lengths.fill(8, 280, 288);
    cachedFixedLiteralLengthTree = HuffmanTree.fromCodeLengths(lengths);
  }
  return cachedFixedLiteralLengthTree;
}

function fixedDistanceTree() {
  if (!cachedFixedDistanceTree) {
    cachedFixedDistanceTree = HuffmanTree.fromCodeLengths(new Array(32).fill(5));
  }
  return cachedFixedDistanceTree;
}

class BitReader {
  constructor(bytes, byteOffset) {
    this.bytes = bytes;
    this.bitOffset = byteOffset * 8;
  }

  readBits(count) {
    let value = 0;
    for (let index = 0; index < count; index += 1) {
      if (this.bitOffset >= this.bytes.length * 8) {
        throw new Error("invalid gzip chunk");
      }
      const byte = this.bytes[this.bitOffset >> 3];
      const bit = (byte >> (this.bitOffset & 7)) & 1;
      value |= bit << index;
      this.bitOffset += 1;
    }
    return value;
  }

  alignToByte() {
    this.bitOffset = Math.ceil(this.bitOffset / 8) * 8;
  }

  readUint16() {
    this.alignToByte();
    const offset = this.bitOffset >> 3;
    if (offset + 2 > this.bytes.length) {
      throw new Error("invalid gzip chunk");
    }
    this.bitOffset += 16;
    return this.bytes[offset] | (this.bytes[offset + 1] << 8);
  }

  skipBytes(count) {
    this.alignToByte();
    const offset = this.bitOffset >> 3;
    if (offset + count > this.bytes.length) {
      throw new Error("invalid gzip chunk");
    }
    this.bitOffset += count * 8;
  }

  byteOffset() {
    return Math.ceil(this.bitOffset / 8);
  }
}

class HuffmanTree {
  constructor(root) {
    this.root = root;
  }

  static fromCodeLengths(lengths) {
    const maxBits = Math.max(...lengths, 0);
    const blCount = new Array(maxBits + 1).fill(0);
    for (const length of lengths) {
      if (length < 0 || length > 15) throw new Error("invalid gzip chunk");
      if (length > 0) blCount[length] += 1;
    }
    const nextCode = new Array(maxBits + 1).fill(0);
    let code = 0;
    for (let bits = 1; bits <= maxBits; bits += 1) {
      code = (code + (blCount[bits - 1] ?? 0)) << 1;
      nextCode[bits] = code;
    }
    const root = {};
    for (let symbol = 0; symbol < lengths.length; symbol += 1) {
      const length = lengths[symbol];
      if (!length) continue;
      insertHuffmanCode(root, reverseBits(nextCode[length], length), length, symbol);
      nextCode[length] += 1;
    }
    return new HuffmanTree(root);
  }

  readSymbol(reader) {
    let node = this.root;
    while (node.symbol === undefined) {
      node = node[reader.readBits(1)];
      if (!node) throw new Error("invalid gzip chunk");
    }
    return node.symbol;
  }
}

function insertHuffmanCode(root, code, length, symbol) {
  let node = root;
  for (let index = 0; index < length; index += 1) {
    const bit = (code >> index) & 1;
    node[bit] ??= {};
    node = node[bit];
  }
  node.symbol = symbol;
}

function reverseBits(value, length) {
  let reversed = 0;
  for (let index = 0; index < length; index += 1) {
    reversed = (reversed << 1) | ((value >> index) & 1);
  }
  return reversed;
}

function readLittleUint32(bytes, offset) {
  if (offset + 4 > bytes.length) {
    throw new Error("invalid gzip chunk");
  }
  return (
    (bytes[offset] |
      (bytes[offset + 1] << 8) |
      (bytes[offset + 2] << 16) |
      (bytes[offset + 3] << 24)) >>>
    0
  );
}

export function canonicalChunkRefsForBytes(data, chunking) {
  return defaultExtensionChunker(data, chunking).map((chunk) => [sha256(chunk), chunk.length]);
}

export function defaultExtensionChunker(data, profile) {
  if (!data.length) {
    return [];
  }
  const chunks = [];
  let start = 0;
  const [primaryMask, secondaryMask] = rollingMasks(profile.targetSize);
  while (start < data.length) {
    const chunkEnd = nextChunkBoundary(data, {
      start,
      minSize: profile.minSize,
      targetSize: profile.targetSize,
      maxSize: profile.maxSize,
      primaryMask,
      secondaryMask,
    });
    chunks.push(data.slice(start, chunkEnd));
    start = chunkEnd;
  }
  return chunks;
}

function rollingMasks(targetSize) {
  const targetBits = Math.max(MIN_MASK_BITS, Math.round(Math.log2(Math.max(2, targetSize))));
  const primaryBits = Math.min(63, targetBits);
  const secondaryBits = Math.max(MIN_MASK_BITS, targetBits - 2);
  return [(1n << BigInt(primaryBits)) - 1n, (1n << BigInt(secondaryBits)) - 1n];
}

function nextChunkBoundary(data, options) {
  const totalLen = data.length;
  const { start, minSize, targetSize, maxSize, primaryMask, secondaryMask } = options;
  if (totalLen - start <= minSize) {
    return totalLen;
  }
  const minEnd = Math.min(totalLen, start + minSize);
  const targetEnd = Math.min(totalLen, start + targetSize);
  const maxEnd = Math.min(totalLen, start + maxSize);
  let fingerprint = 0n;
  const window = new Uint8Array(ROLLING_WINDOW_SIZE);
  let windowCount = 0;
  let windowPos = 0;
  for (let index = start; index < maxEnd; index += 1) {
    const byteValue = data[index];
    if (windowCount < ROLLING_WINDOW_SIZE) {
      fingerprint = rollFingerprint(fingerprint, byteValue);
      window[windowPos] = byteValue;
      windowPos = (windowPos + 1) % ROLLING_WINDOW_SIZE;
      windowCount += 1;
    } else {
      const outgoing = window[windowPos];
      window[windowPos] = byteValue;
      windowPos = (windowPos + 1) % ROLLING_WINDOW_SIZE;
      fingerprint =
        (rotateLeft(fingerprint, 1) ^ GEAR_TABLE[outgoing] ^ GEAR_TABLE[byteValue]) &
        ROLLING_HASH_MASK;
    }
    if (index + 1 < minEnd) {
      continue;
    }
    const mask = index + 1 < targetEnd ? primaryMask : secondaryMask;
    if ((fingerprint & mask) === 0n) {
      return index + 1;
    }
  }
  return maxEnd;
}

function rollFingerprint(current, byteValue) {
  return rotateLeft(current, 1) ^ GEAR_TABLE[byteValue];
}

function rotateLeft(value, shift) {
  const normalized = BigInt(shift & 63);
  return ((value << normalized) | (value >> (64n - normalized))) & ROLLING_HASH_MASK;
}

function buildGearTable() {
  let state = 0x9e3779b97f4a7c15n;
  const values = [];
  for (let index = 0; index < 256; index += 1) {
    state ^= (state >> 12n) & ROLLING_HASH_MASK;
    state ^= (state << 25n) & ROLLING_HASH_MASK;
    state ^= (state >> 27n) & ROLLING_HASH_MASK;
    state = (state * 0x2545f4914f6cdd1dn) & ROLLING_HASH_MASK;
    values.push(state);
  }
  return values;
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

function normalizeRootLabel(value) {
  const root = validateManifestPath(requireString(value, "extension header input_root"));
  if (!root || root.includes("/") || root.includes("\\")) {
    throw new Error("extension header input_root must be a leaf label without path separators");
  }
  return root;
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

function concatByteParts(parts) {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}
