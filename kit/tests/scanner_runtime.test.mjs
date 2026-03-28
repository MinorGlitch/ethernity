import assert from "node:assert/strict";
import test from "node:test";

import { detectWithJsQr } from "../app/hooks/jsqr_runtime_core.js";

test("detectWithJsQr falls back to a full-frame scan and enables inversion retries", () => {
  const video = { videoWidth: 200, videoHeight: 100 };
  const canvas = {};
  const attempts = [];
  const ctx = {
    drawImage(...args) {
      attempts.push(["draw", args.length]);
    },
    getImageData(x, y, width, height) {
      attempts.push(["region", x, y, width, height]);
      return { data: new Uint8ClampedArray(width * height * 4) };
    },
  };

  const hit = detectWithJsQr(video, canvas, ctx, (_data, width, height, options) => {
    attempts.push(["detect", width, height, options.inversionAttempts]);
    if (width === 68 && height === 68) {
      return null;
    }
    return { data: "payload", binaryData: new Uint8Array([1, 2, 3]) };
  });

  assert.deepEqual(hit, { bytes: new Uint8Array([1, 2, 3]), text: "payload" });
  assert.equal(canvas.width, 200);
  assert.equal(canvas.height, 100);
  assert.deepEqual(attempts[1], ["region", 66, 16, 68, 68]);
  assert.deepEqual(attempts[2], ["detect", 68, 68, "attemptBoth"]);
  assert.deepEqual(attempts[3], ["region", 0, 0, 200, 100]);
  assert.deepEqual(attempts[4], ["detect", 200, 100, "attemptBoth"]);
});
