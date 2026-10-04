import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { sha256 } from "@noble/hashes/sha2.js";

import { recoverLatestFromEncryptedDocuments } from "../app/extensions/recovery.js";
import { collectedRecoveryDocuments } from "../app/frames_cipher.js";
import { parseAutoPayload, parseAutoShard } from "../app/frames_parse.js";
import { verifyCollectedShardSignatures } from "../app/shard_auth.js";
import { autoRecoverShardSecret } from "../app/shards.js";
import { createInitialState } from "../app/state/initial.js";
import { decryptAgePassphrase } from "../lib/age_scrypt.js";
import { bytesToHex } from "../lib/bytes.js";
import { ensureAtob } from "./protocol_test_data.mjs";

ensureAtob();

const testDir = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES_ROOT = path.resolve(
  testDir,
  "..",
  "..",
  "tests",
  "fixtures",
  "v1_2",
  "extension_golden",
);

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function latestStateKey(snapshot) {
  const extensionKeys = Object.keys(snapshot.extension_doc_hashes).sort();
  return extensionKeys.at(-1) ?? "root";
}

function expectedExtensionIndex(stateKey) {
  if (stateKey === "root") return null;
  return Number.parseInt(stateKey.slice("extension_".length), 10);
}

function recoveredFileHashes(files) {
  return Object.fromEntries(
    files
      .map((file) => [file.path, bytesToHex(sha256(file.data))])
      .sort(([left], [right]) => left.localeCompare(right)),
  );
}

async function recoverPassphraseFromShardFixture(snapshotPath, { payloadName, shardName }) {
  const scenarioDir = path.dirname(snapshotPath);
  const snapshot = readJson(snapshotPath);
  const shardFixture = snapshot.shard_fixtures[shardName];
  assert.ok(shardFixture, `missing ${shardName} shard fixture in ${snapshotPath}`);

  const state = createInitialState();
  const payloadText = fs.readFileSync(
    path.join(scenarioDir, snapshot.payload_fixtures[payloadName].text),
    "utf8",
  );
  const addedPayloads = parseAutoPayload(state, payloadText);
  assert.equal(addedPayloads, snapshot.payload_fixtures[payloadName].frame_count);

  const shardText = fs.readFileSync(path.join(scenarioDir, shardFixture.text), "utf8");
  const addedShards = parseAutoShard(state, shardText);
  assert.equal(addedShards, shardFixture.threshold);
  assert.equal(state.shardFrames.size, shardFixture.threshold);

  const signatures = await verifyCollectedShardSignatures(state);
  assert.equal(signatures.invalid, 0);
  assert.equal(signatures.verified, shardFixture.threshold);
  assert.equal(autoRecoverShardSecret(state), true);
  assert.equal(state.agePassphrase, snapshot.passphrase);
  return state.agePassphrase;
}

async function restoreScenarioWithPassphrase(snapshotPath, passphrase) {
  const scenarioDir = path.dirname(snapshotPath);
  const snapshot = readJson(snapshotPath);
  const state = createInitialState();
  const payloadText = fs.readFileSync(
    path.join(scenarioDir, snapshot.payload_fixtures.chain.text),
    "utf8",
  );
  assert.equal(parseAutoPayload(state, payloadText), snapshot.payload_fixtures.chain.frame_count);
  const documents = collectedRecoveryDocuments(state);
  const result = await recoverLatestFromEncryptedDocuments(
    documents,
    passphrase,
    decryptAgePassphrase,
    { freshnessUnknownAcknowledged: true, allowResourceIntensiveScrypt: true },
  );
  return { result, snapshot };
}

test("frozen v1.2 root shards unlock and restore an extension chain in the kit", async () => {
  const item = {
    name: "raw/large_raw_two_extension_chain",
    payloadName: "root",
    shardName: "root",
  };
  const snapshotPath = path.join(FIXTURES_ROOT, item.name, "snapshot.json");
  const passphrase = await recoverPassphraseFromShardFixture(snapshotPath, item);
  const { result, snapshot } = await restoreScenarioWithPassphrase(snapshotPath, passphrase);
  const latestKey = latestStateKey(snapshot);
  assert.equal(result.selectedExtensionIndex, expectedExtensionIndex(latestKey));
  assert.deepEqual(recoveredFileHashes(result.files), snapshot.states[latestKey]);
});

test("frozen root-bound quorum restores root and an intact prefix when the latest head is absent", async () => {
  const scenarioDir = path.join(FIXTURES_ROOT, "raw/large_raw_two_extension_chain");
  const snapshotPath = path.join(scenarioDir, "snapshot.json");
  const snapshot = readJson(snapshotPath);
  const passphrase = await recoverPassphraseFromShardFixture(snapshotPath, {
    payloadName: "root",
    shardName: "root",
  });
  const state = createInitialState();
  for (const name of ["root", "extension_01"]) {
    parseAutoPayload(
      state,
      fs.readFileSync(path.join(scenarioDir, snapshot.payload_fixtures[name].text), "utf8"),
    );
  }
  const documents = collectedRecoveryDocuments(state);
  const decrypted = new Map();
  const decrypt = async (ciphertext, secret, options) => {
    const key = bytesToHex(ciphertext);
    if (!decrypted.has(key)) {
      decrypted.set(key, await decryptAgePassphrase(ciphertext, secret, options));
    }
    return decrypted.get(key);
  };
  for (const [extensionTarget, stateKey] of [
    [{ kind: "root", expectedHeadDocHashHex: snapshot.root_doc_hash }, "root"],
    [
      { kind: "latest", expectedHeadDocHashHex: snapshot.extension_doc_hashes.extension_01 },
      "extension_01",
    ],
  ]) {
    const result = await recoverLatestFromEncryptedDocuments(documents, passphrase, decrypt, {
      extensionTarget,
    });
    assert.deepEqual(recoveredFileHashes(result.files), snapshot.states[stateKey]);
    assert.equal(result.trustBasis, "matched_expected_head");
    assert.equal(result.signingKeyVerified, true);
  }
  await assert.rejects(
    () =>
      recoverLatestFromEncryptedDocuments(documents, passphrase, decrypt, {
        extensionTarget: {
          kind: "latest",
          expectedHeadDocHashHex: snapshot.extension_doc_hashes.extension_02,
        },
      }),
    /does not match expected head/u,
  );
});
