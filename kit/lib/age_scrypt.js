import { hmac } from "@noble/hashes/hmac.js";
import { hkdf } from "@noble/hashes/hkdf.js";
import { sha256 } from "@noble/hashes/sha2.js";
import { scrypt } from "@noble/hashes/scrypt.js";
import { chacha20poly1305 } from "@noble/ciphers/chacha.js";
import { base64nopad } from "@scure/base";

const textEncoder = new TextEncoder();

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

class Stanza {
  constructor(args, body) {
    this.args = args;
    this.body = body;
  }
}

async function parseNextStanza(hdr) {
  const argsLine = await hdr.readLine();
  if (argsLine === null) {
    throw new Error("invalid stanza");
  }
  const args = argsLine.split(" ");
  if (args.length < 2 || args.shift() !== "->") {
    return { next: argsLine };
  }
  for (const arg of args) {
    if (arg.length === 0) {
      throw new Error("invalid stanza");
    }
  }
  const bodyLines = [];
  for (;;) {
    const nextLine = await hdr.readLine();
    if (nextLine === null) {
      throw new Error("invalid stanza");
    }
    const line = base64nopad.decode(nextLine);
    if (line.length > 48) {
      throw new Error("invalid stanza");
    }
    bodyLines.push(line);
    if (line.length < 48) {
      break;
    }
  }
  const body = flatten(bodyLines);
  return { stanza: new Stanza(args, body) };
}

async function parseHeader(headerStream) {
  const hdr = new LineReader(headerStream);
  const versionLine = await hdr.readLine();
  if (versionLine !== "age-encryption.org/v1") {
    throw new Error(`invalid version ${versionLine ?? "line"}`);
  }
  const stanzas = [];
  for (;;) {
    const { stanza, next } = await parseNextStanza(hdr);
    if (stanza !== undefined) {
      stanzas.push(stanza);
      continue;
    }
    if (!next.startsWith("--- ")) {
      throw new Error("invalid header");
    }
    const mac = base64nopad.decode(next.slice(4));
    const { rest, transcript } = hdr.close();
    const headerNoMac = transcript.slice(0, transcript.length - 1 - next.length + 3);
    return {
      stanzas,
      headerNoMac,
      mac,
      headerSize: transcript.length,
      rest: prepend(headerStream, rest),
    };
  }
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

function unwrapScrypt(passphrase, stanzas) {
  for (const stanza of stanzas) {
    if (stanza.args.length < 1 || stanza.args[0] !== "scrypt") {
      continue;
    }
    if (stanzas.length !== 1) {
      throw new Error("scrypt recipient is not the only one in the header");
    }
    if (stanza.args.length !== 3) {
      throw new Error("invalid scrypt stanza");
    }
    if (!/^[1-9][0-9]*$/.test(stanza.args[2])) {
      throw new Error("invalid scrypt stanza");
    }
    const salt = base64nopad.decode(stanza.args[1]);
    if (salt.length !== 16) {
      throw new Error("invalid scrypt stanza");
    }
    const logN = Number(stanza.args[2]);
    if (logN > 20) {
      throw new Error("scrypt work factor is too high");
    }
    const label = "age-encryption.org/v1/scrypt";
    const labelAndSalt = new Uint8Array(label.length + 16);
    labelAndSalt.set(textEncoder.encode(label));
    labelAndSalt.set(salt, label.length);
    const key = scrypt(passphrase, labelAndSalt, { N: 2 ** logN, r: 8, p: 1, dkLen: 32 });
    const fileKey = decryptFileKey(stanza.body, key);
    if (fileKey !== null) {
      return fileKey;
    }
  }
  return null;
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
  const header = await parseHeader(fileStream);
  const fileKey = unwrapScrypt(passphrase, header.stanzas);
  if (fileKey === null) {
    throw new Error("no identity matched any of the file's recipients");
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
