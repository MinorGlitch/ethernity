import assert from "node:assert/strict";
import test from "node:test";

import {
  inspectAgeScryptWork,
  INTENSIVE_SCRYPT_APPROVAL_PREFIX,
  MAX_AUTOMATIC_AGE_SCRYPT_LOG_N,
  MAX_AUTOMATIC_RECOVERY_SCRYPT_WORK,
  MAX_BROWSER_AGE_SCRYPT_LOG_N,
  MAX_COMPATIBILITY_RECOVERY_SCRYPT_WORK,
  MAX_SCRYPT_LOG_N,
  preflightAgeScryptBatch,
} from "../lib/age_scrypt.js";

function syntheticAgeDocument(logN) {
  const salt = Buffer.alloc(16, 0x11).toString("base64").replaceAll("=", "");
  const body = Buffer.alloc(32, 0x22).toString("base64").replaceAll("=", "");
  const mac = Buffer.alloc(32, 0x33).toString("base64").replaceAll("=", "");
  return new TextEncoder().encode(
    `age-encryption.org/v1\n-> scrypt ${salt} ${logN}\n${body}\n--- ${mac}\n`,
  );
}

test("age scrypt preflight accepts calibrated writer profiles through the browser limit", () => {
  assert.equal(MAX_SCRYPT_LOG_N, 20);
  assert.equal(MAX_BROWSER_AGE_SCRYPT_LOG_N, 20);
  assert.equal(MAX_AUTOMATIC_AGE_SCRYPT_LOG_N, 18);
  assert.equal(MAX_AUTOMATIC_RECOVERY_SCRYPT_WORK, 8 * 2 ** 18);
  for (const logN of [1, 10, 18, 19, 20]) {
    const profile = inspectAgeScryptWork(syntheticAgeDocument(logN));
    assert.equal(profile.logN, logN);
    assert.equal(profile.work, 2 ** logN);
    assert.equal(profile.memoryBytes, 128 * 8 * (2 ** logN + 2));
  }
});

test("age scrypt preflight rejects profiles above the browser work limit", () => {
  for (const logN of [21, 30, 63]) {
    assert.throws(
      () => inspectAgeScryptWork(syntheticAgeDocument(logN)),
      /scrypt work factor must be between 1 and 20/,
    );
  }
});

test("age scrypt batch preflight reports sequential peak memory and cumulative work", () => {
  const result = preflightAgeScryptBatch([syntheticAgeDocument(19), syntheticAgeDocument(20)], {
    allowResourceIntensive: true,
  });

  assert.equal(result.totalWork, 2 ** 19 + 2 ** 20);
  assert.equal(result.peakMemoryBytes, 128 * 8 * (2 ** 20 + 2));
  assert.deepEqual(result.errors, [null, null]);
  assert.equal(result.requiresResourceIntensiveApproval, true);
});

test("age scrypt preflight requires explicit approval before resource-intensive work", () => {
  assert.throws(
    () => preflightAgeScryptBatch([syntheticAgeDocument(20)]),
    new RegExp(`^Error: ${INTENSIVE_SCRYPT_APPROVAL_PREFIX}`),
  );

  const approved = preflightAgeScryptBatch([syntheticAgeDocument(20)], {
    allowResourceIntensive: true,
  });
  assert.equal(approved.requiresResourceIntensiveApproval, true);
});

test("age scrypt preflight gates cumulative automatic work independently of document count", () => {
  const exactAutomaticBudget = Array.from({ length: 8 }, () => syntheticAgeDocument(18));
  const aboveAutomaticBudget = [...exactAutomaticBudget, syntheticAgeDocument(18)];

  const accepted = preflightAgeScryptBatch(exactAutomaticBudget);
  assert.equal(accepted.requiresResourceIntensiveApproval, false);
  assert.throws(
    () => preflightAgeScryptBatch(aboveAutomaticBudget),
    new RegExp(`^Error: ${INTENSIVE_SCRYPT_APPROVAL_PREFIX}`),
  );
  const approved = preflightAgeScryptBatch(aboveAutomaticBudget, {
    allowResourceIntensive: true,
  });
  assert.equal(approved.requiresResourceIntensiveApproval, true);
});

test("age scrypt batch preflight records unsupported documents without scheduling their work", () => {
  const result = preflightAgeScryptBatch([syntheticAgeDocument(21), syntheticAgeDocument(18)]);

  assert.equal(result.profiles[0], null);
  assert.match(result.errors[0], /scrypt work factor must be between 1 and 20/);
  assert.equal(result.profiles[1].logN, 18);
  assert.equal(result.totalWork, 2 ** 18);
});

test("resource-intensive approval cannot bypass the cumulative hard limit", () => {
  const excessive = Array.from({ length: 9 }, () => syntheticAgeDocument(20));
  assert.throws(
    () => preflightAgeScryptBatch(excessive, { allowResourceIntensive: true }),
    new RegExp(`hard compatibility limit \\(${MAX_COMPATIBILITY_RECOVERY_SCRYPT_WORK}\\)`),
  );
});
