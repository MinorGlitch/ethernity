import assert from "node:assert/strict";
import test from "node:test";

import { bytesToUnpaddedBase64 } from "../lib/encoding.js";
import { normalizeJsQrPayload } from "../lib/qr_scan_normalize.js";

test("normalizeJsQrPayload preserves base64 text payloads", () => {
  const hit = {
    data: "YQ",
    binaryData: Uint8Array.from([0x59, 0x51]),
  };
  assert.equal(normalizeJsQrPayload(hit), "YQ");
});

test("normalizeJsQrPayload synthesizes base64 for raw binary payloads", () => {
  const raw = Uint8Array.from([0x00, 0xff, 0x10, 0x20]);
  const hit = {
    data: "\u0000\u00ff",
    binaryData: raw,
  };
  assert.equal(normalizeJsQrPayload(hit), bytesToUnpaddedBase64(raw));
});

test("normalizeJsQrPayload falls back to text when binary data is missing", () => {
  const hit = { data: "ABCD", binaryData: null };
  assert.equal(normalizeJsQrPayload(hit), "ABCD");
});
