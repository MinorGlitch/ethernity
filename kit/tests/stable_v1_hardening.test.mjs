import assert from "node:assert/strict";
import test from "node:test";

import { sha256 } from "@noble/hashes/sha2.js";

import { extractFiles } from "../app/envelope.js";
import {
  ENVELOPE_MAGIC,
  ENVELOPE_VERSION,
  FRAME_MAGIC,
  FRAME_TYPE_AUTH,
  FRAME_TYPE_KEY,
  FRAME_TYPE_MAIN,
  FRAME_VERSION,
  SHARD_KEY_PASSPHRASE,
} from "../app/constants.js";
import { parseAutoPayload, parseAutoShard } from "../app/frames_parse.js";
import { autoRecoverShardSecret } from "../app/shards.js";
import { createInitialState } from "../app/state/initial.js";
import { encodeCbor } from "../lib/cbor.js";
import { crc32 } from "../lib/crc32.js";
import { decodePayloadString, readUvarint } from "../lib/encoding.js";
import { makeZip } from "../lib/zip.js";

if (typeof globalThis.atob !== "function") {
  globalThis.atob = value => Buffer.from(value, "base64").toString("binary");
}

function encodeUvarint(value) {
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

function concatBytes(parts) {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

function toUnpaddedBase64(bytes) {
  return Buffer.from(bytes).toString("base64").replace(/=+$/u, "");
}

function buildEnvelope(manifest, payload) {
  const manifestBytes = encodeCbor(manifest);
  return concatBytes([
    Uint8Array.from(ENVELOPE_MAGIC),
    encodeUvarint(ENVELOPE_VERSION),
    encodeUvarint(manifestBytes.length),
    manifestBytes,
    encodeUvarint(payload.length),
    payload,
  ]);
}

function buildFrame({ frameType, data, index = 0, total = 1, docId = Uint8Array.of(1, 2, 3, 4, 5, 6, 7, 8) }) {
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

function nonCanonicalVersionMap(canonicalBytes) {
  const marker = Uint8Array.of(0x67, 0x76, 0x65, 0x72, 0x73, 0x69, 0x6f, 0x6e, 0x01);
  for (let idx = 0; idx <= canonicalBytes.length - marker.length; idx += 1) {
    let matches = true;
    for (let subIdx = 0; subIdx < marker.length; subIdx += 1) {
      if (canonicalBytes[idx + subIdx] !== marker[subIdx]) {
        matches = false;
        break;
      }
    }
    if (!matches) continue;
    const out = new Uint8Array(canonicalBytes.length + 1);
    out.set(canonicalBytes.slice(0, idx + marker.length - 1), 0);
    out[idx + marker.length - 1] = 0x18;
    out[idx + marker.length] = 0x01;
    out.set(canonicalBytes.slice(idx + marker.length), idx + marker.length + 1);
    return out;
  }
  throw new Error("unable to locate canonical version marker");
}

function buildDirectManifestEntries(files) {
  return files.map(file => [file.path, file.data.length, sha256(file.data), null]);
}

test("extractFiles supports stable-v1 direct manifest entries", async () => {
  const files = [
    { path: "docs/a.txt", data: new Uint8Array([1, 2, 3]) },
    { path: "docs/b.txt", data: new Uint8Array([4, 5]) },
  ];
  const payload = concatBytes(files.map(file => file.data));
  const manifest = {
    version: 1,
    created: 1_700_000_000,
    sealed: true,
    seed: null,
    input_origin: "file",
    input_roots: [],
    payload_codec: "raw",
    path_encoding: "direct",
    files: buildDirectManifestEntries(files),
  };

  const extracted = await extractFiles(buildEnvelope(manifest, payload));
  assert.equal(extracted.files.length, 2);
  assert.equal(extracted.files[0].path, "docs/a.txt");
  assert.deepEqual(Array.from(extracted.files[0].data), [1, 2, 3]);
  assert.equal(extracted.files[1].path, "docs/b.txt");
  assert.deepEqual(Array.from(extracted.files[1].data), [4, 5]);
});

test("extractFiles supports stable-v1 prefix_table manifest entries", async () => {
  const aData = new Uint8Array([10, 11, 12]);
  const bData = new Uint8Array([13]);
  const manifest = {
    version: 1,
    created: 1_700_000_000,
    sealed: true,
    seed: null,
    input_origin: "directory",
    input_roots: ["docs"],
    payload_codec: "raw",
    path_encoding: "prefix_table",
    path_prefixes: ["", "docs", "docs/sub"],
    files: [
      [1, "a.txt", aData.length, sha256(aData), null],
      [2, "b.txt", bData.length, sha256(bData), null],
    ],
  };
  const payload = concatBytes([aData, bData]);

  const extracted = await extractFiles(buildEnvelope(manifest, payload));
  assert.deepEqual(
    extracted.files.map(file => file.path),
    ["docs/a.txt", "docs/sub/b.txt"]
  );
});

test("extractFiles rejects legacy map-style file entries", async () => {
  const data = new Uint8Array([7]);
  const manifest = {
    version: 1,
    created: 1_700_000_000,
    sealed: true,
    seed: null,
    input_origin: "file",
    input_roots: [],
    payload_codec: "raw",
    path_encoding: "direct",
    files: [{ path: "a.txt", size: 1, hash: sha256(data), mtime: null }],
  };
  const envelope = buildEnvelope(manifest, data);
  await assert.rejects(() => extractFiles(envelope), /array encoding/);
});

test("extractFiles rejects non-canonical envelope varints", async () => {
  const envelope = Uint8Array.of(
    ENVELOPE_MAGIC[0],
    ENVELOPE_MAGIC[1],
    0x81,
    0x00,
    0x00,
    0x00
  );
  await assert.rejects(() => extractFiles(envelope), /non-canonical varint/);
});

test("extractFiles rejects non-canonical manifest CBOR", async () => {
  const nonCanonicalManifest = Uint8Array.of(0x18, 0x01);
  const envelope = concatBytes([
    Uint8Array.from(ENVELOPE_MAGIC),
    encodeUvarint(ENVELOPE_VERSION),
    encodeUvarint(nonCanonicalManifest.length),
    nonCanonicalManifest,
    encodeUvarint(0),
  ]);
  await assert.rejects(() => extractFiles(envelope), /canonical CBOR encoding/);
});

test("readUvarint rejects overlong canonical forms", () => {
  assert.throws(() => readUvarint(Uint8Array.of(0x80, 0x00), 0), /non-canonical varint/);
});

test("decodePayloadString accepts only strict unpadded base64", () => {
  assert.equal(decodePayloadString("YQ=="), null);
  assert.equal(decodePayloadString("YWJjZA-_"), null);
  const decoded = decodePayloadString("YQ");
  assert.ok(decoded instanceof Uint8Array);
  assert.deepEqual(Array.from(decoded), [97]);
});

test("parseAutoPayload rejects frames above MAX_MAIN_FRAME_TOTAL", () => {
  const state = createInitialState();
  const frame = buildFrame({ frameType: FRAME_TYPE_MAIN, data: Uint8Array.of(1), total: 5_000 });
  const payload = toUnpaddedBase64(frame);
  assert.throws(
    () => parseAutoPayload(state, payload),
    /input is neither valid QR payloads nor valid fallback text/
  );
});

test("parseAutoPayload rejects non-canonical AUTH CBOR payload", () => {
  const authPayload = {
    version: 1,
    hash: new Uint8Array(32),
    pub: new Uint8Array(32),
    sig: new Uint8Array(64),
  };
  const nonCanonical = nonCanonicalVersionMap(encodeCbor(authPayload));
  const frame = buildFrame({ frameType: FRAME_TYPE_AUTH, data: nonCanonical });
  const state = createInitialState();

  const added = parseAutoPayload(state, toUnpaddedBase64(frame));
  assert.equal(added, 1);
  assert.equal(state.authErrors, 1);
  assert.equal(state.authPayload, null);
});

test("parseAutoShard rejects structurally invalid shard payload share lengths", () => {
  const shardPayload = {
    version: 1,
    type: SHARD_KEY_PASSPHRASE,
    threshold: 2,
    share_count: 3,
    share_index: 1,
    length: 15,
    share: new Uint8Array(15),
    hash: new Uint8Array(32),
    pub: new Uint8Array(32),
    sig: new Uint8Array(64),
  };
  const frame = buildFrame({ frameType: FRAME_TYPE_KEY, data: encodeCbor(shardPayload) });
  const state = createInitialState();

  const added = parseAutoShard(state, toUnpaddedBase64(frame));
  assert.equal(added, 1);
  assert.equal(state.shardErrors, 1);
  assert.equal(state.shardFrames.size, 0);
});

test("parseAutoShard rejects non-canonical shard CBOR payload", () => {
  const shardPayload = {
    version: 1,
    type: SHARD_KEY_PASSPHRASE,
    threshold: 2,
    share_count: 3,
    share_index: 1,
    length: 1,
    share: new Uint8Array(16),
    hash: new Uint8Array(32),
    pub: new Uint8Array(32),
    sig: new Uint8Array(64),
  };
  const nonCanonical = nonCanonicalVersionMap(encodeCbor(shardPayload));
  const frame = buildFrame({ frameType: FRAME_TYPE_KEY, data: nonCanonical });
  const state = createInitialState();

  const added = parseAutoShard(state, toUnpaddedBase64(frame));
  assert.equal(added, 1);
  assert.equal(state.shardErrors, 1);
  assert.equal(state.shardFrames.size, 0);
});

test("autoRecoverShardSecret rejects shard/doc hash mismatch before reconstruction", () => {
  const state = createInitialState();
  state.total = 1;
  state.mainFrames.set(0, { data: Uint8Array.of(9, 8, 7) });
  state.shardThreshold = 1;
  state.shardDocHashHex = "00".repeat(32);
  state.shardFrames.set(1, {
    version: 1,
    keyType: SHARD_KEY_PASSPHRASE,
    threshold: 1,
    shareCount: 1,
    shareIndex: 1,
    secretLen: 1,
    share: new Uint8Array(16),
    docHash: new Uint8Array(32),
    signPub: new Uint8Array(32),
    signature: new Uint8Array(64),
  });

  const recovered = autoRecoverShardSecret(state);
  assert.equal(recovered, false);
  assert.equal(state.recoveredShardSecret, "");
  assert.equal(state.shardStatus.type, "error");
  assert.match(state.shardStatus.lines.join("\n"), /does not match collected ciphertext/);
});

test("makeZip rejects unsafe traversal paths", () => {
  assert.throws(
    () => makeZip([{ path: "../escape.txt", data: Uint8Array.of(1, 2, 3) }]),
    /must not contain '\.' or '\.\.'/
  );
});
