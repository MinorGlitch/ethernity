import assert from "node:assert/strict";
import test from "node:test";
import { gzipSync } from "node:zlib";

import { sha256 } from "@noble/hashes/sha2.js";

import { extractFiles } from "../app/backup_document.js";
import {
  DOCUMENT_MAGIC,
  LEGACY_BACKUP_DOCUMENT_VERSION,
  DOCUMENT_VERSION,
  DOCUMENT_KIND_BACKUP,
  FRAME_TYPE_AUTH,
  FRAME_TYPE_KEY,
  FRAME_TYPE_MAIN,
  MAX_DECOMPRESSED_PAYLOAD_BYTES,
  SHARD_KEY_PASSPHRASE,
} from "../app/constants.js";
import { parseAutoPayload, parseAutoShard } from "../app/frames_parse.js";
import { createInitialState } from "../app/state/initial.js";
import { encodeCbor } from "../lib/cbor.js";
import {
  buildFrame,
  concatBytes,
  encodeUvarint,
  ensureAtob,
  toUnpaddedBase64,
} from "./protocol_test_data.mjs";

ensureAtob();

function buildBackupDocument(manifest, payload, version = LEGACY_BACKUP_DOCUMENT_VERSION) {
  const manifestBytes = encodeCbor(manifest);
  return concatBytes([
    Uint8Array.from(DOCUMENT_MAGIC),
    encodeUvarint(version),
    ...(version === DOCUMENT_VERSION ? [encodeUvarint(DOCUMENT_KIND_BACKUP)] : []),
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
    payload_codec: "raw",
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
      document: buildBackupDocument(7, payload),
      error: /manifest must be a map/,
    },
    {
      name: "required key missing",
      document: (() => {
        const manifest = validManifest(payload);
        delete manifest.created;
        return buildBackupDocument(manifest, payload);
      })(),
      error: /manifest created is required/,
    },
    {
      name: "payload codec required",
      document: (() => {
        const manifest = validManifest(payload);
        delete manifest.payload_codec;
        return buildBackupDocument(manifest, payload);
      })(),
      error: /manifest payload_codec is required/,
    },
    {
      name: "version type",
      document: buildBackupDocument({ ...validManifest(payload), version: "1" }, payload),
      error: /manifest version must be an int/,
    },
    {
      name: "unsupported version",
      document: buildBackupDocument({ ...validManifest(payload), version: 9 }, payload),
      error: /unsupported manifest version/,
    },
    {
      name: "created type",
      document: buildBackupDocument({ ...validManifest(payload), created: "now" }, payload),
      error: /manifest created must be a number/,
    },
    {
      name: "sealed seed mismatch",
      document: buildBackupDocument(
        { ...validManifest(payload), seed: new Uint8Array(32) },
        payload,
      ),
      error: /seed must be null for sealed manifests/,
    },
    {
      name: "unsealed missing seed",
      document: buildBackupDocument(
        { ...validManifest(payload), sealed: false, seed: null },
        payload,
      ),
      error: /seed must be 32 bytes for unsealed manifests/,
    },
    {
      name: "input origin invalid",
      document: buildBackupDocument(
        { ...validManifest(payload), input_origin: "archive" },
        payload,
      ),
      error: /input_origin must be one of/,
    },
    {
      name: "file input roots must be empty",
      document: buildBackupDocument({ ...validManifest(payload), input_roots: ["root"] }, payload),
      error: /input_roots must be empty when input_origin is file/,
    },
    {
      name: "directory requires roots",
      document: buildBackupDocument(
        { ...validManifest(payload), input_origin: "directory", input_roots: [] },
        payload,
      ),
      error: /input_roots must be non-empty/,
    },
    ...["dir/name", "a\\b", ".", "..", "C:notes", "/abs", "bad\u0001"].map((root) => ({
      name: `directory rejects invalid root label ${JSON.stringify(root)}`,
      document: buildBackupDocument(
        { ...validManifest(payload), input_origin: "directory", input_roots: [root] },
        payload,
      ),
      error: /manifest input_root/,
    })),
    {
      name: "path encoding invalid",
      document: buildBackupDocument(
        { ...validManifest(payload), path_encoding: "legacy" },
        payload,
      ),
      error: /path_encoding must be one of/,
    },
    {
      name: "files required",
      document: buildBackupDocument({ ...validManifest(payload), files: [] }, payload),
      error: /manifest files are required/,
    },
    {
      name: "duplicate paths",
      document: buildBackupDocument(
        {
          ...validManifest(payload),
          files: [
            ["a.txt", 1, sha256(Uint8Array.of(1)), null],
            ["a.txt", 2, sha256(Uint8Array.of(2, 3)), null],
          ],
        },
        Uint8Array.of(1, 2, 3),
      ),
      error: /duplicate manifest file path/,
    },
    {
      name: "prefix table requires prefixes",
      document: buildBackupDocument(
        { ...validManifest(payload), path_encoding: "prefix_table" },
        payload,
      ),
      error: /path_prefixes is required/,
    },
    {
      name: "prefix table index out of range",
      document: buildBackupDocument(
        {
          ...validManifest(payload),
          path_encoding: "prefix_table",
          path_prefixes: ["", "root"],
          files: [[4, "a.txt", payload.length, sha256(payload), null]],
        },
        payload,
      ),
      error: /prefix_index out of range/,
    },
    {
      name: "entry hash must be bytes",
      document: buildBackupDocument(
        {
          ...validManifest(payload),
          files: [["a.txt", payload.length, Uint8Array.of(1), null]],
        },
        payload,
      ),
      error: /file hash must be 32 bytes/,
    },
    {
      name: "entry mtime type",
      document: buildBackupDocument(
        {
          ...validManifest(payload),
          files: [["a.txt", payload.length, sha256(payload), "123"]],
        },
        payload,
      ),
      error: /file mtime must be an int/,
    },
    {
      name: "gzip payload_raw_len over decompressed bound",
      document: buildBackupDocument(
        {
          ...validManifest(Uint8Array.of(1)),
          payload_codec: "gzip",
          payload_raw_len: MAX_DECOMPRESSED_PAYLOAD_BYTES + 1,
          files: [["a.txt", MAX_DECOMPRESSED_PAYLOAD_BYTES + 1, sha256(Uint8Array.of(1)), null]],
        },
        gzipPayload(Uint8Array.of(1)),
      ),
      error: /MAX_DECOMPRESSED_PAYLOAD_BYTES/,
    },
  ];

  for (const testCase of cases) {
    await assert.rejects(() => extractFiles(testCase.document), testCase.error, testCase.name);
  }
});

test("document decoder rejects framing-length and hash mismatches", async () => {
  const payload = Uint8Array.of(1, 2, 3);
  const manifest = validManifest(payload);
  const manifestBytes = encodeCbor(manifest);

  const badMagic = buildBackupDocument(manifest, payload);
  badMagic[0] = 0;
  await assert.rejects(() => extractFiles(badMagic), /invalid document magic/);

  const truncatedManifest = concatBytes([
    Uint8Array.from(DOCUMENT_MAGIC),
    encodeUvarint(LEGACY_BACKUP_DOCUMENT_VERSION),
    encodeUvarint(manifestBytes.length + 10),
    manifestBytes,
    encodeUvarint(payload.length),
    payload,
  ]);
  await assert.rejects(() => extractFiles(truncatedManifest), /truncated manifest/);

  const payloadMismatch = concatBytes([
    Uint8Array.from(DOCUMENT_MAGIC),
    encodeUvarint(LEGACY_BACKUP_DOCUMENT_VERSION),
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
    () => extractFiles(buildBackupDocument(digestMismatchManifest, payload)),
    /sha256 mismatch/,
  );

  const extraPayload = Uint8Array.of(1, 2, 3, 4);
  await assert.rejects(
    () => extractFiles(buildBackupDocument(validManifest(payload), extraPayload)),
    /payload length does not match manifest sizes/,
  );
});

test("root manifests reject file and directory conflicts for both path encodings", async () => {
  for (const paths of [
    ["a", "a/b"],
    ["a/b", "a"],
    ["caf\u00e9", "cafe\u0301/b"],
  ]) {
    const payload = Uint8Array.of(1, 2);
    for (const pathEncoding of ["direct", "prefix_table"]) {
      const manifest = {
        ...validManifest(payload),
        path_encoding: pathEncoding,
        path_prefixes: [""],
        files: paths.map((path, index) => {
          const fields = [path, 1, sha256(payload.slice(index, index + 1)), null];
          return pathEncoding === "direct" ? fields : [0, ...fields];
        }),
      };
      await assert.rejects(
        () => extractFiles(buildBackupDocument(manifest, payload)),
        /file\/directory conflict/u,
      );
    }
  }
});

test("extractFiles normalizes gzip-coded payloads", async () => {
  const rawPayload = Uint8Array.of(1, 2, 3, 4, 5, 6, 7, 8);
  const compressedPayload = gzipPayload(rawPayload);
  const manifest = {
    ...validManifest(rawPayload),
    payload_codec: "gzip",
    payload_raw_len: rawPayload.length,
  };
  const extracted = await extractFiles(buildBackupDocument(manifest, compressedPayload));
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
    () => extractFiles(buildBackupDocument(manifest, compressedPayload)),
    /payload_raw_len must match sum of manifest file sizes/,
  );
});

test("extractFiles rejects gzip expansion beyond declared payload_raw_len", async () => {
  const rawPayload = new Uint8Array(2048).fill(0x41);
  const compressedPayload = gzipPayload(rawPayload);
  const manifest = {
    ...validManifest(Uint8Array.of(0x41)),
    payload_codec: "gzip",
    payload_raw_len: 1,
  };
  await assert.rejects(
    () => extractFiles(buildBackupDocument(manifest, compressedPayload)),
    /decoded payload exceeds manifest payload_raw_len/,
  );
});

test("extractFiles rejects unsupported manifest payload codecs", async () => {
  const payload = Uint8Array.of(1, 2, 3);
  const manifest = {
    ...validManifest(payload),
    payload_codec: "brotli",
  };
  await assert.rejects(
    () => extractFiles(buildBackupDocument(manifest, payload)),
    /payload_codec must be one of: raw, gzip/,
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
    buildFrame({
      frameType: FRAME_TYPE_AUTH,
      data: encodeCbor({
        version: 1,
        hash: new Uint8Array(32),
        pub: new Uint8Array(32),
        sig: new Uint8Array(64),
      }),
      index: 1,
      total: 2,
    }),
  );
  assert.throws(
    () => parseAutoPayload(createInitialState(), authBad),
    /neither valid QR payloads nor valid fallback text/,
  );

  const keyBad = toUnpaddedBase64(
    buildFrame({ frameType: FRAME_TYPE_KEY, data: encodeCbor(shardPayload()), index: 0, total: 2 }),
  );
  assert.throws(
    () => parseAutoShard(createInitialState(), keyBad),
    /neither valid shard payloads nor valid fallback text/,
  );

  const mainBad = toUnpaddedBase64(
    buildFrame({ frameType: FRAME_TYPE_MAIN, data: Uint8Array.of(1), index: 1, total: 1 }),
  );
  assert.throws(
    () => parseAutoPayload(createInitialState(), mainBad),
    /neither valid QR payloads nor valid fallback text/,
  );
});

test("current and released documents normalize to the same manifest", async () => {
  const payload = new TextEncoder().encode("backup contents".repeat(20));
  for (const sealed of [true, false]) {
    for (const codec of ["raw", "gzip"]) {
      for (const pathEncoding of ["direct", "prefix_table"]) {
        const legacy = validManifest(payload);
        legacy.sealed = sealed;
        legacy.seed = sealed ? null : new Uint8Array(32).fill(7);
        legacy.payload_codec = codec;
        legacy.path_encoding = pathEncoding;
        if (codec === "gzip") legacy.payload_raw_len = payload.length;
        if (pathEncoding === "prefix_table") {
          legacy.path_prefixes = [""];
          legacy.files = legacy.files.map(([path, ...rest]) => [0, path, ...rest]);
        }
        const current = { ...legacy };
        delete current.version;
        delete current.sealed;
        delete current.payload_raw_len;
        const stored = codec === "gzip" ? gzipPayload(payload) : payload;
        assert.deepEqual(
          await extractFiles(buildBackupDocument(current, stored, DOCUMENT_VERSION)),
          await extractFiles(buildBackupDocument(legacy, stored)),
        );
      }
    }
  }
});

test("current documents reject removed fields and bound gzip by file sizes", async () => {
  const payload = Uint8Array.of(1, 2, 3);
  const manifest = validManifest(payload);
  delete manifest.version;
  delete manifest.sealed;
  for (const key of ["version", "sealed", "payload_raw_len"]) {
    await assert.rejects(
      () =>
        extractFiles(buildBackupDocument({ ...manifest, [key]: null }, payload, DOCUMENT_VERSION)),
      /not allowed/,
    );
  }
  manifest.payload_codec = "gzip";
  manifest.files[0][1] = 2;
  await assert.rejects(
    () => extractFiles(buildBackupDocument(manifest, gzipPayload(payload), DOCUMENT_VERSION)),
    /exceeds/,
  );
});
