import assert from "node:assert/strict";
import test from "node:test";

import { scannerHookPathForMode, selectedVariants } from "../lib/build_variants.mjs";

test("selectedVariants returns the scanner build variant", () => {
  assert.deepEqual(selectedVariants("scanner"), [
    { id: "scanner", bundleName: "recovery_kit.scanner.bundle.html", scannerMode: "jsqr" },
  ]);
});

test("scannerHookPathForMode selects the jsqr hook path for scanner builds", () => {
  assert.equal(scannerHookPathForMode("jsqr", "lean-hook.js", "jsqr-hook.js"), "jsqr-hook.js");
  assert.equal(scannerHookPathForMode("none", "lean-hook.js", "jsqr-hook.js"), "lean-hook.js");
});
