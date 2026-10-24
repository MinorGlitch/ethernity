import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";

export const kitDir = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

export async function waitForPageState(
  browser,
  pageUrl,
  { attempts, isReady, failureForState, timeoutMessage, onReady },
) {
  const page = await browser.newPage();
  try {
    // Local-file loading is intentional: WebKit workers have different Blob behavior here.
    await page.goto(pageUrl);
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const state = await page.evaluate(() => ({
        html: document.body?.innerHTML ?? "",
        text: document.body?.textContent ?? "",
      }));
      const failure = failureForState(state);
      if (failure) throw new Error(failure);
      if (isReady(state)) {
        await onReady?.(page);
        return;
      }
      await delay(100);
    }
    throw new Error(timeoutMessage);
  } finally {
    await page.close();
  }
}
