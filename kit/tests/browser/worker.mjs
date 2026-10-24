import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { build } from "esbuild";
import { kitDir, waitForPageState } from "./support.mjs";
import { minify as terserMinify } from "terser";
import { gzipCases } from "../gzip_test_data.mjs";

export async function prepareRecoveryWorker(workDir, cases) {
  const result = await build({
    entryPoints: [resolve(kitDir, "tests", "browser_recovery_worker_entry.mjs")],
    bundle: true,
    format: "iife",
    platform: "browser",
    target: "es2020",
    minify: true,
    write: false,
  });
  const fixtures = Buffer.from(JSON.stringify(cases)).toString("base64");
  const gzipFixtures = Buffer.from(JSON.stringify(gzipCases())).toString("base64");
  const minifiedApp = await terserMinify(result.outputFiles[0].text, {
    compress: { passes: 2, toplevel: true },
    mangle: { toplevel: true },
  });
  if (!minifiedApp.code) {
    throw new Error("terser produced no recovery smoke app output");
  }
  const htmlPath = resolve(workDir, "worker.html");
  await writeFile(
    htmlPath,
    `<!doctype html><body data-fixtures="${fixtures}" data-gzip="${gzipFixtures}">waiting<script>${minifiedApp.code}</script></body>`,
    "utf8",
  );
  return htmlPath;
}

export async function smokeRecoveryWorker(browser, htmlPath) {
  await waitForPageState(browser, pathToFileURL(htmlPath).href, {
    attempts: 1200,
    isReady: ({ text }) => text.trim() === "worker-ok",
    failureForState: ({ text }) => (text.trim().startsWith("worker-error:") ? text.trim() : null),
    timeoutMessage: "Recovery worker did not complete within 120 seconds",
  });
}
