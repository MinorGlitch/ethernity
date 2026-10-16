import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { scannerPathForMode, selectedVariants } from "../lib/build_variants.mjs";

const testDir = dirname(fileURLToPath(import.meta.url));

test("selectedVariants returns the scanner build variant", () => {
  assert.deepEqual(selectedVariants("scanner"), [
    { id: "scanner", bundleName: "recovery_kit.scanner.bundle.html", scannerMode: "jsqr" },
  ]);
});

test("scannerPathForMode selects the jsqr controller path for scanner builds", () => {
  assert.equal(
    scannerPathForMode("jsqr", "lean-controller.js", "jsqr-controller.js"),
    "jsqr-controller.js",
  );
  assert.equal(
    scannerPathForMode("none", "lean-controller.js", "jsqr-controller.js"),
    "lean-controller.js",
  );
});

test("default kit scanner runtime import targets the jsqr controller", () => {
  const packageJson = JSON.parse(readFileSync(resolve(testDir, "..", "package.json"), "utf8"));
  assert.equal(packageJson.imports["#kit-scanner"], "./app/scanner/panel.js");
});
