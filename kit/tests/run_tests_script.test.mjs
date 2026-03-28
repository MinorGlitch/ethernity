import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import test from "node:test";

const __dirname = dirname(fileURLToPath(import.meta.url));
const RUN_TESTS_SCRIPT = resolve(__dirname, "..", "scripts", "run_tests.mjs");

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

  const result = spawnSync(
    process.execPath,
    [RUN_TESTS_SCRIPT, "--test-name-pattern=forwarded only"],
    {
      cwd: tempRoot,
      encoding: "utf8",
    },
  );

  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
});
