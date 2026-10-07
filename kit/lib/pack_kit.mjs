/* Copyright (C) 2026 Alex Stoyanov. SPDX-License-Identifier: GPL-3.0-or-later */
import assert from "node:assert/strict";
import { Packer } from "roadroller";
import { minify } from "terser";
import { decodePackedKit } from "./decode_packed_kit.mjs";

// Saved O2 results, with eleven contexts for each input. See docs/release_files.md
// for retuning; ordinary builds must not rerun the random parameter search.
const PACKING_PRESETS = {
  lean: {
    recipLearningRate: 1333,
    modelRecipBaseCount: 22,
    sparseSelectors: [0, 1, 2, 3, 7, 13, 25, 42, 86, 325, 402],
  },
  scanner: {
    recipLearningRate: 1218,
    modelRecipBaseCount: 20,
    sparseSelectors: [0, 1, 2, 3, 7, 13, 25, 30, 149, 226, 344],
  },
};

export async function packKitHtml(html, variant) {
  assert.ok(Object.hasOwn(PACKING_PRESETS, variant), `Unknown kit packing variant: ${variant}`);
  const packer = new Packer([{ data: html, type: "text", action: "write" }], {
    maxMemoryMB: 64,
    allowFreeVars: true,
    dynamicModels: 1,
    modelMaxCount: 4,
    precision: 15,
    ...PACKING_PRESETS[variant],
  });
  const { firstLine, secondLine } = packer.makeDecoder();
  const decoder = firstLine + secondLine;
  const worker = `const document={write:html=>postMessage(html)};${decoder}`;
  assert.equal(
    await decodePackedKit(worker),
    html,
    "Packed kit must reproduce the complete application exactly",
  );
  // Only the small loader runs on the page. Termination releases the decoder's model
  // arrays before recovery starts; the recovery app receives its original script.
  const loader = await minify(`(${openPackedKit.toString()})()`);
  const packed = `<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Ethernity Recovery Kit</title></head><body><style>body{font:16px/1.5 system-ui;max-width:38rem;margin:3rem auto;padding:0 1rem}</style><h1>Opening recovery kit</h1><p id=status role=status>Unpacking the app. This can take a few seconds on a slower computer.</p><script id=packed type=text/plain>${worker.replaceAll("</script", "<\\/script")}</script><script>${loader.code}</script></body></html>`;
  assert.ok(Buffer.byteLength(packed) <= 1000000, "Packed kit exceeds the printed assembler limit");
  return packed;
}

// Serialized into the generated file; do not capture build-time variables.
function openPackedKit() {
  let worker;
  let url;
  const fail = () => {
    worker?.terminate();
    if (url) URL.revokeObjectURL(url);
    document.getElementById("status").textContent =
      "Could not open the kit. Reopen this file or try another supported browser.";
  };
  try {
    const source = document.getElementById("packed");
    url = URL.createObjectURL(new Blob([source.textContent], { type: "text/javascript" }));
    source.remove();
    worker = new Worker(url);
    worker.onerror = fail;
    worker.onmessage = (event) => {
      worker.terminate();
      URL.revokeObjectURL(url);
      document.open();
      document.write(event.data);
      document.close();
    };
  } catch {
    fail();
  }
}
