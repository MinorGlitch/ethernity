import assert from "node:assert/strict";
import test from "node:test";
import { gzipSync } from "node:zlib";

import { sha256 } from "@noble/hashes/sha2.js";

import { extractFiles } from "../app/envelope.js";
import {
  ENVELOPE_MAGIC,
  ENVELOPE_VERSION,
  FRAME_TYPE_AUTH,
  FRAME_TYPE_KEY,
  FRAME_TYPE_MAIN,
  SHARD_KEY_PASSPHRASE,
} from "../app/constants.js";
import { parseAutoPayload, parseAutoShard } from "../app/frames_parse.js";
import { createInitialState } from "../app/state/initial.js";
import { encodeCbor } from "../lib/cbor.js";
import { buildFrame, concatBytes, encodeUvarint, ensureAtob, toUnpaddedBase64 } from "./test_helpers.mjs";

ensureAtob();

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

function validManifest(payload = Uint8Array.of(1)) {
  return {
    version: 1,
    created: 1_700_000_000,
    sealed: true,
    seed: null,
    input_origin: "file",
    input_roots: [],
    path_encoding: "direct",
    files: [["a.txt", payload.length, sha256(payload), null]],
  };
}

function gzipPayload(payload) {
  return new Uint8Array(gzipSync(Buffer.from(payload), { level: 9, mtime: 0 }));
}

test("manifest decoder rejects invalid stable-v1 structures", async () => {
  const payload = Uint8Array.of(1, 2, 3);
  const cases = [
    {
      name: "manifest must be map",
      envelope: buildEnvelope(7, payload),
      error: /manifest must be a map/,
    },
    {
      name: "required key missing",
      envelope: (() => {
        const manifest = validManifest(payload);
        delete manifest.created;
        return buildEnvelope(manifest, payload);
      })(),
      error: /manifest created is required/,
    },
    {
      name: "version type",
      envelope: buildEnvelope({ ...validManifest(payload), version: "1" }, payload),
      error: /manifest version must be an int/,
    },
    {
      name: "unsupported version",
      envelope: buildEnvelope({ ...validManifest(payload), version: 9 }, payload),
      error: /unsupported manifest version/,
    },
    {
      name: "created type",
      envelope: buildEnvelope({ ...validManifest(payload), created: "now" }, payload),
      error: /manifest created must be a number/,
    },
    {
      name: "sealed seed mismatch",
      envelope: buildEnvelope({ ...validManifest(payload), seed: new Uint8Array(32) }, payload),
      error: /seed must be null for sealed manifests/,
    },
    {
      name: "unsealed missing seed",
      envelope: buildEnvelope({ ...validManifest(payload), sealed: false, seed: null }, payload),
      error: /seed must be 32 bytes for unsealed manifests/,
    },
    {
      name: "input origin invalid",
      envelope: buildEnvelope({ ...validManifest(payload), input_origin: "archive" }, payload),
      error: /input_origin must be one of/,
    },
    {
      name: "file input roots must be empty",
      envelope: buildEnvelope({ ...validManifest(payload), input_roots: ["root"] }, payload),
      error: /input_roots must be empty when input_origin is file/,
    },
    {
      name: "directory requires roots",
      envelope: buildEnvelope(
        { ...validManifest(payload), input_origin: "directory", input_roots: [] },
        payload
      ),
      error: /input_roots must be non-empty/,
    },
    {
      name: "path encoding invalid",
      envelope: buildEnvelope({ ...validManifest(payload), path_encoding: "legacy" }, payload),
      error: /path_encoding must be one of/,
    },
    {
      name: "files required",
      envelope: buildEnvelope({ ...validManifest(payload), files: [] }, payload),
      error: /manifest files are required/,
    },
    {
      name: "duplicate paths",
      envelope: buildEnvelope(
        {
          ...validManifest(payload),
          files: [
            ["a.txt", 1, sha256(Uint8Array.of(1)), null],
            ["a.txt", 2, sha256(Uint8Array.of(2, 3)), null],
          ],
        },
        Uint8Array.of(1, 2, 3)
      ),
      error: /duplicate manifest file path/,
    },
    {
      name: "prefix table requires prefixes",
      envelope: buildEnvelope({ ...validManifest(payload), path_encoding: "prefix_table" }, payload),
      error: /path_prefixes is required/,
    },
    {
      name: "prefix table index out of range",
      envelope: buildEnvelope(
        {
          ...validManifest(payload),
          path_encoding: "prefix_table",
          path_prefixes: ["", "root"],
          files: [[4, "a.txt", payload.length, sha256(payload), null]],
        },
        payload
      ),
      error: /prefix_index out of range/,
    },
    {
      name: "entry hash must be bytes",
      envelope: buildEnvelope(
        {
          ...validManifest(payload),
          files: [["a.txt", payload.length, Uint8Array.of(1), null]],
        },
        payload
      ),
      error: /file hash must be 32 bytes/,
    },
    {
      name: "entry mtime type",
      envelope: buildEnvelope(
        {
          ...validManifest(payload),
          files: [["a.txt", payload.length, sha256(payload), "123"]],
        },
        payload
      ),
      error: /file mtime must be an int/,
    },
  ];

  for (const testCase of cases) {
    await assert.rejects(() => extractFiles(testCase.envelope), testCase.error, testCase.name);
  }
});

test("envelope decoder rejects framing-length and hash mismatches", async () => {
  const payload = Uint8Array.of(1, 2, 3);
  const manifest = validManifest(payload);
  const manifestBytes = encodeCbor(manifest);

  const badMagic = buildEnvelope(manifest, payload);
  badMagic[0] = 0;
  await assert.rejects(() => extractFiles(badMagic), /invalid envelope magic/);

  const truncatedManifest = concatBytes([
    Uint8Array.from(ENVELOPE_MAGIC),
    encodeUvarint(ENVELOPE_VERSION),
    encodeUvarint(manifestBytes.length + 10),
    manifestBytes,
    encodeUvarint(payload.length),
    payload,
  ]);
  await assert.rejects(() => extractFiles(truncatedManifest), /truncated manifest/);

  const payloadMismatch = concatBytes([
    Uint8Array.from(ENVELOPE_MAGIC),
    encodeUvarint(ENVELOPE_VERSION),
    encodeUvarint(manifestBytes.length),
    manifestBytes,
    encodeUvarint(payload.length + 1),
    payload,
  ]);
  await assert.rejects(() => extractFiles(payloadMismatch), /payload length mismatch/);

  const digestMismatchManifest = {
    ...manifest,
    files: [["a.txt", payload.length, sha256(Uint8Array.of(9, 9, 9)), null]],
  };
  await assert.rejects(
    () => extractFiles(buildEnvelope(digestMismatchManifest, payload)),
    /sha256 mismatch/
  );

  const extraPayload = Uint8Array.of(1, 2, 3, 4);
  await assert.rejects(
    () => extractFiles(buildEnvelope(validManifest(payload), extraPayload)),
    /payload length does not match manifest sizes/
  );
});

test("extractFiles normalizes gzip-coded payloads", async () => {
  const rawPayload = Uint8Array.of(1, 2, 3, 4, 5, 6, 7, 8);
  const compressedPayload = gzipPayload(rawPayload);
  const manifest = {
    ...validManifest(rawPayload),
    payload_codec: "gzip",
    payload_raw_len: rawPayload.length,
  };
  const extracted = await extractFiles(buildEnvelope(manifest, compressedPayload));
  assert.equal(extracted.files.length, 1);
  assert.equal(extracted.files[0].path, "a.txt");
  assert.deepEqual(extracted.files[0].data, rawPayload);
});

test("extractFiles rejects gzip payload_raw_len mismatch", async () => {
  const rawPayload = Uint8Array.of(1, 2, 3, 4, 5, 6, 7, 8);
  const compressedPayload = gzipPayload(rawPayload);
  const manifest = {
    ...validManifest(rawPayload),
    payload_codec: "gzip",
    payload_raw_len: rawPayload.length + 1,
  };
  await assert.rejects(
    () => extractFiles(buildEnvelope(manifest, compressedPayload)),
    /payload_raw_len must match sum of manifest file sizes/
  );
});

test("extractFiles rejects unsupported manifest payload codecs", async () => {
  const payload = Uint8Array.of(1, 2, 3);
  const manifest = {
    ...validManifest(payload),
    payload_codec: "brotli",
  };
  await assert.rejects(
    () => extractFiles(buildEnvelope(manifest, payload)),
    /payload_codec must be one of: raw, gzip/
  );
});

function shardPayload(overrides = {}) {
  return {
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
    ...overrides,
  };
}

test("frame parser rejects invalid auth/key frame invariants", () => {
  const authBad = toUnpaddedBase64(
    buildFrame({ frameType: FRAME_TYPE_AUTH, data: encodeCbor({ version: 1, hash: new Uint8Array(32), pub: new Uint8Array(32), sig: new Uint8Array(64) }), index: 1, total: 2 })
  );
  assert.throws(
    () => parseAutoPayload(createInitialState(), authBad),
    /neither valid QR payloads nor valid fallback text/
  );

  const keyBad = toUnpaddedBase64(
    buildFrame({ frameType: FRAME_TYPE_KEY, data: encodeCbor(shardPayload()), index: 0, total: 2 })
  );
  assert.throws(
    () => parseAutoShard(createInitialState(), keyBad),
    /neither valid shard payloads nor valid fallback text/
  );

  const mainBad = toUnpaddedBase64(
    buildFrame({ frameType: FRAME_TYPE_MAIN, data: Uint8Array.of(1), index: 1, total: 1 })
  );
  assert.throws(
    () => parseAutoPayload(createInitialState(), mainBad),
    /neither valid QR payloads nor valid fallback text/
  );
});
