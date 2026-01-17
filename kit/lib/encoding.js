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

const ZBASE32_ALPHABET = "ybndrfg8ejkmcpqxot1uwisza345h769";

export function isBase64(text) {
  return /^[A-Za-z0-9+/=_-]+$/.test(text);
}

export function decodePayloadString(text) {
  const cleaned = text.replace(/\s+/g, "");
  if (!cleaned) return null;
  if (isBase64(cleaned)) {
    try {
      const normalized = cleaned.replaceAll("-", "+").replaceAll("_", "/");
      const padded = normalized + "===".slice((normalized.length + 3) % 4);
      const binary = atob(padded);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) {
        bytes[i] = binary.codePointAt(i);
      }
      return bytes;
    } catch (err) {
      return null;
    }
  }
  return null;
}

export function decodeZBase32(text) {
  let bits = 0;
  let bitCount = 0;
  const out = [];
  for (const ch of text) {
    if (ch === "-" || /\s/.test(ch)) continue;
    const idx = ZBASE32_ALPHABET.indexOf(ch.toLowerCase());
    if (idx === -1) throw new Error(`invalid z-base-32 character: ${ch}`);
    bits = (bits << 5) | idx;
    bitCount += 5;
    if (bitCount >= 8) {
      const shift = bitCount - 8;
      out.push((bits >> shift) & 0xff);
      bitCount -= 8;
      bits &= (1 << bitCount) - 1;
    }
  }
  return new Uint8Array(out);
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
  let value = 0;
  let shift = 0;
  let idx = offset;
  while (idx < bytes.length) {
    const byte = bytes[idx++];
    const part = byte & 0x7f;
    value += part * Math.pow(2, shift);
    if ((byte & 0x80) === 0) {
      return { value, offset: idx };
    }
    shift += 7;
    if (shift > 53) throw new Error("varint too large");
  }
  throw new Error("truncated varint");
}

export function encodeUvarint(value) {
  if (!Number.isFinite(value) || value < 0 || Math.floor(value) !== value) {
    throw new Error("varint value must be a non-negative integer");
  }
  let v = value;
  const out = [];
  while (v >= 0x80) {
    out.push((v % 128) | 0x80);
    v = Math.floor(v / 128);
  }
  out.push(v);
  return new Uint8Array(out);
}

export function bytesEqual(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

export function bytesToHex(bytes) {
  return Array.from(bytes).map(b => b.toString(16).padStart(2, "0")).join("");
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

export { ZBASE32_ALPHABET };
