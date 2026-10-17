import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { kitDir, requireSuccessfulCommand, waitForPageState } from "./support.mjs";

export async function smokeUiLifecycle(browser) {
  const workDir = await mkdtemp(resolve(tmpdir(), "ethernity-ui-smoke-"));
  try {
    const output = resolve(workDir, "ui.js");
    requireSuccessfulCommand(
      spawnSync(
        "npx",
        [
          "--no-install",
          "esbuild",
          resolve(kitDir, "tests", "browser_ui_entry.mjs"),
          "--bundle",
          "--format=iife",
          "--platform=browser",
          "--target=es2020",
          "--minify",
          `--outfile=${output}`,
        ],
        { cwd: kitDir, encoding: "utf8" },
      ),
      "UI lifecycle check build",
    );
    const htmlPath = resolve(workDir, "ui.html");
    await writeFile(
      htmlPath,
      `<!doctype html><body>waiting<script>${await readFile(output, "utf8")}</script></body>`,
    );
    await waitForPageState(browser, pathToFileURL(htmlPath).href, {
      attempts: 100,
      isReady: ({ text }) => text === "ui-lifecycle-ok",
      failureForState: ({ text }) => (text.startsWith("ui-lifecycle-error:") ? text : null),
      timeoutMessage: "UI lifecycle checks timed out",
    });
  } finally {
    await rm(workDir, { recursive: true, force: true, maxRetries: 3 });
  }
}
