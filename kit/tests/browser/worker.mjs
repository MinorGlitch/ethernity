import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { kitDir, requireSuccessfulCommand, waitForPageState } from "./support.mjs";
import { minify as terserMinify } from "terser";
import { gzipCases } from "../gzip_test_data.mjs";

export async function smokeRecoveryWorker(browser, cases) {
  const workDir = await mkdtemp(resolve(tmpdir(), "ethernity-recovery-smoke-"));
  try {
    const appOutput = resolve(workDir, "app.js");
    requireSuccessfulCommand(
      spawnSync(
        "npx",
        [
          "--no-install",
          "esbuild",
          resolve(kitDir, "tests", "browser_recovery_worker_entry.mjs"),
          "--bundle",
          "--format=iife",
          "--platform=browser",
          "--target=es2020",
          "--minify",
          `--outfile=${appOutput}`,
        ],
        { cwd: kitDir, encoding: "utf8" },
      ),
      "recovery smoke app build",
    );
    const fixtures = Buffer.from(JSON.stringify(cases)).toString("base64");
    const gzipFixtures = Buffer.from(JSON.stringify(gzipCases())).toString("base64");
    const bundledAppSource = await readFile(appOutput, "utf8");
    const minifiedApp = await terserMinify(bundledAppSource, {
      compress: { passes: 2, toplevel: true },
      mangle: { toplevel: true },
    });
    if (!minifiedApp.code) {
      throw new Error("terser produced no recovery smoke app output");
    }
    const htmlPath = resolve(workDir, "index.html");
    await writeFile(
      htmlPath,
      `<!doctype html><body data-fixtures="${fixtures}" data-gzip="${gzipFixtures}">waiting<script>${minifiedApp.code}</script></body>`,
      "utf8",
    );
    await waitForPageState(browser, pathToFileURL(htmlPath).href, {
      attempts: 1200,
      isReady: ({ text }) => text.trim() === "worker-ok",
      failureForState: ({ text }) => (text.trim().startsWith("worker-error:") ? text.trim() : null),
      timeoutMessage: "Recovery worker did not complete within 120 seconds",
    });
  } finally {
    await rm(workDir, { recursive: true, force: true, maxRetries: 3 });
  }
}
