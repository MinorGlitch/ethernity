import assert from "node:assert/strict";
import test from "node:test";

import { readEmbeddedKitMetadata } from "../app/kit_metadata.js";
import { createBaseState } from "../app/state/initial.js";

const HASH_A = "aa".repeat(32);
const HASH_B = "bb".repeat(32);
const HASH_C = "cc".repeat(32);

test.afterEach(() => {
  delete globalThis.__ETHERNITY_KIT_METADATA__;
});

test("reusable kit metadata carries no chain-specific trust claim", () => {
  globalThis.__ETHERNITY_KIT_METADATA__ = {
    capability: "ethernity-unanchored-rescue",
    version: 1,
    supported_document_versions: [1, 2, 3],
  };

  assert.deepEqual(readEmbeddedKitMetadata(), {
    capability: "ethernity-unanchored-rescue",
    version: 1,
  });
  const state = createBaseState();
  assert.equal(state.expectedHeadDocHashText, "");
});

test("embedded chain-bound metadata is rejected", () => {
  globalThis.__ETHERNITY_KIT_METADATA__ = {
    capability: "ethernity-chain-bound-recovery",
    version: 1,
    root_document_hash: HASH_A,
    root_signing_public_key_fingerprint: HASH_B,
    expected_latest_head_hash: HASH_C,
    supported_document_versions: [1, 2, 3],
  };

  assert.throws(() => readEmbeddedKitMetadata(), /unsupported recovery kit capability/u);
});
