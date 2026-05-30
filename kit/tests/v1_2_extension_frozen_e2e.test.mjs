import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { sha256 } from "@noble/hashes/sha2.js";

import { recoverLatestFromEncryptedDocuments } from "../app/extension_recovery.js";
import { collectedRecoveryDocuments } from "../app/frames_cipher.js";
import { parseAutoPayload } from "../app/frames_parse.js";
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
