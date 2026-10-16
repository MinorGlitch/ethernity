import {
  configureRecoveryWorker,
  recoverInWorker,
  serveRecoveryWorker,
} from "../app/recovery_worker.js";
import { collectedRecoveryDocuments } from "../app/frames_cipher.js";
import { parseAutoPayload } from "../app/frames_parse.js";
import { createInitialState } from "../app/state/initial.js";
import { RecoveryError } from "../lib/errors.js";
import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "../lib/bytes.js";
import { gunzipBytesBounded } from "../lib/gzip.js";

function check(condition, message) {
  if (!condition) throw new Error(message);
}

async function rejectsCode(promise, code) {
  try {
    await promise;
  } catch (error) {
    check(error instanceof RecoveryError && error.code === code, `Expected ${code}: ${error}`);
    return;
  }
  throw new Error(`Expected ${code}, but recovery succeeded`);
}

async function run() {
  try {
    for (const sample of JSON.parse(atob(document.body.dataset.gzip))) {
      let decoded;
      let failure;
      try {
        decoded = await gunzipBytesBounded(Uint8Array.from(sample.bytes), sample.expectedLen);
      } catch (error) {
        failure = error;
      }
      if (sample.error) {
        check(failure?.message === sample.error, `gzip ${sample.name}: ${failure}`);
      } else {
        check(!failure, `gzip ${sample.name}: ${failure}`);
        check(
          bytesToHex(decoded) === bytesToHex(Uint8Array.from(sample.expected)),
          `gzip ${sample.name}: wrong bytes`,
        );
      }
    }
    const cases = JSON.parse(atob(document.body.dataset.fixtures));
    const options = { freshnessUnknownAcknowledged: true };
    for (const sample of cases) {
      const state = createInitialState();
      parseAutoPayload(state, sample.payload);
      const documents = collectedRecoveryDocuments(state);
      const recover = (extra = {}) =>
        recoverInWorker(documents, sample.passphrase, { ...options, ...extra });

      if (sample.expectedHashes) {
        const result = await recover();
        check(
          result.files.length === Object.keys(sample.expectedHashes).length,
          "Frozen backup file count",
        );
        for (const file of result.files) {
          check(
            bytesToHex(sha256(file.data)) === sample.expectedHashes[file.path],
            "Frozen backup file bytes",
          );
        }
        continue;
      }

      await rejectsCode(recoverInWorker(documents, "wrong", options), "PASSPHRASE_AUTH_FAILED");
      const controller = new AbortController();
      const cancelled = recover({ signal: controller.signal });
      controller.abort();
      await rejectsCode(cancelled, "CANCELLED");

      const result = await recover();
      check(result.files[0].data instanceof Uint8Array, "File bytes lost their type in transit");
      check(
        new TextDecoder().decode(result.files[0].data) === "recovered in browser",
        "Recovered root file bytes differ",
      );
      if (sample.updateMode) {
        check(result.updateMode === sample.updateMode, "Update mode changed");
        check(result.selectedExtensionIndex === 2, "Latest update was not selected");
        check(new TextDecoder().decode(result.files[1].data) === "update 2", "Wrong update data");
        const root = await recover({
          extensionTarget: { kind: "root", expectedHeadDocHashHex: documents[0].docHashHex },
        });
        check(root.files.length === 1 && root.selectedExtensionIndex === null, "Root selection");
        const selected = await recover({
          extensionTarget: {
            kind: "index",
            index: 1,
            expectedHeadDocHashHex: documents[1].docHashHex,
          },
        });
        check(selected.selectedExtensionIndex === 1, "Selected update was not restored");
        check(new TextDecoder().decode(selected.files[1].data) === "update 1", "Selected data");
      }
      const invalid = structuredClone(documents);
      invalid[0].authPayload.signature[0] ^= 1;
      await rejectsCode(
        recoverInWorker(invalid, sample.passphrase, options),
        "AUTH_SIGNATURE_INVALID",
      );
      check(documents[0].ciphertext.byteLength > 0, "Recovery detached collected ciphertext");
    }
    document.body.textContent = "worker-ok";
  } catch (err) {
    document.body.textContent = `worker-error:${err instanceof Error ? err.message : String(err)}`;
  }
}

if (typeof document === "undefined") {
  serveRecoveryWorker();
} else {
  configureRecoveryWorker(document.currentScript.textContent);
  void run();
}
