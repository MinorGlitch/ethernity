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

import { bytesEqual, concatByteParts } from "./bytes.js";

const textDecoder = new TextDecoder();
const textEncoder = new TextEncoder();
const CBOR_FLOAT_BOX = Symbol("cborFloatBox");

export function decodeCbor(bytes) {
  return decodeCborWithOptions(bytes);
}

export function decodeDeterministicCbor(bytes, label, options = {}) {
  return decodeCborWithOptions(bytes, { ...options, deterministicLabel: label });
}

export function encodeCbor(value) {
  const chunks = [];
  encodeCborItem(value, chunks);
  return concatByteParts(chunks);
}

function encodeCborItem(value, chunks) {
  if (isCborFloatBox(value)) {
    chunks.push(encodeShortestFloat(value.value));
    return;
  }
  if (value instanceof Uint8Array) {
    chunks.push(encodeMajorLength(2, value.length));
    chunks.push(value);
    return;
  }
  if (typeof value === "string") {
    const bytes = textEncoder.encode(value);
    chunks.push(encodeMajorLength(3, bytes.length));
    chunks.push(bytes);
    return;
  }
  if (Array.isArray(value)) {
    chunks.push(encodeMajorLength(4, value.length));
    for (const item of value) {
      encodeCborItem(item, chunks);
    }
    return;
  }
  if (value !== null && typeof value === "object") {
    const items = value instanceof Map ? value.entries() : Object.entries(value);
    const entries = Array.from(items, ([key, item]) => ({
      keyBytes: encodeCbor(key),
      value: item,
    }));
    entries.sort((left, right) => compareBytes(left.keyBytes, right.keyBytes));
    chunks.push(encodeMajorLength(5, entries.length));
    for (const entry of entries) {
      chunks.push(entry.keyBytes);
      encodeCborItem(entry.value, chunks);
    }
    return;
  }
  if (Number.isInteger(value) && !Object.is(value, -0)) {
    if (value >= 0) {
      chunks.push(encodeMajorLength(0, value));
    } else {
      chunks.push(encodeMajorLength(1, -1 - value));
    }
    return;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    chunks.push(encodeShortestFloat(value));
    return;
  }
  if (value === null) {
    chunks.push(Uint8Array.of(0xf6));
    return;
  }
  if (value === true) {
    chunks.push(Uint8Array.of(0xf5));
    return;
  }
  if (value === false) {
    chunks.push(Uint8Array.of(0xf4));
    return;
  }
  throw new Error("unsupported CBOR value");
}

function isCborFloatBox(value) {
  return value !== null && typeof value === "object" && value[CBOR_FLOAT_BOX] === true;
}

function cborFloatBox(value) {
  return { [CBOR_FLOAT_BOX]: true, value };
}

function compareBytes(left, right) {
  if (left.length !== right.length) return left.length - right.length;
  for (let idx = 0; idx < left.length; idx += 1) {
    const delta = left[idx] - right[idx];
    if (delta !== 0) return delta;
  }
  return 0;
}

function encodeMajorLength(major, length) {
  if (!Number.isFinite(length) || length < 0 || Math.floor(length) !== length) {
    throw new Error("invalid CBOR length");
  }
  if (length < 24) {
    return Uint8Array.of((major << 5) | length);
  }
  if (length < 0x100) {
    return Uint8Array.of((major << 5) | 24, length);
  }
  if (length < 0x10000) {
    return Uint8Array.of((major << 5) | 25, (length >> 8) & 0xff, length & 0xff);
  }
  if (length < 0x100000000) {
    return Uint8Array.of(
      (major << 5) | 26,
      (length >>> 24) & 0xff,
      (length >>> 16) & 0xff,
      (length >>> 8) & 0xff,
      length & 0xff,
    );
  }
  if (length <= Number.MAX_SAFE_INTEGER) {
    const high = Math.floor(length / 0x100000000);
    const low = length >>> 0;
    return Uint8Array.of(
      (major << 5) | 27,
      (high >>> 24) & 0xff,
      (high >>> 16) & 0xff,
      (high >>> 8) & 0xff,
      high & 0xff,
      (low >>> 24) & 0xff,
      (low >>> 16) & 0xff,
      (low >>> 8) & 0xff,
      low & 0xff,
    );
  }
  throw new Error("CBOR length too large");
}

function encodeShortestFloat(value) {
  const float16Bits = encodeFloat16Exact(value);
  if (float16Bits !== null) {
    return Uint8Array.of(0xf9, (float16Bits >> 8) & 0xff, float16Bits & 0xff);
  }
  if (isExactFloat32(value)) {
    const floatBytes = new Uint8Array(5);
    floatBytes[0] = 0xfa;
    const view = new DataView(floatBytes.buffer, floatBytes.byteOffset + 1, 4);
    view.setFloat32(0, value);
    return floatBytes;
  }
  const floatBytes = new Uint8Array(9);
  floatBytes[0] = 0xfb;
  const view = new DataView(floatBytes.buffer, floatBytes.byteOffset + 1, 8);
  view.setFloat64(0, value);
  return floatBytes;
}

function isExactFloat32(value) {
  return Object.is(Math.fround(value), value);
}

function encodeFloat16Exact(value) {
  const magnitude = Math.abs(value);
  if (!Number.isFinite(value) || magnitude > 65504) return null;
  const sign = value < 0 || Object.is(value, -0) ? 0x8000 : 0;
  // Subnormals use a fixed step; normal values have ten fraction bits.
  if (magnitude < 2 ** -14) {
    const fraction = magnitude * 2 ** 24;
    return Number.isInteger(fraction) ? sign | fraction : null;
  }
  const exponent = Math.floor(Math.log2(magnitude));
  const fraction = magnitude / 2 ** (exponent - 10) - 1024;
  return Number.isInteger(fraction) ? sign | ((exponent + 15) << 10) | fraction : null;
}

function decodeHalfFloat(bits) {
  const sign = bits & 0x8000 ? -1 : 1;
  const exp = (bits >> 10) & 0x1f;
  const mantissa = bits & 0x03ff;
  if (exp === 0) {
    if (mantissa === 0) {
      return sign < 0 ? -0 : 0;
    }
    return sign * (mantissa / 1024) * 2 ** -14;
  }
  if (exp === 0x1f) {
    if (mantissa === 0) {
      return sign < 0 ? -Infinity : Infinity;
    }
    return NaN;
  }
  return sign * (1 + mantissa / 1024) * 2 ** (exp - 15);
}

function decodeCborWithOptions(bytes, options = {}) {
  let offset = 0;
  const deterministic = "deterministicLabel" in options;
  const rejectEncoding = () => {
    throw new Error(
      `${options.deterministicLabel} must use deterministic CBOR encoding (indefinite-length items are not allowed)`,
    );
  };

  function readLength(addl) {
    if (addl < 24) return addl;
    if (addl > 27) throw new Error("indefinite CBOR lengths not supported");
    const width = 2 ** (addl - 24);
    if (offset + width > bytes.length) throw new Error("CBOR length truncated");
    let value = 0;
    for (let i = 0; i < width; i += 1) value = value * 256 + bytes[offset++];
    if (value > Number.MAX_SAFE_INTEGER) throw new Error("CBOR integer too large");
    if (deterministic && value < [24, 0x100, 0x10000, 0x100000000][addl - 24]) {
      rejectEncoding();
    }
    return value;
  }

  function read(preserveFloatType = options.preserveFloatType) {
    if (offset >= bytes.length) throw new Error("CBOR truncated");
    const start = offset;
    const first = bytes[offset++];
    const major = first >> 5;
    const addl = first & 0x1f;
    if (major === 7) {
      if (addl === 20) return false;
      if (addl === 21) return true;
      if (addl === 22) return null;
      if (addl < 25 || addl > 27) throw new Error("unsupported CBOR simple value");
      const width = 2 ** (addl - 24);
      if (offset + width > bytes.length) throw new Error("CBOR float truncated");
      const view = new DataView(bytes.buffer, bytes.byteOffset + offset, width);
      const value =
        width === 2
          ? decodeHalfFloat(view.getUint16(0))
          : width === 4
            ? view.getFloat32(0)
            : view.getFloat64(0);
      offset += width;
      if (deterministic && !bytesEqual(encodeShortestFloat(value), bytes.subarray(start, offset))) {
        rejectEncoding();
      }
      return preserveFloatType ? cborFloatBox(value) : value;
    }

    const length = readLength(addl);
    switch (major) {
      case 0:
        return length;
      case 1:
        return -1 - length;
      case 2:
      case 3: {
        const end = offset + length;
        if (end > bytes.length) {
          throw new Error(major === 2 ? "CBOR bytes truncated" : "CBOR text truncated");
        }
        const data = bytes.subarray(offset, end);
        offset = end;
        if (major === 2) return data.slice();
        const text = textDecoder.decode(data);
        // Preserve the existing UTF-8 checks without re-encoding the containing document.
        if (deterministic && !bytesEqual(textEncoder.encode(text), data)) rejectEncoding();
        return text;
      }
      case 4: {
        const array = [];
        for (let i = 0; i < length; i += 1) array.push(read(preserveFloatType));
        return array;
      }
      case 5: {
        const map = options.preserveMapType ? new Map() : {};
        let previousKey = null;
        for (let i = 0; i < length; i += 1) {
          const keyStart = offset;
          // Map keys retain their wire type, including floating-point keys.
          const key = read(deterministic || preserveFloatType);
          const keyBytes = bytes.subarray(keyStart, offset);
          if (deterministic) {
            if (previousKey && compareBytes(previousKey, keyBytes) >= 0) rejectEncoding();
            if (!options.preserveMapType && (typeof key !== "string" || key === "__proto__")) {
              rejectEncoding();
            }
          }
          previousKey = keyBytes;
          const value = read(preserveFloatType);
          if (options.preserveMapType) map.set(key, value);
          else map[String(key)] = value;
        }
        return map;
      }
      default:
        throw new Error("unsupported CBOR type");
    }
  }

  const value = read();
  if (offset !== bytes.length) throw new Error("extra CBOR data");
  return value;
}
