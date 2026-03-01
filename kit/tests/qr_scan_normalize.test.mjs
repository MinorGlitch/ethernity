import assert from "node:assert/strict";
import test from "node:test";

import { normalizeJsQrPayload } from "../lib/qr_scan_normalize.js";

test("normalizeJsQrPayload preserves base64 text payloads", () => {
  const hit = {
    data: "YQ",
    binaryData: Uint8Array.from([0x59, 0x51]),
  };
  assert.deepEqual(normalizeJsQrPayload(hit), { text: "YQ" });
});

test("normalizeJsQrPayload preserves raw binary payloads", () => {
  const raw = Uint8Array.from([0x00, 0xff, 0x10, 0x20]);
  const hit = {
    data: "\u0000\u00ff",
    binaryData: raw,
  };
  assert.deepEqual(normalizeJsQrPayload(hit), { bytes: raw, text: "\u0000\u00ff" });
});

test("normalizeJsQrPayload falls back to text when binary data is missing", () => {
  const hit = { data: "ABCD", binaryData: null };
  assert.deepEqual(normalizeJsQrPayload(hit), { text: "ABCD" });
});
