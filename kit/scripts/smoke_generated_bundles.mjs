import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import { chromium, firefox, webkit } from "playwright";
import { kitDir } from "../tests/browser/support.mjs";
import { smokeBackup, frozenBackups } from "../tests/browser/fixtures.mjs";
import { smokeBundle } from "../tests/browser/bundle.mjs";
import { checkPrintedMetadata } from "../tests/browser/metadata.mjs";
import { prepareUiLifecycle, smokeUiLifecycle } from "../tests/browser/lifecycle.mjs";
import { prepareRecoveryWorker, smokeRecoveryWorker } from "../tests/browser/worker.mjs";

const printedKitDirectory = process.env.ETHERNITY_KIT_PRINTED_SMOKE_DIR;
const bundleDirectory =
  printedKitDirectory ?? resolve(kitDir, "..", "src", "ethernity", "resources", "kit");
const bundlePaths = [
  resolve(bundleDirectory, "recovery_kit.bundle.html"),
  resolve(bundleDirectory, "recovery_kit.scanner.bundle.html"),
];

const engines = { chromium, firefox, webkit };
const requestedBrowsers = process.argv.slice(2);
const browserNames = requestedBrowsers.length ? requestedBrowsers : ["chromium", "webkit"];
for (const name of browserNames) {
  if (!Object.hasOwn(engines, name)) throw new Error(`Unknown browser: ${name}`);
}
const backups = [
  ...[null, "incremental", "cumulative"].map(smokeBackup),
  ...(await frozenBackups()),
];
const bundleSmokeCount =
  process.env.ETHERNITY_KIT_BROWSER_SMOKE_WORKER_ONLY === "1" ? 0 : bundlePaths.length;
// Bound simultaneous browser and key-derivation memory use.
await test("generated recovery kits", { concurrency: 2 }, async (suite) => {
  const workDir = await mkdtemp(resolve(tmpdir(), "ethernity-browser-smoke-"));
  try {
    // Build identical test pages once. Each engine still runs every scenario in
    // its own browser, including both packed kit variants and real legacy KDFs.
    const lifecyclePage = await prepareUiLifecycle(workDir);
    const workerPage = await prepareRecoveryWorker(workDir, backups);
    await Promise.all(
      browserNames.map((name) =>
        suite.test(name, async () => {
          const browser = await engines[name].launch({ headless: true });
          try {
            if (bundleSmokeCount) {
              for (const bundlePath of bundlePaths) {
                process.stdout.write(`Booting ${bundlePath} in ${name}...\n`);
                await smokeBundle(browser, bundlePath, backups, Boolean(printedKitDirectory));
                await checkPrintedMetadata(browser, bundlePath);
              }
            }
            await smokeUiLifecycle(browser, lifecyclePage);
            process.stdout.write(
              `${name}: DOM identity, UI disposal, and camera lifecycle checks passed.\n`,
            );
            await smokeRecoveryWorker(browser, workerPage);
            process.stdout.write(
              `${name}: ${printedKitDirectory ? "reconstructed printed" : "generated gzip"} kits passed: ${bundleSmokeCount}; recovery worker passed\n`,
            );
          } finally {
            await browser.close();
          }
        }),
      ),
    );
  } finally {
    // Subtests finish even when a sibling fails, before shared fixtures go away.
    await rm(workDir, { recursive: true, force: true, maxRetries: 3 });
  }
});
