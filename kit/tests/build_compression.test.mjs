import assert from "node:assert/strict";
import test from "node:test";

import {
  compressedBundleName,
  DEFAULT_KIT_COMPRESSION,
  selectedCompressions,
} from "../lib/build_compression.mjs";

test("default recovery kit compression is gzip", () => {
  assert.equal(DEFAULT_KIT_COMPRESSION, "gzip");
  assert.deepEqual(selectedCompressions(), ["gzip"]);
  assert.deepEqual(selectedCompressions("both"), ["gzip", "brotli"]);
  assert.deepEqual(selectedCompressions("brotli"), ["gzip", "brotli"]);
});

test("only gzip receives the default recovery kit filename", () => {
  const defaultName = "recovery_kit.bundle.html";
  assert.equal(compressedBundleName(defaultName, "gzip"), defaultName);
  assert.equal(compressedBundleName(defaultName, "brotli"), "recovery_kit.brotli.bundle.html");
});

test("compression build policy rejects unknown values", () => {
  assert.throws(() => selectedCompressions("zip"), /gzip, brotli, both/);
  assert.throws(() => compressedBundleName("recovery_kit.bundle.html", "zip"), /gzip, brotli/);
});
