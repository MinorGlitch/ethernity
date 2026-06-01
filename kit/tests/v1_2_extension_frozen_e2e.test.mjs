import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { sha256 } from "@noble/hashes/sha2.js";

import { recoverLatestFromEncryptedDocuments } from "../app/extension_recovery.js";
import { collectedRecoveryDocuments } from "../app/frames_cipher.js";
import { parseAutoPayload, parseAutoShard } from "../app/frames_parse.js";
import { verifyCollectedShardSignatures } from "../app/shard_auth.js";
import { autoRecoverShardSecret } from "../app/shards.js";
import { createInitialState } from "../app/state/initial.js";
import { decryptAgePassphrase } from "../lib/age_scrypt.js";
import { bytesToHex } from "../lib/encoding.js";
import { ensureAtob } from "./test_helpers.mjs";

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

function scenarioSnapshotPaths(profileName) {
  const profileRoot = path.join(FIXTURES_ROOT, profileName);
  const index = readJson(path.join(profileRoot, "index.json"));
  return index.scenarios.map((scenario) => path.join(profileRoot, scenario.path));
}

function recoveredFileHashes(files) {
  return Object.fromEntries(
    files
      .map((file) => [file.path, bytesToHex(sha256(file.data))])
      .sort(([left], [right]) => left.localeCompare(right)),
  );
}

async function restoreScenario(snapshotPath, { extensionTarget = "latest" } = {}) {
  const scenarioDir = path.dirname(snapshotPath);
  const snapshot = readJson(snapshotPath);
  const state = createInitialState();
  const payloadText = fs.readFileSync(
    path.join(scenarioDir, snapshot.payload_fixtures.chain.text),
    "utf8",
  );
  const added = parseAutoPayload(state, payloadText);
  assert.equal(added, snapshot.payload_fixtures.chain.frame_count);

  const documents = collectedRecoveryDocuments(state);
  const result = await recoverLatestFromEncryptedDocuments(
    documents,
    snapshot.passphrase,
    decryptAgePassphrase,
    { extensionTarget },
  );
  return { result, snapshot };
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
  );
  return { result, snapshot };
}

test("frozen v1.2 extension fixtures restore latest state in the kit", async (t) => {
  for (const profileName of ["base64", "raw"]) {
    for (const snapshotPath of scenarioSnapshotPaths(profileName)) {
      await t.test(`${profileName}/${path.basename(path.dirname(snapshotPath))}`, async () => {
        const { result, snapshot } = await restoreScenario(snapshotPath);
        const latestKey = latestStateKey(snapshot);
        assert.equal(result.selectedExtensionIndex, expectedExtensionIndex(latestKey));
        assert.equal(result.selectedExtensionDocHash, snapshot.extension_doc_hashes[latestKey]);
        assert.deepEqual(recoveredFileHashes(result.files), snapshot.states[latestKey]);
      });
    }
  }
});

test("frozen v1.2 shard fixtures unlock extension chains in the kit", async (t) => {
  const cases = [
    {
      name: "raw/extension_local_sharded_chain",
      payloadName: "extension_01",
      shardName: "extension",
    },
    {
      name: "raw/reuse_root_shards_chain",
      payloadName: "root",
      shardName: "root",
    },
  ];
  for (const item of cases) {
    await t.test(item.name, async () => {
      const snapshotPath = path.join(FIXTURES_ROOT, item.name, "snapshot.json");
      const passphrase = await recoverPassphraseFromShardFixture(snapshotPath, item);
      const { result, snapshot } = await restoreScenarioWithPassphrase(snapshotPath, passphrase);
      const latestKey = latestStateKey(snapshot);
      assert.equal(result.selectedExtensionIndex, expectedExtensionIndex(latestKey));
      assert.deepEqual(recoveredFileHashes(result.files), snapshot.states[latestKey]);
    });
  }
});

test("frozen v1.2 extension fixtures allow root-only kit recovery", async (t) => {
  for (const profileName of ["base64", "raw"]) {
    for (const snapshotPath of scenarioSnapshotPaths(profileName)) {
      await t.test(`${profileName}/${path.basename(path.dirname(snapshotPath))}`, async () => {
        const { result, snapshot } = await restoreScenario(snapshotPath, {
          extensionTarget: "root",
        });
        assert.equal(result.selectedExtensionIndex, null);
        assert.equal(result.selectedExtensionDocHash, null);
        assert.deepEqual(recoveredFileHashes(result.files), snapshot.states.root);
      });
    }
  }
});
