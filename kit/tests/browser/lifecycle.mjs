import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { build } from "esbuild";
import { kitDir, waitForPageState } from "./support.mjs";

export async function prepareUiLifecycle(workDir) {
  const result = await build({
    entryPoints: [resolve(kitDir, "tests", "browser_ui_entry.mjs")],
    bundle: true,
    format: "iife",
    platform: "browser",
    target: "es2020",
    minify: true,
    write: false,
  });
  const htmlPath = resolve(workDir, "ui.html");
  await writeFile(
    htmlPath,
    `<!doctype html><body>waiting<script>${result.outputFiles[0].text}</script></body>`,
  );
  return htmlPath;
}

export async function smokeUiLifecycle(browser, htmlPath) {
  await waitForPageState(browser, pathToFileURL(htmlPath).href, {
    attempts: 100,
    isReady: ({ text }) => text === "ui-lifecycle-ok",
    failureForState: ({ text }) => (text.startsWith("ui-lifecycle-error:") ? text : null),
    timeoutMessage: "UI lifecycle checks timed out",
  });
}
