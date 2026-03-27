import assert from "node:assert/strict";
import test from "node:test";

import { MAX_QR_PAYLOAD_CHARS } from "../app/constants.js";
import {
  bumpError,
  cloneState,
  createInitialState,
  resetState,
  setStatus,
} from "../app/state/initial.js";
import { reducer } from "../app/state/reducer.js";
import { decodeCanonicalCbor, decodeCbor, encodeCbor } from "../lib/cbor.js";
import {
  bytesEqual,
  bytesToUnpaddedBase64,
  concatBytes,
  decodePayloadString,
  decodeZBase32,
  filterZBase32Lines,
  hexToBytes,
  readUvarint,
} from "../lib/encoding.js";
import { validateManifestPath } from "../lib/path_validation.js";
import { makeZip } from "../lib/zip.js";
import { ensureAtob } from "./test_helpers.mjs";

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
  assert.throws(() => decodeZBase32("yb"), /non-canonical tail bits/);
  assert.throws(() => decodeZBase32("!"), /invalid z-base-32 character/);
  assert.throws(() => filterZBase32Lines("yy\nhello\n8x\n"), /outside the z-base-32 alphabet/);

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

test("CBOR codec roundtrips canonical values and rejects malformed payloads", () => {
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
  assert.equal(decodeCanonicalCbor(Uint8Array.of(0xf9, 0x3e, 0x00), "probe"), 1.5);
  assert.equal(decodeCanonicalCbor(Uint8Array.of(0xf9, 0x3c, 0x00), "probe"), 1);

  const f32Value = Math.fround(1.1);
  const f32Bytes = new Uint8Array(5);
  f32Bytes[0] = 0xfa;
  new DataView(f32Bytes.buffer, f32Bytes.byteOffset + 1, 4).setFloat32(0, f32Value);
  assert.equal(decodeCanonicalCbor(f32Bytes, "probe"), f32Value);

  const nonCanonicalFloat32 = Uint8Array.of(0xfa, 0x3f, 0xc0, 0x00, 0x00); // 1.5 encoded as float32
  assert.throws(() => decodeCanonicalCbor(nonCanonicalFloat32, "probe"), /canonical CBOR/);

  assert.throws(() => decodeCanonicalCbor(Uint8Array.of(0x18, 0x01), "probe"), /canonical CBOR/);
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
});

test("state helpers clone and reset mutable fields safely", () => {
  const state = createInitialState();
  state.mainFrames.set(0, { data: Uint8Array.of(1) });
  state.shardFrames.set(1, { share: Uint8Array.of(2) });
  state.extractedFiles.push({ path: "a", data: Uint8Array.of(3) });
  setStatus(state, "frameStatus", ["ok"], "ok");
  bumpError(state, "errors");
  assert.equal(state.errors, 1);

  const cloned = cloneState(state);
  assert.notEqual(cloned.mainFrames, state.mainFrames);
  assert.notEqual(cloned.shardFrames, state.shardFrames);
  assert.notEqual(cloned.extractedFiles, state.extractedFiles);
  assert.deepEqual(cloned.frameStatus, state.frameStatus);

  resetState(state);
  assert.equal(state.mainFrames.size, 0);
  assert.equal(state.shardFrames.size, 0);
  assert.equal(state.errors, 0);
  assert.equal(state.frameStatus.lines[0], "State cleared.");
});

test("reducer rejects stale state commits and bumps revision on reset", () => {
  let state = createInitialState();
  assert.equal(state.revision, 0);

  state = reducer(state, {
    type: "MUTATE_STATE",
    baseRevision: state.revision,
    mutate(next) {
      next.payloadText = "a";
    },
  });
  assert.equal(state.payloadText, "a");
  assert.equal(state.revision, 1);

  const unchanged = reducer(state, {
    type: "MUTATE_STATE",
    baseRevision: 0,
    mutate(next) {
      next.payloadText = "stale";
    },
  });
  assert.equal(unchanged, state);
  assert.equal(unchanged.payloadText, "a");
  assert.equal(unchanged.revision, 1);

  state = reducer(state, {
    type: "MUTATE_STATE",
    baseRevision: state.revision,
    mutate(next) {
      next.payloadText = "b";
    },
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
