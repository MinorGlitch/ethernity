import assert from "node:assert/strict";
import test from "node:test";
import { decodePackedKit } from "../lib/decode_packed_kit.mjs";

test("decoder globals stay in their worker and cannot reach the next decode", async () => {
  assert.equal(
    await decodePackedKit('kitDecoderGlobal = "isolated"; postMessage(kitDecoderGlobal)'),
    "isolated",
  );
  assert.equal(await decodePackedKit("postMessage(typeof kitDecoderGlobal)"), "undefined");
  assert.equal(Object.hasOwn(globalThis, "kitDecoderGlobal"), false);
});

test("decoder failures reject verification", async () => {
  await assert.rejects(decodePackedKit('throw Error("broken decoder")'), /broken decoder/);
  await assert.rejects(decodePackedKit(""), /exited without returning the app/);
});

test("a stuck decoder is stopped at the verification deadline", async () => {
  await assert.rejects(decodePackedKit("while (true) {}", 100), /decoder timed out/);
});
