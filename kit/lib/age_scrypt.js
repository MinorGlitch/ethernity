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

import { concatByteParts } from "./bytes.js";
import { hmac } from "@noble/hashes/hmac.js";
import { hkdf } from "@noble/hashes/hkdf.js";
import { sha256 } from "@noble/hashes/sha2.js";
import { scrypt } from "@noble/hashes/scrypt.js";
import { chacha20poly1305 } from "@noble/ciphers/chacha.js";
import { RecoveryError, asRecoveryError } from "./errors.js";

const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder();
const LABEL_SCRYPT = textEncoder.encode("age-encryption.org/v1/scrypt");
const LABEL_HEADER = textEncoder.encode("header");
const LABEL_PAYLOAD = textEncoder.encode("payload");
const CHUNK_SIZE = 64 * 1024;
const TAG_SIZE = 16;
const STREAM_BLOCK_BYTES = CHUNK_SIZE + TAG_SIZE;
export const MAX_BROWSER_AGE_SCRYPT_LOG_N = 20;
export const MAX_SCRYPT_LOG_N = MAX_BROWSER_AGE_SCRYPT_LOG_N;
export const MAX_RECOVERY_SCRYPT_WORK = 8 * 2 ** MAX_BROWSER_AGE_SCRYPT_LOG_N;
export const SCRYPT_WORKER_UNAVAILABLE =
  "This browser cannot safely run the required scrypt work. Use the Ethernity desktop app to recover this backup.";

function decodeBase64NoPad(text) {
  const cleaned = text.trim();
  const pad = cleaned.length % 4;
  if (pad === 1) {
    throw new RecoveryError("DOCUMENT_INVALID", "invalid base64");
  }
  const padded = pad ? `${cleaned}${"=".repeat(4 - pad)}` : cleaned;
  let binary;
  try {
    binary = atob(padded);
  } catch {
    throw new RecoveryError("DOCUMENT_INVALID", "invalid base64");
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
      throw new RecoveryError("DOCUMENT_INVALID", "invalid non-ASCII byte in header");
    }
  });
  return textDecoder.decode(bytes);
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
    throw new RecoveryError("DOCUMENT_INVALID", `invalid version ${versionLine?.text ?? "line"}`);
  }
  offset = versionLine.nextOffset;
  const argsLine = readAsciiLine(fileBytes, offset);
  if (argsLine === null) {
    throw new RecoveryError("DOCUMENT_INVALID", "invalid stanza");
  }
  offset = argsLine.nextOffset;
  const args = argsLine.text.split(" ");
  if (args.length !== 4 || args[0] !== "->" || args[1] !== "scrypt") {
    throw new RecoveryError("DOCUMENT_INVALID", "unsupported recipient");
  }
  const bodyLines = [];
  for (;;) {
    const nextLine = readAsciiLine(fileBytes, offset);
    if (nextLine === null) {
      throw new RecoveryError("DOCUMENT_INVALID", "invalid stanza");
    }
    offset = nextLine.nextOffset;
    const line = decodeBase64NoPad(nextLine.text);
    if (line.length > 48) {
      throw new RecoveryError("DOCUMENT_INVALID", "invalid stanza");
    }
    bodyLines.push(line);
    if (line.length < 48) {
      break;
    }
  }
  const body = concatByteParts(bodyLines);
  const macLine = readAsciiLine(fileBytes, offset);
  if (!macLine?.text.startsWith("--- ")) {
    throw new RecoveryError("DOCUMENT_INVALID", "invalid header");
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
    throw new RecoveryError("DOCUMENT_INVALID", "invalid stanza");
  }
  const nonce = new Uint8Array(12);
  try {
    return chacha20poly1305(key, nonce).decrypt(body);
  } catch {
    return null;
  }
}

function parseSupportedScryptProfile(saltText, logNText) {
  if (!/^[1-9][0-9]*$/.test(logNText)) {
    throw new RecoveryError("DOCUMENT_INVALID", "invalid scrypt stanza");
  }
  const salt = decodeBase64NoPad(saltText);
  if (salt.length !== 16) {
    throw new RecoveryError("DOCUMENT_INVALID", "invalid scrypt stanza");
  }
  const logN = Number(logNText);
  if (!Number.isSafeInteger(logN) || logN < 1 || logN > MAX_SCRYPT_LOG_N) {
    throw new RecoveryError(
      "RECOVERY_RESOURCE_LIMIT",
      `scrypt work factor must be between 1 and ${MAX_SCRYPT_LOG_N}`,
    );
  }
  const labelAndSalt = new Uint8Array(LABEL_SCRYPT.length + 16);
  labelAndSalt.set(LABEL_SCRYPT);
  labelAndSalt.set(salt, LABEL_SCRYPT.length);
  const work = 2 ** logN;
  return {
    labelAndSalt,
    logN,
    work,
    memoryBytes: 128 * 8 * (work + 2),
  };
}

async function unwrapScrypt(passphrase, saltText, logNText, body, options) {
  const profile = parseSupportedScryptProfile(saltText, logNText);
  const key = await deriveScryptKey(passphrase, profile, options);
  return decryptFileKey(body, key);
}

function deriveScryptKey(passphrase, profile, { signal, onScrypt } = {}) {
  if (typeof window !== "undefined") {
    throw new RecoveryError("SCRYPT_UNAVAILABLE", SCRYPT_WORKER_UNAVAILABLE);
  }
  if (signal?.aborted) {
    throw new RecoveryError("CANCELLED", "scrypt operation was cancelled");
  }
  onScrypt?.(true);
  try {
    return scrypt(passphrase, profile.labelAndSalt, {
      N: profile.work,
      r: 8,
      p: 1,
      dkLen: 32,
      maxmem: profile.memoryBytes,
    });
  } catch {
    throw new RecoveryError("SCRYPT_UNAVAILABLE", SCRYPT_WORKER_UNAVAILABLE);
  } finally {
    onScrypt?.(false);
  }
}

export function inspectAgeScryptWork(fileBytes) {
  const bytes =
    fileBytes instanceof Uint8Array ? fileBytes : new Uint8Array(fileBytes.buffer ?? fileBytes);
  const header = parseHeaderScrypt(bytes);
  const profile = parseSupportedScryptProfile(header.saltText, header.logNText);
  return { logN: profile.logN, work: profile.work, memoryBytes: profile.memoryBytes };
}

export function preflightAgeScryptBatch(fileBytesList) {
  if (!Array.isArray(fileBytesList) || !fileBytesList.length) {
    throw new RecoveryError(
      "INPUT_REQUIRED",
      "scrypt preflight requires at least one encrypted document",
    );
  }
  let totalWork = 0;
  let peakMemoryBytes = 0;
  const errors = [];
  const profiles = fileBytesList.map((fileBytes) => {
    try {
      const profile = inspectAgeScryptWork(fileBytes);
      totalWork += profile.work;
      peakMemoryBytes = Math.max(peakMemoryBytes, profile.memoryBytes);
      errors.push(null);
      return profile;
    } catch (err) {
      errors.push(asRecoveryError(err));
      return null;
    }
  });
  if (totalWork > MAX_RECOVERY_SCRYPT_WORK) {
    throw new RecoveryError(
      "RECOVERY_RESOURCE_LIMIT",
      `cumulative scrypt work exceeds the recovery work limit (${MAX_RECOVERY_SCRYPT_WORK})`,
    );
  }
  return {
    profiles,
    errors,
    totalWork,
    peakMemoryBytes,
  };
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
  return concatByteParts(out);
}

export async function decryptAgePassphrase(fileBytes, passphrase, options = {}) {
  const bytes =
    fileBytes instanceof Uint8Array ? fileBytes : new Uint8Array(fileBytes.buffer ?? fileBytes);
  const header = parseHeaderScrypt(bytes);
  const fileKey = await unwrapScrypt(
    passphrase,
    header.saltText,
    header.logNText,
    header.body,
    options,
  );
  if (fileKey === null) {
    throw new RecoveryError("PASSPHRASE_AUTH_FAILED", "invalid passphrase");
  }
  const hmacKey = hkdf(sha256, fileKey, undefined, LABEL_HEADER, 32);
  const mac = hmac(sha256, hmacKey, header.headerNoMac);
  if (!compareBytes(header.mac, mac)) {
    throw new RecoveryError("DOCUMENT_INTEGRITY_FAILED", "invalid header HMAC");
  }
  const nonce = bytes.subarray(header.payloadOffset, header.payloadOffset + 16);
  if (nonce.length !== 16) {
    throw new RecoveryError("DOCUMENT_INVALID", "stream ended before reading 16 bytes");
  }
  const streamKey = hkdf(sha256, fileKey, nonce, LABEL_PAYLOAD, 32);
  const payload = bytes.subarray(header.payloadOffset + 16);
  try {
    return decryptPayloadBytes(streamKey, payload);
  } catch (error) {
    throw asRecoveryError(error, "DOCUMENT_INTEGRITY_FAILED");
  }
}

decryptAgePassphrase.preflightBatch = preflightAgeScryptBatch;
