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

import { crc32 } from "./crc32.js";

const GZIP_CHUNK_MESSAGES = [
  "gzip extension chunks require DecompressionStream support",
  "gzip chunk contains trailing data",
  "decoded chunk exceeds raw_len",
  "decoded chunk length does not match raw_len",
  "invalid gzip chunk",
];
const LENGTH_EXTRA_BITS = [
  0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0,
];
const DISTANCE_EXTRA_BITS = [
  0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13,
];

export async function gunzipBytesBounded(bytes, expectedLen, messages = GZIP_CHUNK_MESSAGES) {
  if (typeof DecompressionStream !== "function") {
    throw new Error(messages[0]);
  }
  const gzipTrailer = validateSingleGzipMember(bytes, expectedLen, messages);
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
        throw new Error(messages[2]);
      }
      chunks.push(value);
    }
  } catch (err) {
    try {
      await reader.cancel();
    } catch {
      // Ignore cancellation failures while surfacing the primary decode error.
    }
    if (err instanceof Error && err.message === messages[2]) {
      throw err;
    }
    throw new Error(messages[4]);
  } finally {
    reader.releaseLock();
  }
  const decoded = concatByteParts(chunks);
  if (decoded.length !== expectedLen) {
    throw new Error(messages[3]);
  }
  if (crc32(decoded) !== gzipTrailer.crc32) {
    throw new Error(messages[4]);
  }
  return decoded;
}

function validateSingleGzipMember(bytes, expectedLen, messages) {
  const dataStart = gzipDeflateDataStart(bytes);
  const trailerStart = deflateStreamEndOffset(bytes, dataStart);
  if (trailerStart + 8 !== bytes.length) {
    throw new Error(messages[1]);
  }
  const expectedSize = readLittleUint32(bytes, trailerStart + 4);
  if (expectedSize > expectedLen) {
    throw new Error(messages[2]);
  }
  if (expectedSize !== expectedLen) {
    throw new Error(messages[3]);
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
