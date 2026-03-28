import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { scannerHookPathForMode, selectedVariants } from "../lib/build_variants.mjs";

const testDir = dirname(fileURLToPath(import.meta.url));

test("selectedVariants returns the scanner build variant", () => {
  assert.deepEqual(selectedVariants("scanner"), [
    { id: "scanner", bundleName: "recovery_kit.scanner.bundle.html", scannerMode: "jsqr" },
  ]);
});

test("scannerHookPathForMode selects the jsqr hook path for scanner builds", () => {
  assert.equal(scannerHookPathForMode("jsqr", "lean-hook.js", "jsqr-hook.js"), "jsqr-hook.js");
  assert.equal(scannerHookPathForMode("none", "lean-hook.js", "jsqr-hook.js"), "lean-hook.js");
});

test("default kit scanner runtime import targets the jsqr hook", () => {
  const packageJson = JSON.parse(readFileSync(resolve(testDir, "..", "package.json"), "utf8"));
  assert.equal(
    packageJson.imports["#kit-scanner-runtime"],
    "./app/hooks/useQrScannerRuntime_jsqr.js",
  );
});
