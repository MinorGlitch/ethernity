import { readdir } from "node:fs/promises";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

async function collectTestFiles(rootDir) {
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

const testRoot = resolve("tests");
const testFiles = await collectTestFiles(testRoot);
const result = spawnSync(process.execPath, ["--test", ...testFiles], {
  stdio: "inherit",
});

process.exit(result.status ?? 1);
