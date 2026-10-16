import { resolve } from "node:path";
import { chromium, firefox, webkit } from "playwright";
import { kitDir } from "../tests/browser/support.mjs";
import { smokeBackup, frozenBackups } from "../tests/browser/fixtures.mjs";
import { smokeBundle } from "../tests/browser/bundle.mjs";
import { checkPrintedMetadata } from "../tests/browser/metadata.mjs";
import { smokeUiLifecycle } from "../tests/browser/lifecycle.mjs";
import { smokeRecoveryWorker } from "../tests/browser/worker.mjs";

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
for (const name of browserNames) {
  const browser = await engines[name].launch({ headless: true });
  try {
    if (bundleSmokeCount) {
      for (const bundlePath of bundlePaths) {
        process.stdout.write(`Booting ${bundlePath} in ${name}...\n`);
        await smokeBundle(browser, bundlePath, backups, Boolean(printedKitDirectory));
        await checkPrintedMetadata(browser, bundlePath);
      }
    }
    await smokeUiLifecycle(browser);
    process.stdout.write(
      `${name}: DOM identity, UI disposal, and camera lifecycle checks passed.\n`,
    );
    await smokeRecoveryWorker(browser, backups);
    process.stdout.write(
      `${name}: ${printedKitDirectory ? "reconstructed printed" : "generated gzip"} kits passed: ${bundleSmokeCount}; recovery worker passed\n`,
    );
  } finally {
    await browser.close();
  }
}
