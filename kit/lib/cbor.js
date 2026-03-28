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

const textDecoder = new TextDecoder();
const textEncoder = new TextEncoder();
const CBOR_FLOAT_BOX = Symbol("cborFloatBox");

export function decodeCbor(bytes) {
  const result = decodeCborItem(bytes, 0);
  if (result.offset !== bytes.length) {
    throw new Error("extra CBOR data");
  }
  return result.value;
}

export function decodeCanonicalCbor(bytes, label) {
  const typed = decodeCborWithOptions(bytes, { preserveFloatType: true });
  const encoded = encodeCbor(typed);
  if (!bytesEqual(encoded, bytes)) {
    throw new Error(
      `${label} must use canonical CBOR encoding (indefinite-length items are not allowed)`,
    );
  }
  return stripCborFloatBoxes(typed);
}

export function encodeCbor(value) {
  const chunks = [];
  encodeCborItem(value, chunks);
  return concatChunks(chunks);
}

function encodeCborItem(value, chunks) {
  if (isCborFloatBox(value)) {
    chunks.push(encodeCanonicalFloat(value.value));
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
    const entries = [];
    for (const [key, item] of Object.entries(value)) {
      if (typeof key !== "string") {
        throw new Error("unsupported CBOR map key");
      }
      entries.push({ keyBytes: encodeCbor(key), value: item });
    }
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
    chunks.push(encodeCanonicalFloat(value));
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

function stripCborFloatBoxes(value) {
  if (isCborFloatBox(value)) {
    return value.value;
  }
  if (Array.isArray(value)) {
    return value.map(stripCborFloatBoxes);
  }
  if (value instanceof Uint8Array || value === null || typeof value !== "object") {
    return value;
  }
  const out = {};
  for (const [key, item] of Object.entries(value)) {
    out[key] = stripCborFloatBoxes(item);
  }
  return out;
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

function concatChunks(chunks) {
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

function encodeCanonicalFloat(value) {
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
  const bytes = new Uint8Array(4);
  const view = new DataView(bytes.buffer, bytes.byteOffset, 4);
  view.setFloat32(0, value);
  return Object.is(view.getFloat32(0), value);
}

function encodeFloat16Exact(value) {
  const bits = floatToHalfBits(value);
  if (bits === null) {
    return null;
  }
  return Object.is(decodeHalfFloat(bits), value) ? bits : null;
}

function floatToHalfBits(value) {
  if (!Number.isFinite(value)) {
    return null;
  }
  const f32Bytes = new Uint8Array(4);
  const f32View = new DataView(f32Bytes.buffer, f32Bytes.byteOffset, 4);
  f32View.setFloat32(0, value);
  const x = f32View.getUint32(0);
  const sign = (x >>> 16) & 0x8000;
  let mantissa = x & 0x007fffff;
  let exp = (x >>> 23) & 0xff;

  if (exp === 0xff) {
    return null;
  }
  if (exp === 0) {
    return sign;
  }

  exp = exp - 127 + 15;
  if (exp >= 0x1f) {
    return sign | 0x7c00;
  }
  if (exp <= 0) {
    if (exp < -10) {
      return sign;
    }
    mantissa |= 0x00800000;
    const shift = 14 - exp;
    let halfMantissa = mantissa >> shift;
    const roundBit = 1 << (shift - 1);
    const roundMask = roundBit - 1;
    const remainder = mantissa & roundMask;
    const tie = mantissa & roundBit;
    if (tie && (remainder || halfMantissa & 1)) {
      halfMantissa += 1;
    }
    return sign | halfMantissa;
  }

  let halfMantissa = mantissa >> 13;
  const remainder = mantissa & 0x1fff;
  if (remainder > 0x1000 || (remainder === 0x1000 && halfMantissa & 1)) {
    halfMantissa += 1;
    if (halfMantissa === 0x400) {
      halfMantissa = 0;
      exp += 1;
      if (exp >= 0x1f) {
        return sign | 0x7c00;
      }
    }
  }
  return sign | (exp << 10) | halfMantissa;
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

function bytesEqual(left, right) {
  if (left.length !== right.length) {
    return false;
  }
  for (let idx = 0; idx < left.length; idx += 1) {
    if (left[idx] !== right[idx]) {
      return false;
    }
  }
  return true;
}

function decodeCborWithOptions(bytes, options = {}) {
  const result = decodeCborItem(bytes, 0, options);
  if (result.offset !== bytes.length) {
    throw new Error("extra CBOR data");
  }
  return result.value;
}

function decodeCborItem(bytes, offset, options = {}) {
  if (offset >= bytes.length) throw new Error("CBOR truncated");
  const first = bytes[offset++];
  const major = first >> 5;
  const addl = first & 0x1f;
  if (major === 7) {
    if (addl === 20) return { value: false, offset };
    if (addl === 21) return { value: true, offset };
    if (addl === 22) return { value: null, offset };
    if (addl === 25) {
      if (offset + 2 > bytes.length) throw new Error("CBOR float truncated");
      const bits = (bytes[offset] << 8) | bytes[offset + 1];
      const value = decodeHalfFloat(bits);
      return { value: options.preserveFloatType ? cborFloatBox(value) : value, offset: offset + 2 };
    }
    if (addl === 26) {
      if (offset + 4 > bytes.length) throw new Error("CBOR float truncated");
      const view = new DataView(bytes.buffer, bytes.byteOffset + offset, 4);
      const value = view.getFloat32(0);
      return { value: options.preserveFloatType ? cborFloatBox(value) : value, offset: offset + 4 };
    }
    if (addl === 27) {
      if (offset + 8 > bytes.length) throw new Error("CBOR float truncated");
      const view = new DataView(bytes.buffer, bytes.byteOffset + offset, 8);
      const value = view.getFloat64(0);
      return { value: options.preserveFloatType ? cborFloatBox(value) : value, offset: offset + 8 };
    }
    throw new Error("unsupported CBOR simple value");
  }

  const lengthInfo = readCborLength(bytes, offset, addl);
  const length = lengthInfo.value;
  offset = lengthInfo.offset;
  switch (major) {
    case 0:
      return { value: length, offset };
    case 1:
      return { value: -1 - length, offset };
    case 2: {
      const end = offset + length;
      if (end > bytes.length) throw new Error("CBOR bytes truncated");
      return { value: bytes.slice(offset, end), offset: end };
    }
    case 3: {
      const end = offset + length;
      if (end > bytes.length) throw new Error("CBOR text truncated");
      const text = textDecoder.decode(bytes.slice(offset, end));
      return { value: text, offset: end };
    }
    case 4: {
      const arr = [];
      for (let i = 0; i < length; i += 1) {
        const item = decodeCborItem(bytes, offset, options);
        arr.push(item.value);
        offset = item.offset;
      }
      return { value: arr, offset };
    }
    case 5: {
      const obj = {};
      for (let i = 0; i < length; i += 1) {
        const keyItem = decodeCborItem(bytes, offset, options);
        offset = keyItem.offset;
        const valItem = decodeCborItem(bytes, offset, options);
        offset = valItem.offset;
        obj[String(keyItem.value)] = valItem.value;
      }
      return { value: obj, offset };
    }
    default:
      throw new Error("unsupported CBOR type");
  }
}

function readCborLength(bytes, offset, addl) {
  if (addl < 24) return { value: addl, offset };
  if (addl === 24) {
    if (offset >= bytes.length) throw new Error("CBOR length truncated");
    return { value: bytes[offset], offset: offset + 1 };
  }
  if (addl === 25) {
    if (offset + 2 > bytes.length) throw new Error("CBOR length truncated");
    const value = (bytes[offset] << 8) | bytes[offset + 1];
    return { value, offset: offset + 2 };
  }
  if (addl === 26) {
    if (offset + 4 > bytes.length) throw new Error("CBOR length truncated");
    const view = new DataView(bytes.buffer, bytes.byteOffset + offset, 4);
    return { value: view.getUint32(0), offset: offset + 4 };
  }
  if (addl === 27) {
    if (offset + 8 > bytes.length) throw new Error("CBOR length truncated");
    const view = new DataView(bytes.buffer, bytes.byteOffset + offset, 8);
    const high = view.getUint32(0);
    const low = view.getUint32(4);
    const value = high * 2 ** 32 + low;
    if (value > Number.MAX_SAFE_INTEGER) throw new Error("CBOR integer too large");
    return { value, offset: offset + 8 };
  }
  throw new Error("indefinite CBOR lengths not supported");
}
