import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { defaultTestRoot, runTests } from "../scripts/run_tests.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));

test("run_tests.mjs anchors discovery to kit/tests", () => {
  assert.equal(defaultTestRoot(), resolve(__dirname));
});

test("run_tests.mjs forwards node --test CLI filters", async () => {
  const tempRoot = await mkdtemp(resolve(tmpdir(), "ethernity-kit-tests-"));
  const testsDir = resolve(tempRoot, "tests");
  await mkdir(testsDir);
  await writeFile(
    resolve(testsDir, "match.test.mjs"),
    ["import test from 'node:test';", "test('forwarded only', () => {});", ""].join("\n"),
    { encoding: "utf8", flag: "wx" },
  );
  await writeFile(
    resolve(testsDir, "filtered-out.test.mjs"),
    [
      "import test from 'node:test';",
      "test('should stay filtered', () => { throw new Error('filter failed'); });",
      "",
    ].join("\n"),
    { encoding: "utf8", flag: "wx" },
  );

  let spawnCall = null;
  const result = await runTests({
    testRoot: testsDir,
    testArgs: ["--test-name-pattern=forwarded only"],
    execPath: "node",
    stdio: "pipe",
    spawn(execPath, args, options) {
      spawnCall = { execPath, args, options };
      return { status: 0 };
    },
  });

  assert.equal(result.status, 0);
  assert.deepEqual(spawnCall, {
    execPath: "node",
    args: [
      "--test",
      "--test-name-pattern=forwarded only",
      resolve(testsDir, "filtered-out.test.mjs"),
      resolve(testsDir, "match.test.mjs"),
    ],
    options: { stdio: "pipe" },
  });
});
