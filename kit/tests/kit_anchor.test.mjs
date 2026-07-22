import assert from "node:assert/strict";
import test from "node:test";

import { readEmbeddedKitMetadata } from "../app/kit_anchor.js";
import { createBaseState } from "../app/state/initial.js";

const HASH_A = "aa".repeat(32);
const HASH_B = "bb".repeat(32);
const HASH_C = "cc".repeat(32);

test.afterEach(() => {
  delete globalThis.__ETHERNITY_KIT_METADATA__;
});

test("chain-bound kit metadata pins initial recovery state", () => {
  globalThis.__ETHERNITY_KIT_METADATA__ = {
    capability: "ethernity-chain-bound-recovery",
    version: 1,
    root_document_hash: HASH_A,
    root_signing_public_key_fingerprint: HASH_B,
    expected_latest_head_hash: HASH_C,
    supported_extension_envelope_versions: [2],
    supported_extension_schema_versions: [1],
  };

  const metadata = readEmbeddedKitMetadata();
  const state = createBaseState();

  assert.equal(metadata.anchored, true);
  assert.equal(metadata.rootDocumentHashHex, HASH_A);
  assert.equal(metadata.rootSigningPublicKeyFingerprintHex, HASH_B);
  assert.equal(state.expectedHeadDocHashText, HASH_C);
  assert.equal(state.trustedKitAnchored, true);
  assert.equal(state.freshnessUnknownAcknowledged, false);
});

test("unanchored rescue metadata carries no authenticated freshness claim", () => {
  globalThis.__ETHERNITY_KIT_METADATA__ = {
    capability: "ethernity-unanchored-rescue",
    version: 1,
    supported_extension_envelope_versions: [2],
    supported_extension_schema_versions: [1],
  };

  assert.deepEqual(readEmbeddedKitMetadata(), {
    capability: "ethernity-unanchored-rescue",
    version: 1,
    anchored: false,
  });
  assert.equal(createBaseState().expectedHeadDocHashText, "");
  assert.equal(createBaseState().trustedKitAnchored, false);
});

test("kit metadata fails closed for unsupported extension versions", () => {
  globalThis.__ETHERNITY_KIT_METADATA__ = {
    capability: "ethernity-chain-bound-recovery",
    version: 1,
    root_document_hash: HASH_A,
    root_signing_public_key_fingerprint: HASH_B,
    expected_latest_head_hash: HASH_C,
    supported_extension_envelope_versions: [99],
    supported_extension_schema_versions: [1],
  };

  assert.throws(() => readEmbeddedKitMetadata(), /does not support extension envelope version 2/u);
});
