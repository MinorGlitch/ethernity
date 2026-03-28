import { DOC_ID_LEN, FRAME_MAGIC, FRAME_VERSION } from "../app/constants.js";
import { crc32 } from "../lib/crc32.js";

const ZBASE32_ALPHABET = "ybndrfg8ejkmcpqxot1uwisza345h769";

export function ensureAtob() {
  if (typeof globalThis.atob !== "function") {
    globalThis.atob = (value) => Buffer.from(value, "base64").toString("binary");
  }
}

export function encodeUvarint(value) {
  let current = BigInt(value);
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

export function concatBytes(parts) {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

export function toUnpaddedBase64(bytes) {
  return Buffer.from(bytes).toString("base64").replace(/=+$/u, "");
}

export function encodeZBase32(bytes) {
  let bits = 0;
  let bitCount = 0;
  let out = "";
  for (const byte of bytes) {
    bits = bits * 256 + byte;
    bitCount += 8;
    while (bitCount >= 5) {
      const shift = bitCount - 5;
      const idx = Math.floor(bits / 2 ** shift) & 0x1f;
      out += ZBASE32_ALPHABET[idx];
      bitCount -= 5;
      bits &= 2 ** bitCount - 1;
    }
  }
  if (bitCount > 0) {
    out += ZBASE32_ALPHABET[(bits * 2 ** (5 - bitCount)) & 0x1f];
  }
  return out;
}

export function buildFrame({
  frameType,
  data,
  index = 0,
  total = 1,
  docId = Uint8Array.from(Array.from({ length: DOC_ID_LEN }, (_, idx) => idx + 1)),
}) {
  const body = concatBytes([
    Uint8Array.from(FRAME_MAGIC),
    encodeUvarint(FRAME_VERSION),
    Uint8Array.of(frameType),
    docId,
    encodeUvarint(index),
    encodeUvarint(total),
    encodeUvarint(data.length),
    data,
  ]);
  const crc = crc32(body);
  return concatBytes([
    body,
    Uint8Array.of((crc >>> 24) & 0xff, (crc >>> 16) & 0xff, (crc >>> 8) & 0xff, crc & 0xff),
  ]);
}

export function mutateFrameCrc(frame) {
  const out = frame.slice();
  out[out.length - 1] ^= 0x01;
  return out;
}
