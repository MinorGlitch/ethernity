import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import { sha256 } from "@noble/hashes/sha2.js";

import { extractFiles } from "../app/envelope.js";
import { ensureCiphertextAndHash, parseAutoPayload, parseAutoShard } from "../app/frames.js";
import { autoRecoverShardSecret } from "../app/shards.js";
import { createInitialState } from "../app/state/initial.js";
import { decryptAgePassphrase } from "../lib/age_scrypt.js";
import { bytesToHex } from "../lib/encoding.js";
import { ensureAtob } from "./test_helpers.mjs";

ensureAtob();

const FIXTURES_ROOT = path.resolve(process.cwd(), "../tests/fixtures/v1_0/golden");

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

async function restoreScenario(scenarioPath) {
  const scenarioDir = path.dirname(scenarioPath);
  const snapshot = readJson(scenarioPath);
  const state = createInitialState();

  const mainPayloadText = fs.readFileSync(path.join(scenarioDir, "main_payloads.txt"), "utf8");
  const mainAdded = parseAutoPayload(state, mainPayloadText);
  assert.ok(mainAdded >= 1);

  const cipherHash = ensureCiphertextAndHash(state);
  assert.ok(cipherHash instanceof Uint8Array);
  assert.equal(state.ciphertext instanceof Uint8Array, true);
  assert.equal(state.cipherDocHashHex, bytesToHex(cipherHash));

  if (snapshot.shard_payload_count > 0) {
    const shardPayloadText = fs.readFileSync(
      path.join(scenarioDir, "shard_payloads_threshold.txt"),
      "utf8"
    );
    const shardAdded = parseAutoShard(state, shardPayloadText);
    assert.equal(shardAdded, snapshot.shard_payload_count);
    assert.equal(state.shardFrames.size, snapshot.shard_payload_count);
    assert.equal(autoRecoverShardSecret(state), true);
    assert.equal(state.agePassphrase, snapshot.passphrase);
  } else {
    state.agePassphrase = snapshot.passphrase;
  }

  const envelopeBytes = await decryptAgePassphrase(state.ciphertext, state.agePassphrase);
  const extracted = extractFiles(envelopeBytes);
  const expectedPaths = snapshot.expected_relative_paths.slice().sort();
  const actualPaths = extracted.files.map(file => file.path).sort();

  assert.deepEqual(actualPaths, expectedPaths);
  assert.equal(extracted.manifest.inputOrigin, snapshot.manifest_projection.input_origin);
  assert.deepEqual(extracted.manifest.inputRoots, snapshot.manifest_projection.input_roots);

  for (const file of extracted.files) {
    assert.equal(bytesToHex(sha256(file.data)), snapshot.expected_file_sha256[file.path]);
  }
}

test("frozen v1.0 fixtures restore end-to-end in the kit", async () => {
  const index = readJson(path.join(FIXTURES_ROOT, "index.json"));
  for (const scenario of index.scenarios) {
    await restoreScenario(path.join(FIXTURES_ROOT, scenario.path));
  }
});
