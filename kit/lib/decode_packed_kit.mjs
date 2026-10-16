/* Copyright (C) 2026 Alex Stoyanov. SPDX-License-Identifier: GPL-3.0-or-later */
import { Worker } from "node:worker_threads";

// Build/test verification uses the same worker source as the browser. Roadroller's
// globals stay in this disposable thread instead of a slow vm context proxy.
export async function decodePackedKit(source, timeoutMs = 30000) {
  const worker = new Worker(
    `const {parentPort}=require("node:worker_threads");
     const postMessage=text=>parentPort.postMessage(text);
     ${source}`,
    { eval: true },
  );
  let timeout;
  try {
    return await new Promise((resolve, reject) => {
      timeout = setTimeout(() => reject(Error("Packed kit decoder timed out")), timeoutMs);
      worker.once("message", resolve);
      worker.once("error", reject);
      worker.once("exit", (code) => {
        reject(Error(`Packed kit decoder exited without returning the app (code ${code})`));
      });
    });
  } finally {
    clearTimeout(timeout);
    await worker.terminate();
  }
}
