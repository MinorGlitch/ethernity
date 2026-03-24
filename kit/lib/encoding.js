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

import { MAX_QR_PAYLOAD_CHARS } from "../app/constants.js";

const ZBASE32_ALPHABET = "ybndrfg8ejkmcpqxot1uwisza345h769";
const BASE64_ALPHABET = /^[A-Za-z0-9+/]+$/;
const MAX_UVARINT = (1n << 64n) - 1n;
const BASE64_BINARY_CHUNK = 0x8000;

function isBase64(text) {
  return BASE64_ALPHABET.test(text);
}

export function bytesToUnpaddedBase64(bytes) {
  if (!(bytes instanceof Uint8Array)) {
    throw new Error("bytesToUnpaddedBase64 expects Uint8Array");
  }
  if (bytes.length === 0) return "";
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += BASE64_BINARY_CHUNK) {
    const chunk = bytes.subarray(offset, offset + BASE64_BINARY_CHUNK);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary).replace(/=+$/u, "");
}

export function decodePayloadString(text) {
  const cleaned = text.replace(/\s+/g, "");
  if (!cleaned) return null;
  if (cleaned.length > MAX_QR_PAYLOAD_CHARS) return null;
  if (cleaned.includes("=") || cleaned.includes("-") || cleaned.includes("_")) {
    return null;
  }
  if (cleaned.length % 4 === 1) return null;
  if (isBase64(cleaned)) {
    try {
      const padded = cleaned + "===".slice((cleaned.length + 3) % 4);
      const binary = atob(padded);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) {
        bytes[i] = binary.codePointAt(i);
      }
      if (bytesToUnpaddedBase64(bytes) !== cleaned) {
        return null;
      }
      return bytes;
    } catch (err) {
      return null;
    }
  }
  return null;
}

function encodeZBase32(bytes) {
  if (!(bytes instanceof Uint8Array)) {
    throw new Error("encodeZBase32 expects Uint8Array");
  }
  if (bytes.length === 0) {
    return "";
  }
  let bits = 0;
  let bitCount = 0;
  let out = "";
  for (const byte of bytes) {
    bits = (bits << 8) | byte;
    bitCount += 8;
    while (bitCount >= 5) {
      const shift = bitCount - 5;
      out += ZBASE32_ALPHABET[(bits >> shift) & 0x1f];
      bitCount -= 5;
      bits &= (1 << bitCount) - 1;
    }
  }
  if (bitCount) {
    out += ZBASE32_ALPHABET[(bits << (5 - bitCount)) & 0x1f];
  }
  return out;
}

export function decodeZBase32(text) {
  let bits = 0;
  let bitCount = 0;
  const out = [];
  const normalizedChars = [];
  for (const ch of text) {
    if (ch === "-" || /\s/.test(ch)) continue;
    const normalized = ch.toLowerCase();
    const idx = ZBASE32_ALPHABET.indexOf(normalized);
    if (idx === -1) throw new Error(`invalid z-base-32 character: ${ch}`);
    normalizedChars.push(normalized);
    bits = (bits << 5) | idx;
    bitCount += 5;
    if (bitCount >= 8) {
      const shift = bitCount - 8;
      out.push((bits >> shift) & 0xff);
      bitCount -= 8;
      bits &= (1 << bitCount) - 1;
    }
  }
  const decoded = new Uint8Array(out);
  if (encodeZBase32(decoded) !== normalizedChars.join("")) {
    throw new Error("invalid z-base-32 text: non-canonical tail bits");
  }
  return decoded;
}

export function filterZBase32Lines(text) {
  const lines = text.split(/\r?\n/);
  const filtered = [];
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    let ok = true;
    for (const ch of line) {
      if (ch === "-" || /\s/.test(ch)) continue;
      if (!ZBASE32_ALPHABET.includes(ch.toLowerCase())) {
        ok = false;
        break;
      }
    }
    if (ok) filtered.push(line);
  }
  return filtered;
}

export function readUvarint(bytes, offset) {
  let value = 0n;
  let shift = 0n;
  let idx = offset;
  while (idx < bytes.length) {
    const byte = bytes[idx++];
    const part = BigInt(byte & 0x7f);
    if (shift === 63n && part > 1n) {
      throw new Error("varint too large");
    }
    value |= part << shift;
    if (value > MAX_UVARINT) {
      throw new Error("varint too large");
    }
    if ((byte & 0x80) === 0) {
      const encoded = encodeUvarint(value);
      const actual = bytes.slice(offset, idx);
      if (!bytesEqual(encoded, actual)) {
        throw new Error("non-canonical varint");
      }
      if (value > BigInt(Number.MAX_SAFE_INTEGER)) {
        throw new Error("varint too large");
      }
      return { value: Number(value), offset: idx };
    }
    shift += 7n;
    if (shift > 63n) throw new Error("varint too large");
  }
  throw new Error("truncated varint");
}

function encodeUvarint(value) {
  let current = value;
  const out = [];
  while (true) {
    const byte = Number(current & 0x7fn);
    current >>= 7n;
    if (current) {
      out.push(byte | 0x80);
    } else {
      out.push(byte);
      break;
    }
  }
  return Uint8Array.from(out);
}

export function bytesEqual(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

export function bytesToHex(bytes) {
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export function hexToBytes(hex) {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    bytes[i / 2] = Number.parseInt(hex.slice(i, i + 2), 16);
  }
  return bytes;
}

export function concatBytes(a, b) {
  const out = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}
