import fs from "node:fs";
import path from "node:path";
import process from "node:process";

import { recoverLatestFromEncryptedDocuments } from "../app/extensions/recovery.js";
import { decryptAgePassphrase } from "../lib/age_scrypt.js";
import { bytesToHex } from "../lib/bytes.js";

if (typeof globalThis.atob !== "function") {
  globalThis.atob = (value) => Buffer.from(value, "base64").toString("binary");
}

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

function bytesFromBase64(value, label) {
  if (typeof value !== "string" || !value) {
    fail(`${label} must be base64 text`);
  }
  return new Uint8Array(Buffer.from(value, "base64"));
}

function authPayloadFromJson(value) {
  if (!value || typeof value !== "object") {
    return null;
  }
  return {
    version: value.version ?? 1,
    docHash: bytesFromBase64(value.doc_hash, "auth.doc_hash"),
    signPub: bytesFromBase64(value.sign_pub, "auth.sign_pub"),
    signature: bytesFromBase64(value.signature, "auth.signature"),
  };
}

function documentFromJson(value, index) {
  const ciphertext = bytesFromBase64(value?.ciphertext, `documents[${index}].ciphertext`);
  const docHash =
    value?.doc_hash === undefined || value?.doc_hash === null || value?.doc_hash === ""
      ? null
      : bytesFromBase64(value.doc_hash, `documents[${index}].doc_hash`);
  const document = {
    ciphertext,
    authPayload: authPayloadFromJson(value?.auth),
  };
  if (docHash) {
    document.docHash = docHash;
    document.docHashHex = bytesToHex(docHash);
  }
  return document;
}

function extensionTargetFromJson(fixture) {
  const value = fixture.extension_target ?? fixture.extensionTarget ?? "latest";
  if (value === null || value === "latest" || value === "root") {
    return value ?? "latest";
  }
  if (!value || typeof value !== "object") {
    fail("extension_target must be 'latest', 'root', or an object");
  }
  const expectedHeadDocHashHex = value.expectedHeadDocHashHex ?? value.expected_head_doc_hash_hex;
  if (value.kind === "latest" || value.kind === "root") {
    return { kind: value.kind, expectedHeadDocHashHex };
  }
  if (value.kind === "index") {
    return { kind: "index", index: value.index, expectedHeadDocHashHex };
  }
  if (value.kind === "doc_hash") {
    return {
      kind: "doc_hash",
      docHashHex: value.docHashHex ?? value.doc_hash_hex,
      expectedHeadDocHashHex,
    };
  }
  fail("unknown extension_target kind");
}

function freshnessUnknownAcknowledgedFromJson(fixture) {
  const value =
    fixture.freshnessUnknownAcknowledged ?? fixture.freshness_unknown_acknowledged ?? false;
  if (typeof value !== "boolean") {
    fail("freshness_unknown_acknowledged must be a boolean");
  }
  return value;
}

async function main() {
  const input = process.argv[2];
  if (!input) {
    fail("usage: node kit/scripts/run_recover_documents.mjs <documents-json-file>");
  }
  const fixturePath = path.resolve(input);
  const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
  if (!Array.isArray(fixture.documents)) {
    fail("documents must be an array");
  }
  const documents = fixture.documents.map(documentFromJson);
  const extensionTarget = extensionTargetFromJson(fixture);
  const freshnessUnknownAcknowledged = freshnessUnknownAcknowledgedFromJson(fixture);
  const result = await recoverLatestFromEncryptedDocuments(
    documents,
    fixture.passphrase,
    decryptAgePassphrase,
    {
      extensionTarget,
      freshnessUnknownAcknowledged,
      allowResourceIntensiveScrypt: true,
    },
  );
  const files = result.files.map((file) => ({
    path: file.path,
    data_base64: Buffer.from(file.data).toString("base64"),
  }));
  process.stdout.write(
    `${JSON.stringify({
      selected_extension_index: result.selectedExtensionIndex,
      selected_extension_doc_hash: result.selectedExtensionDocHash,
      freshness_scope: result.freshnessScope,
      freshness_decision: result.freshnessDecision,
      replay_target: result.replayTarget,
      manifest: {
        input_origin: result.manifest.inputOrigin,
        input_roots: result.manifest.inputRoots,
      },
      files,
    })}\n`,
  );
}

await main().catch((err) => {
  fail(err instanceof Error ? err.message : String(err));
});
