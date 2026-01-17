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

class LineReader {
  constructor(stream) {
    this.reader = stream.getReader();
    this.transcript = [];
    this.buf = new Uint8Array(0);
  }

  async readLine() {
    const line = [];
    while (true) {
      const idx = this.buf.indexOf(10);
      if (idx >= 0) {
        line.push(this.buf.subarray(0, idx));
        this.transcript.push(this.buf.subarray(0, idx + 1));
        this.buf = this.buf.subarray(idx + 1);
        return asciiString(flatten(line));
      }
      if (this.buf.length > 0) {
        line.push(this.buf);
        this.transcript.push(this.buf);
      }
      const next = await this.reader.read();
      if (next.done) {
        this.buf = flatten(line);
        return null;
      }
      this.buf = next.value;
    }
  }

  close() {
    this.reader.releaseLock();
    return { rest: this.buf, transcript: flatten(this.transcript) };
  }
}

function asciiString(bytes) {
  bytes.forEach((byte) => {
    if (byte < 32 || byte > 126) {
      throw new Error("invalid non-ASCII byte in header");
    }
  });
  return new TextDecoder().decode(bytes);
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

function prepend(stream, ...prefixes) {
  return stream.pipeThrough(
    new TransformStream({
      start(controller) {
        for (const prefix of prefixes) {
          controller.enqueue(prefix);
        }
      },
    })
  );
}

function stream(bytes) {
  return new ReadableStream({
    start(controller) {
      controller.enqueue(bytes);
      controller.close();
    },
  });
}

async function read(streamValue, count) {
  const reader = streamValue.getReader();
  const chunks = [];
  let readBytes = 0;
  while (readBytes < count) {
    const { done, value } = await reader.read();
    if (done) {
      throw new Error(`stream ended before reading ${count} bytes`);
    }
    chunks.push(value);
    readBytes += value.length;
  }
  reader.releaseLock();
  const buf = flatten(chunks);
  const data = buf.subarray(0, count);
  const rest = prepend(streamValue, buf.subarray(count));
  return { data, rest };
}

async function readAll(streamValue) {
  if (!(streamValue instanceof ReadableStream)) {
    throw new Error("readAll expects a ReadableStream<Uint8Array>");
  }
  return new Uint8Array(await new Response(streamValue).arrayBuffer());
}

async function parseHeaderScrypt(headerStream) {
  const hdr = new LineReader(headerStream);
  const versionLine = await hdr.readLine();
  if (versionLine !== "age-encryption.org/v1") {
    throw new Error(`invalid version ${versionLine ?? "line"}`);
  }
  const argsLine = await hdr.readLine();
  if (argsLine === null) {
    throw new Error("invalid stanza");
  }
  const args = argsLine.split(" ");
  if (args.length !== 4 || args[0] !== "->" || args[1] !== "scrypt") {
    throw new Error("unsupported recipient");
  }
  const bodyLines = [];
  for (;;) {
    const nextLine = await hdr.readLine();
    if (nextLine === null) {
      throw new Error("invalid stanza");
    }
    const line = decodeBase64NoPad(nextLine);
    if (line.length > 48) {
      throw new Error("invalid stanza");
    }
    bodyLines.push(line);
    if (line.length < 48) {
      break;
    }
  }
  const body = flatten(bodyLines);
  const next = await hdr.readLine();
  if (!next || !next.startsWith("--- ")) {
    throw new Error("invalid header");
  }
  const mac = decodeBase64NoPad(next.slice(4));
  const { rest, transcript } = hdr.close();
  const headerNoMac = transcript.slice(0, transcript.length - 1 - next.length + 3);
  return {
    saltText: args[2],
    logNText: args[3],
    body,
    headerNoMac,
    mac,
    rest: prepend(headerStream, rest),
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
  const label = "age-encryption.org/v1/scrypt";
  const labelAndSalt = new Uint8Array(label.length + 16);
  labelAndSalt.set(textEncoder.encode(label));
  labelAndSalt.set(salt, label.length);
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

function decryptSTREAM(key) {
  const streamNonce = new Uint8Array(12);
  const incNonce = () => {
    for (let i = streamNonce.length - 2; i >= 0; i -= 1) {
      streamNonce[i] += 1;
      if (streamNonce[i] !== 0) break;
    }
  };
  let firstChunk = true;
  const chunkSize = 64 * 1024;
  const overhead = 16;
  const buffer = new Uint8Array(chunkSize + overhead);
  let used = 0;
  return new TransformStream({
    transform(chunk, controller) {
      while (chunk.length > 0) {
        if (used === buffer.length) {
          const decryptedChunk = chacha20poly1305(key, streamNonce).decrypt(buffer);
          controller.enqueue(decryptedChunk);
          incNonce();
          used = 0;
          firstChunk = false;
        }
        const n = Math.min(buffer.length - used, chunk.length);
        buffer.set(chunk.subarray(0, n), used);
        used += n;
        chunk = chunk.subarray(n);
      }
    },
    flush(controller) {
      streamNonce[11] = 1;
      const decryptedChunk = chacha20poly1305(key, streamNonce).decrypt(
        buffer.subarray(0, used)
      );
      if (!firstChunk && decryptedChunk.length === 0) {
        throw new Error("final chunk is empty");
      }
      controller.enqueue(decryptedChunk);
    },
  });
}

export async function decryptAgePassphrase(fileBytes, passphrase) {
  const fileStream = fileBytes instanceof ReadableStream ? fileBytes : stream(fileBytes);
  const header = await parseHeaderScrypt(fileStream);
  const fileKey = unwrapScrypt(passphrase, header.saltText, header.logNText, header.body);
  if (fileKey === null) {
    throw new Error("invalid passphrase");
  }
  const labelHeader = textEncoder.encode("header");
  const hmacKey = hkdf(sha256, fileKey, undefined, labelHeader, 32);
  const mac = hmac(sha256, hmacKey, header.headerNoMac);
  if (!compareBytes(header.mac, mac)) {
    throw new Error("invalid header HMAC");
  }
  const { data: nonce, rest: payload } = await read(header.rest, 16);
  const labelPayload = textEncoder.encode("payload");
  const streamKey = hkdf(sha256, fileKey, nonce, labelPayload, 32);
  const decrypter = decryptSTREAM(streamKey);
  const out = payload.pipeThrough(decrypter);
  return await readAll(out);
}
