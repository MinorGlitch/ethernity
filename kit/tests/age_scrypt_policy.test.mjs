import assert from "node:assert/strict";
import test from "node:test";

import {
  decryptAgePassphrase,
  inspectAgeScryptWork,
  MAX_BROWSER_AGE_SCRYPT_LOG_N,
  MAX_RECOVERY_SCRYPT_WORK,
  MAX_SCRYPT_LOG_N,
  preflightAgeScryptBatch,
} from "../lib/age_scrypt.js";

function buildAgeScryptHeader(logN) {
  const salt = Buffer.alloc(16, 0x11).toString("base64").replaceAll("=", "");
  const body = Buffer.alloc(32, 0x22).toString("base64").replaceAll("=", "");
  const mac = Buffer.alloc(32, 0x33).toString("base64").replaceAll("=", "");
  return new TextEncoder().encode(
    `age-encryption.org/v1\n-> scrypt ${salt} ${logN}\n${body}\n--- ${mac}\n`,
  );
}

test("age scrypt preflight accepts writer profiles through the fixed browser limit", () => {
  assert.equal(MAX_SCRYPT_LOG_N, 20);
  assert.equal(MAX_BROWSER_AGE_SCRYPT_LOG_N, 20);
  for (const logN of [1, 10, 18, 19, 20]) {
    const profile = inspectAgeScryptWork(buildAgeScryptHeader(logN));
    assert.equal(profile.logN, logN);
    assert.equal(profile.work, 2 ** logN);
    assert.equal(profile.memoryBytes, 128 * 8 * (2 ** logN + 2));
    assert.deepEqual(preflightAgeScryptBatch([buildAgeScryptHeader(logN)]).errors, [null]);
  }
});

test("age scrypt preflight rejects profiles above the browser work limit", () => {
  for (const logN of [21, 30, 63]) {
    assert.throws(
      () => inspectAgeScryptWork(buildAgeScryptHeader(logN)),
      /scrypt work factor must be between 1 and 20/,
    );
  }
});

test("age scrypt batch preflight reports sequential peak memory and cumulative work", () => {
  const result = preflightAgeScryptBatch([buildAgeScryptHeader(19), buildAgeScryptHeader(20)]);
  assert.equal(result.totalWork, 2 ** 19 + 2 ** 20);
  assert.equal(result.peakMemoryBytes, 128 * 8 * (2 ** 20 + 2));
  assert.deepEqual(result.errors, [null, null]);
});

test("age scrypt preflight enforces cumulative work independently of document count", () => {
  for (const logN of [18, 19, 20]) {
    const count = MAX_RECOVERY_SCRYPT_WORK / 2 ** logN;
    const documents = Array.from({ length: count }, () => buildAgeScryptHeader(logN));
    assert.equal(preflightAgeScryptBatch(documents).totalWork, MAX_RECOVERY_SCRYPT_WORK);
    assert.throws(
      () => preflightAgeScryptBatch([...documents, buildAgeScryptHeader(logN)]),
      /cumulative scrypt work exceeds the recovery work limit/,
    );
  }
});

test("age scrypt batch preflight records unsupported documents without scheduling their work", () => {
  const result = preflightAgeScryptBatch([buildAgeScryptHeader(21), buildAgeScryptHeader(18)]);
  assert.equal(result.profiles[0], null);
  assert.equal(result.errors[0].code, "RECOVERY_RESOURCE_LIMIT");
  assert.match(result.errors[0].message, /scrypt work factor must be between 1 and 20/);
  assert.equal(result.profiles[1].logN, 18);
  assert.equal(result.totalWork, 2 ** 18);
});

test("age failure codes distinguish malformed input from rejected key authentication", async () => {
  await assert.rejects(
    decryptAgePassphrase(new Uint8Array(), "pw"),
    (error) => error.code === "DOCUMENT_INVALID" && error.stage === "source",
  );
  await assert.rejects(
    decryptAgePassphrase(buildAgeScryptHeader(1), "pw"),
    (error) => error.code === "PASSPHRASE_AUTH_FAILED" && error.stage === "unlock",
  );
});

test("scrypt cannot run on the browser UI thread", async (t) => {
  Object.defineProperty(globalThis, "window", { value: {}, configurable: true });
  t.after(() => delete globalThis.window);
  await assert.rejects(
    decryptAgePassphrase(buildAgeScryptHeader(1), "pw"),
    (error) => error.code === "SCRYPT_UNAVAILABLE",
  );
});

test("scrypt reports its work interval even when key authentication fails", async () => {
  const events = [];
  await assert.rejects(
    decryptAgePassphrase(buildAgeScryptHeader(1), "pw", {
      onScrypt: (active) => events.push(active),
    }),
    (error) => error.code === "PASSPHRASE_AUTH_FAILED",
  );
  assert.deepEqual(events, [true, false]);
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    decryptAgePassphrase(buildAgeScryptHeader(1), "pw", {
      signal: controller.signal,
      onScrypt: () => assert.fail("cancelled KDF was started"),
    }),
    (error) => error.code === "CANCELLED",
  );
});
