import assert from "node:assert/strict";
import test from "node:test";
import { gzipSync } from "node:zlib";
import { gunzipBytesBounded } from "../lib/gzip.js";
import { gzipCases } from "./gzip_test_data.mjs";

for (const sample of gzipCases()) {
  test(`bounded gzip: ${sample.name}`, async () => {
    const decode = () => gunzipBytesBounded(Uint8Array.from(sample.bytes), sample.expectedLen);
    if (sample.error) {
      await assert.rejects(decode, { message: sample.error });
    } else {
      assert.deepEqual(await decode(), Uint8Array.from(sample.expected));
    }
  });
}

test("bounded gzip reports unavailable native decompression", async (t) => {
  const original = Object.getOwnPropertyDescriptor(globalThis, "DecompressionStream");
  t.after(() => Object.defineProperty(globalThis, "DecompressionStream", original));
  Object.defineProperty(globalThis, "DecompressionStream", {
    value: undefined,
    configurable: true,
  });
  await assert.rejects(() => gunzipBytesBounded(new Uint8Array(), 0), {
    message: "gzip extension chunks require DecompressionStream support",
  });
});

test("bounded gzip cancels its reader when output exceeds the limit", async (t) => {
  const cancel = t.mock.method(ReadableStreamDefaultReader.prototype, "cancel");
  const release = t.mock.method(ReadableStreamDefaultReader.prototype, "releaseLock");
  await assert.rejects(() => gunzipBytesBounded(gzipSync(new Uint8Array(256 * 1024)), 1024), {
    message: "decoded chunk exceeds raw_len",
  });
  assert.equal(cancel.mock.callCount(), 1);
  assert.equal(release.mock.callCount(), 1);
});

test("bounded gzip preserves the size error when cancellation fails", async (t) => {
  const original = ReadableStreamDefaultReader.prototype.cancel;
  t.mock.method(ReadableStreamDefaultReader.prototype, "cancel", async function () {
    await original.call(this);
    throw new Error("cancel failed");
  });
  await assert.rejects(() => gunzipBytesBounded(gzipSync(new Uint8Array(256 * 1024)), 1024), {
    message: "decoded chunk exceeds raw_len",
  });
});
