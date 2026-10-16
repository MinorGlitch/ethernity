/* Copyright (C) 2026 Alex Stoyanov. SPDX-License-Identifier: GPL-3.0-or-later */
import { gzipSync } from "node:zlib";
import { minify } from "terser";
import { mountKitAssembler } from "./kit_assembler.js";

// The two startup scans join at an HTML textarea boundary. Line breaks and spaces
// between scans are harmless, including inside the encoded JavaScript.
export async function buildAssemblerTemplate() {
  const result = await minify(`(${mountKitAssembler.toString()})(globalThis.K)`, {
    compress: { passes: 3 },
    mangle: { toplevel: true },
    format: { comments: false, ascii_only: true },
  });
  const loader = await minify(`(${openAssembler.toString()})()`);
  const payload = gzipSync(result.code, { level: 9 }).toString("base64");
  return `<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Assemble recovery kit</title><style>body{font:16px/1.5 system-ui;max-width:42rem;margin:2rem auto;padding:0 1rem}textarea{box-sizing:border-box;width:100%;height:8rem}button,input{font:inherit}button{padding:.5rem 1rem}#notice{color:#963e19}</style><h1>Assemble recovery kit</h1><p>Paste scans from QR 3 onwards, in any order. Duplicates are ignored.</p><label for=scans>Scanned text</label><textarea id=scans spellcheck=false></textarea><p><button id=add disabled>Add scans</button> <button id=save disabled>Save recovery kit</button></p><label>Import text files <input id=file type=file multiple accept=".txt,text/plain"></label><p id=status role=status>Opening assembly page...</p><p id=notice role=alert></p><script>globalThis.K=__KIT_CONFIG__;${loader.code}</script><textarea hidden id=code>${payload}`;
}

// Serialized into QR 1. QR 2 contains the compressed assembler source.
function openAssembler() {
  addEventListener("load", async () => {
    try {
      const encoded = document.getElementById("code").value.replace(/\s/g, "");
      const bytes = Uint8Array.from(atob(encoded), (char) => char.charCodeAt(0));
      const source = await new Response(
        new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip")),
      ).text();
      Function(source)();
      document.getElementById("add").disabled = false;
    } catch {
      document.getElementById("notice").textContent =
        "Cannot open assembly page. Check both startup scans and use a browser with gzip support.";
    }
  });
}
