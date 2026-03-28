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

import { hmac } from "@noble/hashes/hmac.js";
import { hkdf } from "@noble/hashes/hkdf.js";
import { sha256 } from "@noble/hashes/sha2.js";
import { scrypt } from "@noble/hashes/scrypt.js";
import { chacha20poly1305 } from "@noble/ciphers/chacha.js";

const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder();
const LABEL_SCRYPT = textEncoder.encode("age-encryption.org/v1/scrypt");
const LABEL_HEADER = textEncoder.encode("header");
const LABEL_PAYLOAD = textEncoder.encode("payload");
const CHUNK_SIZE = 64 * 1024;
const TAG_SIZE = 16;
const STREAM_BLOCK_BYTES = CHUNK_SIZE + TAG_SIZE;

function decodeBase64NoPad(text) {
  const cleaned = text.trim();
  const pad = cleaned.length % 4;
  if (pad === 1) {
    throw new Error("invalid base64");
  }
  const padded = pad ? `${cleaned}${"=".repeat(4 - pad)}` : cleaned;
  let binary;
  try {
    binary = atob(padded);
  } catch {
    throw new Error("invalid base64");
  }
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function asciiString(bytes) {
  bytes.forEach((byte) => {
    if (byte < 32 || byte > 126) {
      throw new Error("invalid non-ASCII byte in header");
    }
  });
  return textDecoder.decode(bytes);
}

function flatten(chunks) {
  const len = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const out = new Uint8Array(len);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

function readAsciiLine(bytes, offset) {
  if (offset >= bytes.length) {
    return null;
  }
  const lf = bytes.indexOf(10, offset);
  if (lf < 0) {
    return null;
  }
  return {
    text: asciiString(bytes.subarray(offset, lf)),
    lineStart: offset,
    nextOffset: lf + 1,
  };
}

function parseHeaderScrypt(fileBytes) {
  let offset = 0;
  const versionLine = readAsciiLine(fileBytes, offset);
  if (versionLine?.text !== "age-encryption.org/v1") {
    throw new Error(`invalid version ${versionLine?.text ?? "line"}`);
  }
  offset = versionLine.nextOffset;
  const argsLine = readAsciiLine(fileBytes, offset);
  if (argsLine === null) {
    throw new Error("invalid stanza");
  }
  offset = argsLine.nextOffset;
  const args = argsLine.text.split(" ");
  if (args.length !== 4 || args[0] !== "->" || args[1] !== "scrypt") {
    throw new Error("unsupported recipient");
  }
  const bodyLines = [];
  for (;;) {
    const nextLine = readAsciiLine(fileBytes, offset);
    if (nextLine === null) {
      throw new Error("invalid stanza");
    }
    offset = nextLine.nextOffset;
    const line = decodeBase64NoPad(nextLine.text);
    if (line.length > 48) {
      throw new Error("invalid stanza");
    }
    bodyLines.push(line);
    if (line.length < 48) {
      break;
    }
  }
  const body = flatten(bodyLines);
  const macLine = readAsciiLine(fileBytes, offset);
  if (!macLine || !macLine.text.startsWith("--- ")) {
    throw new Error("invalid header");
  }
  const mac = decodeBase64NoPad(macLine.text.slice(4));
  const headerNoMac = fileBytes.subarray(0, macLine.lineStart + 3);
  return {
    saltText: args[2],
    logNText: args[3],
    body,
    headerNoMac,
    mac,
    payloadOffset: macLine.nextOffset,
  };
}

function decryptFileKey(body, key) {
  if (body.length !== 32) {
    throw new Error("invalid stanza");
  }
  const nonce = new Uint8Array(12);
  try {
    return chacha20poly1305(key, nonce).decrypt(body);
  } catch {
    return null;
  }
}

function unwrapScrypt(passphrase, saltText, logNText, body) {
  if (!/^[1-9][0-9]*$/.test(logNText)) {
    throw new Error("invalid scrypt stanza");
  }
  const salt = decodeBase64NoPad(saltText);
  if (salt.length !== 16) {
    throw new Error("invalid scrypt stanza");
  }
  const logN = Number(logNText);
  if (logN > 20) {
    throw new Error("scrypt work factor is too high");
  }
  const labelAndSalt = new Uint8Array(LABEL_SCRYPT.length + 16);
  labelAndSalt.set(LABEL_SCRYPT);
  labelAndSalt.set(salt, LABEL_SCRYPT.length);
  const key = scrypt(passphrase, labelAndSalt, { N: 2 ** logN, r: 8, p: 1, dkLen: 32 });
  return decryptFileKey(body, key);
}

function compareBytes(a, b) {
  if (a.length !== b.length) {
    return false;
  }
  let acc = 0;
  for (let i = 0; i < a.length; i += 1) {
    acc |= a[i] ^ b[i];
  }
  return acc === 0;
}

function decryptPayloadBytes(key, payloadBytes) {
  const streamNonce = new Uint8Array(12);
  const incNonce = () => {
    for (let i = streamNonce.length - 2; i >= 0; i -= 1) {
      streamNonce[i] += 1;
      if (streamNonce[i] !== 0) break;
    }
  };
  let firstChunk = true;
  let offset = 0;
  const out = [];
  while (payloadBytes.length - offset > STREAM_BLOCK_BYTES) {
    const decryptedChunk = chacha20poly1305(key, streamNonce).decrypt(
      payloadBytes.subarray(offset, offset + STREAM_BLOCK_BYTES),
    );
    out.push(decryptedChunk);
    incNonce();
    firstChunk = false;
    offset += STREAM_BLOCK_BYTES;
  }
  streamNonce[11] = 1;
  const decryptedChunk = chacha20poly1305(key, streamNonce).decrypt(payloadBytes.subarray(offset));
  if (!firstChunk && decryptedChunk.length === 0) {
    throw new Error("final chunk is empty");
  }
  out.push(decryptedChunk);
  return flatten(out);
}

export async function decryptAgePassphrase(fileBytes, passphrase) {
  const bytes =
    fileBytes instanceof Uint8Array ? fileBytes : new Uint8Array(fileBytes.buffer ?? fileBytes);
  const header = parseHeaderScrypt(bytes);
  const fileKey = unwrapScrypt(passphrase, header.saltText, header.logNText, header.body);
  if (fileKey === null) {
    throw new Error("invalid passphrase");
  }
  const hmacKey = hkdf(sha256, fileKey, undefined, LABEL_HEADER, 32);
  const mac = hmac(sha256, hmacKey, header.headerNoMac);
  if (!compareBytes(header.mac, mac)) {
    throw new Error("invalid header HMAC");
  }
  const nonce = bytes.subarray(header.payloadOffset, header.payloadOffset + 16);
  if (nonce.length !== 16) {
    throw new Error("stream ended before reading 16 bytes");
  }
  const streamKey = hkdf(sha256, fileKey, nonce, LABEL_PAYLOAD, 32);
  const payload = bytes.subarray(header.payloadOffset + 16);
  return decryptPayloadBytes(streamKey, payload);
}
