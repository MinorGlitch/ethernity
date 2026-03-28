import { readdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const scriptPath = fileURLToPath(import.meta.url);
const scriptDir = dirname(scriptPath);
const packageDir = resolve(scriptDir, "..");

export function defaultTestRoot() {
  return resolve(packageDir, "tests");
}

export async function collectTestFiles(rootDir) {
  const entries = await readdir(rootDir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const fullPath = resolve(rootDir, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await collectTestFiles(fullPath)));
      continue;
    }
    if (entry.isFile() && entry.name.endsWith(".test.mjs")) {
      files.push(fullPath);
    }
  }
  return files.sort();
}

export async function runTests({
  testRoot = defaultTestRoot(),
  testArgs = process.argv.slice(2),
  execPath = process.execPath,
  spawn = spawnSync,
  stdio = "inherit",
} = {}) {
  const testFiles = await collectTestFiles(testRoot);
  return spawn(execPath, ["--test", ...testArgs, ...testFiles], {
    stdio,
  });
}

if (process.argv[1] && resolve(process.argv[1]) === scriptPath) {
  const result = await runTests();
  process.exit(result.status ?? 1);
}
