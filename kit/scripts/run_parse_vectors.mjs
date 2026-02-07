import fs from "node:fs";
import path from "node:path";
import process from "node:process";

import { parseAutoPayload, parseAutoShard } from "../app/frames.js";
import { createInitialState } from "../app/state/initial.js";

if (typeof globalThis.atob !== "function") {
  globalThis.atob = (value) => Buffer.from(value, "base64").toString("binary");
}

function fixturePathFromArg() {
  if (process.argv[2]) {
    return path.resolve(process.argv[2]);
  }
  return path.resolve(process.cwd(), "tests/fixtures/recovery_parse_vectors.json");
}

function runPayloadCase(testCase) {
  const state = createInitialState();
  try {
    const added = parseAutoPayload(state, testCase.input);
    if (testCase.expect_error_contains) {
      return `${testCase.name}: expected error containing '${testCase.expect_error_contains}'`;
    }
    if (added !== testCase.expect_added) {
      return `${testCase.name}: expected added=${testCase.expect_added}, got ${added}`;
    }
    return null;
  } catch (error) {
    const message = String(error);
    if (!testCase.expect_error_contains) {
      return `${testCase.name}: unexpected error: ${message}`;
    }
    if (!message.includes(testCase.expect_error_contains)) {
      return (
        `${testCase.name}: expected error containing '${testCase.expect_error_contains}', ` +
        `got '${message}'`
      );
    }
    return null;
  }
}

function runShardCase(testCase) {
  const state = createInitialState();
  try {
    const added = parseAutoShard(state, testCase.input);
    if (testCase.expect_error_contains) {
      return `${testCase.name}: expected error containing '${testCase.expect_error_contains}'`;
    }
    if (added !== testCase.expect_added) {
      return `${testCase.name}: expected added=${testCase.expect_added}, got ${added}`;
    }
    return null;
  } catch (error) {
    const message = String(error);
    if (!testCase.expect_error_contains) {
      return `${testCase.name}: unexpected error: ${message}`;
    }
    if (!message.includes(testCase.expect_error_contains)) {
      return (
        `${testCase.name}: expected error containing '${testCase.expect_error_contains}', ` +
        `got '${message}'`
      );
    }
    return null;
  }
}

function main() {
  const fixturePath = fixturePathFromArg();
  const raw = fs.readFileSync(fixturePath, "utf8");
  const fixture = JSON.parse(raw);

  const failures = [];
  const payloadCases = Array.isArray(fixture.kit_payload_cases) ? fixture.kit_payload_cases : [];
  for (const testCase of payloadCases) {
    const failure = runPayloadCase(testCase);
    if (failure) {
      failures.push(failure);
    }
  }

  const shardCases = Array.isArray(fixture.kit_shard_cases) ? fixture.kit_shard_cases : [];
  for (const testCase of shardCases) {
    const failure = runShardCase(testCase);
    if (failure) {
      failures.push(failure);
    }
  }

  if (failures.length) {
    process.stderr.write(`parse vectors failed (${failures.length})\n`);
    for (const failure of failures) {
      process.stderr.write(`- ${failure}\n`);
    }
    process.exit(1);
  }

  process.stdout.write(
    `parse vectors passed (${payloadCases.length + shardCases.length} case(s))\n`
  );
}

main();
