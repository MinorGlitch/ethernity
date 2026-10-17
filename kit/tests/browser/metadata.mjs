import { pathToFileURL } from "node:url";

export async function checkPrintedMetadata(browser, bundlePath) {
  const valid = {
    capability: "ethernity-unanchored-rescue",
    version: 1,
    supported_document_versions: [1, 2],
  };
  for (const [metadata, errorText] of [
    [valid, null],
    [{ ...valid, capability: "unknown" }, "unsupported recovery kit capability"],
    [
      { ...valid, supported_document_versions: [1] },
      "recovery kit does not support document version 2",
    ],
  ]) {
    const page = await browser.newPage();
    try {
      await page.addInitScript((value) => {
        globalThis.__ETHERNITY_KIT_METADATA__ = value;
      }, metadata);
      const error = errorText ? page.waitForEvent("pageerror") : null;
      await page.goto(pathToFileURL(bundlePath).href);
      if (error) {
        const actual = await error;
        if (!actual.message.includes(errorText)) throw actual;
      } else {
        await page.getByRole("button", { name: "Use while online", exact: true }).click();
        await page.locator("#payload-text").waitFor({ state: "visible" });
        await page.locator("#shard-payload-text").waitFor({ state: "visible" });
      }
    } finally {
      await page.close();
    }
  }
}
