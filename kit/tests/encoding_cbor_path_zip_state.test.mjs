import {
  selectCiphertextSource,
  selectShardInputs,
  selectShardKeyLabel,
} from "../app/state/selectors.js";
import {
  addMainDocumentFrame,
  primaryDocumentRecord,
  documentCounts,
} from "../app/documents/store.js";
import { addShardPayloadFrame, activeShardSetRecord, shardCounts } from "../app/shard_store.js";
import { parseAutoPayload } from "../app/frames_parse.js";
import {
  buildFrame,
  encodeZBase32,
  toUnpaddedBase64,
  createTestDocument,
  ensureAtob,
} from "./protocol_test_data.mjs";
import {
  FRAME_TYPE_MAIN,
  SHARD_KEY_PASSPHRASE,
  SHARD_KEY_SIGNING_SEED,
  MAX_QR_PAYLOAD_CHARS,
} from "../app/constants.js";
import { dispatchState } from "../app/state_actions.js";
import assert from "node:assert/strict";
import test from "node:test";

import {
  bumpError,
  cloneState,
  createInitialState,
  resetState,
  setStatus,
} from "../app/state/initial.js";
import { reducer } from "../app/state/reducer.js";
import { decodeDeterministicCbor, decodeCbor, encodeCbor } from "../lib/cbor.js";
import { bytesEqual, concatBytes, hexToBytes } from "../lib/bytes.js";
import {
  bytesToUnpaddedBase64,
  decodePayloadString,
  decodeZBase32,
  filterZBase32Lines,
  readUvarint,
} from "../lib/encoding.js";
import { validateManifestPath } from "../lib/path_validation.js";
import { makeZip } from "../lib/zip.js";

ensureAtob();

test("encoding primitives enforce strict payload and varint rules", () => {
  assert.equal(decodePayloadString(""), null);
  assert.equal(decodePayloadString("A".repeat(MAX_QR_PAYLOAD_CHARS + 1)), null);
  assert.equal(decodePayloadString("abc="), null);
  assert.equal(decodePayloadString("abc_"), null);
  assert.equal(decodePayloadString("abc-"), null);
  assert.equal(decodePayloadString("abcde"), null);
  assert.equal(decodePayloadString("AB"), null);

  const decoded = decodePayloadString("YQ");
  assert.ok(decoded instanceof Uint8Array);
  assert.deepEqual(Array.from(decoded), [97]);

  assert.deepEqual(Array.from(decodeZBase32("yy")), [0]);
  assert.throws(() => decodeZBase32("yb"), /nonzero unused tail bits/);
  assert.throws(() => decodeZBase32("!"), /invalid z-base-32 character/);
  assert.throws(() => filterZBase32Lines("yy\nhello\n8x\n"), /outside the z-base-32 alphabet/);
  assert.deepEqual(filterZBase32Lines("01. yy\r12.yy\r\n3. yy\n"), ["yy", "yy", "yy"]);
  assert.deepEqual(filterZBase32Lines("10000. yy\n50000. yy\n"), ["yy", "yy"]);
  assert.throws(() => filterZBase32Lines("100000. yy\n"), /outside the z-base-32 alphabet/);
  assert.throws(() => filterZBase32Lines("01 yy\n"), /outside the z-base-32 alphabet/);
  assert.throws(() => filterZBase32Lines("01. \u212a\n"), /outside the z-base-32 alphabet/);
  assert.throws(() => decodeZBase32("\u212a"), /invalid z-base-32 character/);

  assert.throws(() => readUvarint(Uint8Array.of(0x80), 0), /truncated varint/);
  assert.throws(
    () => readUvarint(Uint8Array.of(0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x02), 0),
    /varint too large/,
  );
  assert.deepEqual(readUvarint(Uint8Array.of(0x81, 0x01), 0), { value: 129, offset: 2 });

  assert.equal(bytesEqual(Uint8Array.of(1, 2), Uint8Array.of(1, 2)), true);
  assert.equal(bytesEqual(Uint8Array.of(1, 2), Uint8Array.of(1, 3)), false);
  assert.equal(bytesToUnpaddedBase64(Uint8Array.of(97)), "YQ");
  assert.deepEqual(Array.from(concatBytes(Uint8Array.of(1), Uint8Array.of(2, 3))), [1, 2, 3]);
  assert.deepEqual(Array.from(hexToBytes("0a0b")), [10, 11]);
});

test("CBOR codec roundtrips deterministically encoded values and rejects malformed payloads", () => {
  const value = {
    z: true,
    a: "text",
    arr: [1, -2, null, new Uint8Array([1, 2, 3])],
    n: 1.5,
  };
  const encoded = encodeCbor(value);
  const decoded = decodeCbor(encoded);

  assert.equal(decoded.a, "text");
  assert.equal(decoded.z, true);
  assert.equal(decoded.arr[1], -2);
  assert.deepEqual(Array.from(decoded.arr[3]), [1, 2, 3]);

  assert.equal(decodeCbor(Uint8Array.of(0xf9, 0x3e, 0x00)), 1.5);
  assert.equal(decodeDeterministicCbor(Uint8Array.of(0xf9, 0x3e, 0x00), "probe"), 1.5);
  assert.equal(decodeDeterministicCbor(Uint8Array.of(0xf9, 0x3c, 0x00), "probe"), 1);

  const f32Value = Math.fround(1.1);
  const f32Bytes = new Uint8Array(5);
  f32Bytes[0] = 0xfa;
  new DataView(f32Bytes.buffer, f32Bytes.byteOffset + 1, 4).setFloat32(0, f32Value);
  assert.equal(decodeDeterministicCbor(f32Bytes, "probe"), f32Value);

  const overlyWideFloat32 = Uint8Array.of(0xfa, 0x3f, 0xc0, 0x00, 0x00); // 1.5 encoded as float32
  assert.throws(() => decodeDeterministicCbor(overlyWideFloat32, "probe"), /deterministic CBOR/);

  assert.throws(
    () => decodeDeterministicCbor(Uint8Array.of(0x18, 0x01), "probe"),
    /deterministic CBOR/,
  );
  assert.throws(() => decodeCbor(Uint8Array.of(0x5f)), /indefinite CBOR lengths not supported/);
  assert.throws(() => decodeCbor(Uint8Array.of(0xf8, 0x00)), /unsupported CBOR simple value/);
  assert.throws(() => encodeCbor(undefined), /unsupported CBOR value/);
});

test("path validation and zip creation enforce safe relative paths", async () => {
  assert.equal(validateManifestPath("docs/file.txt"), "docs/file.txt");
  assert.throws(() => validateManifestPath("/abs/file.txt"), /must be relative/);
  assert.throws(() => validateManifestPath("C:/file.txt"), /must be relative/);
  assert.throws(() => validateManifestPath("C:notes.txt"), /must be relative/);
  assert.throws(() => validateManifestPath("a\\b.txt"), /POSIX separators/);
  assert.throws(() => validateManifestPath("a//b.txt"), /empty path segments/);
  assert.throws(() => validateManifestPath("a/../b.txt"), /must not contain '\.' or '\.\.'/);
  assert.throws(() => validateManifestPath("docs/\u0001.txt"), /control characters/);
  assert.throws(() => validateManifestPath("docs/\u0085.txt"), /control characters/);

  const zipBlob = makeZip([{ path: "docs/file.txt", data: Uint8Array.of(1, 2, 3, 4) }]);
  const zipBytes = new Uint8Array(await zipBlob.arrayBuffer());
  assert.deepEqual(Array.from(zipBytes.slice(0, 4)), [0x50, 0x4b, 0x03, 0x04]);
  assert.deepEqual(
    Array.from(zipBytes.slice(zipBytes.length - 22, zipBytes.length - 18)),
    [0x50, 0x4b, 0x05, 0x06],
  );
  assert.equal(zipBytes[6] | (zipBytes[7] << 8), 0x0800);
  const eocdOffset = zipBytes.length - 22;
  const centralOffset =
    zipBytes[eocdOffset + 16] |
    (zipBytes[eocdOffset + 17] << 8) |
    (zipBytes[eocdOffset + 18] << 16) |
    (zipBytes[eocdOffset + 19] << 24);
  assert.equal(zipBytes[centralOffset + 8] | (zipBytes[centralOffset + 9] << 8), 0x0800);

  assert.throws(() => makeZip([{ path: "docs/file.txt", data: "not-bytes" }]), /must be bytes/);
  assert.throws(
    () =>
      makeZip([
        { path: "docs/file.txt", data: Uint8Array.of(1) },
        { path: "docs/file.txt", data: Uint8Array.of(2) },
      ]),
    /duplicate ZIP entry path/,
  );
});

test("state cloning and reset preserve mutable-field isolation", () => {
  const state = createInitialState();
  const document = createTestDocument(state);
  const shardPayload = {
    share: Uint8Array.of(2),
    docHash: Uint8Array.of(3),
    signPub: Uint8Array.of(4),
    signature: Uint8Array.of(5),
    shardSetId: Uint8Array.of(6),
  };
  const shardRecord = {
    docId: Uint8Array.of(7),
    shardFrames: new Map([[1, shardPayload]]),
  };
  document.mainFrames.set(0, { data: Uint8Array.of(1) });
  state.shardSets.set("active", shardRecord);
  state.activeShardSetKey = "active";
  state.extractedFiles.push({ path: "a", data: Uint8Array.of(3) });
  setStatus(state, "frameStatus", ["ok"], "ok");
  bumpError(state, "errors");
  assert.equal(state.errors, 1);

  const cloned = cloneState(state);
  assert.notEqual(primaryDocumentRecord(cloned).mainFrames, document.mainFrames);
  assert.notEqual(
    activeShardSetRecord(cloned).shardFrames,
    activeShardSetRecord(state).shardFrames,
  );
  assert.notEqual(cloned.extractedFiles, state.extractedFiles);
  assert.deepEqual(cloned.frameStatus, state.frameStatus);
  assert.equal(
    activeShardSetRecord(cloned).shardFrames,
    cloned.shardSets.get("active").shardFrames,
  );
  assert.notEqual(activeShardSetRecord(cloned).shardFrames.get(1), shardPayload);
  assert.notEqual(activeShardSetRecord(cloned).shardFrames.get(1).share, shardPayload.share);
  activeShardSetRecord(cloned).shardFrames.get(1).signatureVerified = true;
  activeShardSetRecord(cloned).shardFrames.get(1).share[0] = 9;
  assert.equal(shardPayload.signatureVerified, undefined);
  assert.equal(shardPayload.share[0], 2);

  let committed = createInitialState();
  dispatchState((action) => {
    committed = reducer(committed, action);
  }, cloned);
  const committedDocument = primaryDocumentRecord(committed);
  const committedShards = activeShardSetRecord(committed);
  primaryDocumentRecord(cloned).mainFrames.clear();
  primaryDocumentRecord(cloned).authStatus = "invalid signature";
  activeShardSetRecord(cloned).shardFrames.get(1).signatureVerified = false;
  activeShardSetRecord(cloned).shardFrames.get(1).share[0] = 8;
  assert.equal(committedDocument.mainFrames.size, 1);
  assert.equal(committedDocument.authStatus, "missing");
  assert.equal(committedShards.shardFrames.get(1).signatureVerified, true);
  assert.equal(committedShards.shardFrames.get(1).share[0], 9);
  dispatchState((action) => {
    committed = reducer(committed, action);
  }, cloned);
  assert.equal(primaryDocumentRecord(committed), committedDocument);

  resetState(state);
  assert.equal(primaryDocumentRecord(state), null);
  assert.equal(state.documents.size, 0);
  assert.equal(state.shardSets.size, 0);
  assert.equal(activeShardSetRecord(state)?.shardFrames.size ?? 0, 0);
  assert.equal(state.errors, 0);
  assert.equal(state.frameStatus.lines[0], "State cleared.");
});

test("reducer rejects stale state commits and bumps revision on reset", () => {
  let state = createInitialState();
  assert.equal(state.revision, 0);

  state = reducer(state, {
    type: "REPLACE_STATE",
    baseRevision: state.revision,
    state: { ...state, payloadText: "a" },
  });
  assert.equal(state.payloadText, "a");
  assert.equal(state.revision, 1);

  const unchanged = reducer(state, {
    type: "REPLACE_STATE",
    baseRevision: 0,
    state: { ...state, payloadText: "stale" },
  });
  assert.equal(unchanged, state);
  assert.equal(unchanged.payloadText, "a");
  assert.equal(unchanged.revision, 1);

  state = reducer(state, {
    type: "REPLACE_STATE",
    baseRevision: state.revision,
    state: { ...state, payloadText: "b" },
  });
  assert.equal(state.payloadText, "b");
  assert.equal(state.revision, 2);

  state = reducer(state, { type: "RESET" });
  assert.equal(state.revision, 3);
  assert.equal(state.payloadText, "");
  assert.equal(state.frameStatus.lines[0], "State cleared.");

  const patched = reducer(state, {
    type: "PATCH_STATE",
    baseRevision: state.revision,
    patch: { payloadText: "patch" },
  });
  assert.equal(patched.payloadText, "patch");
  assert.equal(patched.revision, 4);

  const stalePatched = reducer(patched, {
    type: "PATCH_STATE",
    baseRevision: state.revision,
    patch: { payloadText: "stale-patch" },
  });
  assert.equal(stalePatched, patched);
  assert.equal(stalePatched.payloadText, "patch");
});

test("record selection and diagnostics follow the stored records", () => {
  const state = createInitialState();
  const first = { docId: Uint8Array.of(1), index: 0, total: 1, data: Uint8Array.of(1) };
  const second = { ...first, docId: Uint8Array.of(2), data: Uint8Array.of(2, 3) };
  addMainDocumentFrame(state, first);
  addMainDocumentFrame(state, second);
  addMainDocumentFrame(state, second);
  assert.equal(documentCounts(state).duplicates, 1);
  assert.equal(primaryDocumentRecord(state), state.documents.get("01"));
  assert.match(selectCiphertextSource(state).detail, /3 B.*2 documents/);

  const payload = {
    version: 1,
    keyType: SHARD_KEY_PASSPHRASE,
    threshold: 1,
    shareCount: 1,
    secretLen: 1,
    shareIndex: 1,
    share: Uint8Array.of(1),
    docHash: Uint8Array.of(3),
    signPub: Uint8Array.of(4),
    signature: Uint8Array.of(5),
  };
  addShardPayloadFrame(state, first, payload);
  const firstSetKey = state.activeShardSetKey;
  addShardPayloadFrame(state, second, { ...payload, keyType: SHARD_KEY_SIGNING_SEED });
  assert.equal(selectShardKeyLabel(state), "signing key");
  assert.notEqual(primaryDocumentRecord(state).docIdHex, selectShardInputs(state).docIdHex);
  state.primaryDocIdHex = "02";
  assert.equal(primaryDocumentRecord(state).docIdHex, selectShardInputs(state).docIdHex);
  state.activeShardSetKey = firstSetKey;
  assert.equal(selectShardKeyLabel(state), "passphrase");
  assert.equal(selectShardInputs(state).docIdHex, "01");
  activeShardSetRecord(state).conflicts += 1;
  assert.equal(shardCounts(state).conflicts, 1);

  addMainDocumentFrame(state, { ...first, data: Uint8Array.of(9) });
  assert.equal(selectCiphertextSource(state).available, false);
  assert.equal(documentCounts(state).conflicts, 1);
});

test("malformed AUTH text remains an error when more documents arrive", () => {
  const state = createInitialState();
  const frame = buildFrame({ frameType: FRAME_TYPE_MAIN, data: Uint8Array.of(1) });
  parseAutoPayload(state, `MAIN FRAME\n${encodeZBase32(frame)}\nAUTH FRAME\nnot-valid!`);
  assert.equal(documentCounts(state).authErrors, 1);
  parseAutoPayload(
    state,
    toUnpaddedBase64(
      buildFrame({
        frameType: FRAME_TYPE_MAIN,
        docId: new Uint8Array(8).fill(2),
        data: Uint8Array.of(3),
      }),
    ),
  );
  assert.equal(documentCounts(state).authErrors, 1);
  assert.equal(selectCiphertextSource(state).available, false);
  resetState(state);
  assert.equal(documentCounts(state).authErrors, 0);
});
