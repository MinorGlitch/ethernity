/*
 * Copyright (C) 2026 Alex Stoyanov
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along with this program.
 * If not, see <https://www.gnu.org/licenses/>.
 */

import { copyFile, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { brotliCompressSync, gunzipSync, constants as zlibConstants } from "node:zlib";

import { minify as terserMinify } from "terser";
import { gzipAsync } from "@gfx/zopfli";

import {
  compressedBundleName,
  DEFAULT_KIT_COMPRESSION,
  selectedCompressions,
} from "./lib/build_compression.mjs";
import { scannerHookPathForMode, selectedVariants } from "./lib/build_variants.mjs";
import { buildCompressedLoaderHtml } from "./lib/loader_html.js";
import { buildAssemblerTemplate } from "./lib/assembler_html.mjs";
import { packKitHtml } from "./lib/pack_kit.mjs";
import { SUPPORTED_DOCUMENT_VERSIONS } from "./app/constants.js";
// 91 printable ASCII chars excluding double quote, backslash, and less-than.
// This keeps Base91 density while avoiding JS string and </script> escaping overhead.
const BASE91_ALPHABET =
  "!#$%&'()*+,-./0123456789:;=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_`abcdefghijklmnopqrstuvwxyz{|}~";
const DEFAULT_KIT_PROPERTY_MANGLE = "true";
const SCANNER_ONLY_CSS_RE =
  /\s*\/\* ETHERNITY_SCANNER_CSS_START \*\/[\s\S]*?\/\* ETHERNITY_SCANNER_CSS_END \*\//gu;
const IDENTIFIER_LIKE_PROPERTY_RE = /^[A-Za-z_$][A-Za-z0-9_$]*$/;
const PROPERTY_MANGLE_RESERVED = [
  // ReadableStream invokes this callback by name outside the bundled code.
  "pull",
  // The printed loader supplies these fields outside the JavaScript bundle.
  "capability",
  "supported_document_versions",
  "accept",
  "aria-atomic",
  "aria-label",
  "aria-live",
  "autofocus",
  "capture",
  "checked",
  "children",
  "class",
  "className",
  "colSpan",
  "cols",
  "currentTarget",
  "disabled",
  "download",
  "files",
  "for",
  "hidden",
  "href",
  "htmlFor",
  "id",
  "key",
  "multiple",
  "name",
  "onBlur",
  "onChange",
  "onClick",
  "onError",
  "onFocus",
  "onInput",
  "onKeyDown",
  "onKeyUp",
  "onLoad",
  "onSubmit",
  "placeholder",
  "preventScroll",
  "readOnly",
  "ref",
  "required",
  "role",
  "rows",
  "scrollLeft",
  "scrollTop",
  "selected",
  "selectionDirection",
  "selectionEnd",
  "selectionStart",
  "style",
  "tabIndex",
  "target",
  "title",
  "type",
  "value",
  "auth",
  "chunk_id",
  "chunk_refs",
  "codec",
  "created",
  "data",
  "doc_hash",
  "doc_hash_hex",
  "doc_id",
  "doc_id_hex",
  "entries",
  "error",
  "files",
  "hash",
  "index",
  "input_origin",
  "input_roots",
  "length",
  "labelAndSalt",
  "logN",
  "manifest",
  "mtime",
  "passphrase",
  "path",
  "path_encoding",
  "path_prefixes",
  "payload_codec",
  "payload_raw_len",
  "pub",
  "raw_len",
  "sealed",
  "seed",
  "set_id",
  "sha",
  "share",
  "share_count",
  "share_index",
  "sign_pub",
  "signature",
  "size",
  "threshold",
  "version",
];

function base91Encode(bytes) {
  let buffer = 0;
  let bits = 0;
  let out = "";
  for (const byte of bytes) {
    buffer |= byte << bits;
    bits += 8;
    if (bits > 13) {
      let value = buffer & 8191;
      if (value > 88) {
        buffer >>= 13;
        bits -= 13;
      } else {
        value = buffer & 16383;
        buffer >>= 14;
        bits -= 14;
      }
      out += BASE91_ALPHABET[value % 91] + BASE91_ALPHABET[Math.floor(value / 91)];
    }
  }
  if (bits) {
    out += BASE91_ALPHABET[buffer % 91];
    if (bits > 7 || buffer > 90) {
      out += BASE91_ALPHABET[Math.floor(buffer / 91)];
    }
  }
  return out;
}

function htmlForBundleVariant(source, variant) {
  if (variant.scannerMode === "jsqr") {
    return source;
  }
  return source.replace(SCANNER_ONLY_CSS_RE, "");
}

function normalizeGzipHeader(gzBytes) {
  if (gzBytes.length < 10) return gzBytes;
  // RFC 1952 mtime + OS bytes are informational; normalize for deterministic output.
  if (gzBytes[0] === 0x1f && gzBytes[1] === 0x8b) {
    gzBytes[4] = 0x00;
    gzBytes[5] = 0x00;
    gzBytes[6] = 0x00;
    gzBytes[7] = 0x00;
    gzBytes[9] = 0xff;
  }
  return gzBytes;
}

async function gzipBundlePayload(rawBundle) {
  const bytes = normalizeGzipHeader(
    await gzipAsync(Buffer.from(rawBundle), { numiterations: 100 }),
  );
  if (!gunzipSync(bytes).equals(Buffer.from(rawBundle, "utf8"))) {
    throw new Error("zopfli output did not reproduce the complete packed kit");
  }
  return { bytes, method: "zopfli-100" };
}

function brotliBundlePayload(rawBundle) {
  const input = Buffer.from(rawBundle, "utf8");
  const bytes = brotliCompressSync(input, {
    params: {
      [zlibConstants.BROTLI_PARAM_MODE]: zlibConstants.BROTLI_MODE_TEXT,
      [zlibConstants.BROTLI_PARAM_QUALITY]: 11,
      [zlibConstants.BROTLI_PARAM_SIZE_HINT]: input.length,
    },
  });
  return { bytes: new Uint8Array(bytes), method: "node:brotli-q11" };
}

function propertyManglingEnabled(requested = DEFAULT_KIT_PROPERTY_MANGLE) {
  const normalized = requested.toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) {
    return true;
  }
  if (["0", "false", "no", "off"].includes(normalized)) {
    return false;
  }
  throw new Error("ETHERNITY_KIT_MANGLE_PROPERTIES must be one of: true, false");
}

function readStaticStringLiteralValue(source, start) {
  const quote = source[start];
  let value = "";
  let i = start + 1;
  while (i < source.length) {
    const ch = source[i];
    if (ch === "\\") {
      return { value: null, end: skipStringLiteral(source, i + 2, quote) };
    }
    if (ch === quote) {
      return { value, end: i + 1 };
    }
    value += ch;
    i += 1;
  }
  return { value: null, end: i };
}

function skipStringLiteral(source, start, quote) {
  let i = start;
  while (i < source.length) {
    const ch = source[i];
    if (ch === "\\") {
      i += 2;
      continue;
    }
    if (ch === quote) {
      return i + 1;
    }
    i += 1;
  }
  return i;
}

function collectIdentifierLikeStringLiterals(source) {
  const names = new Set();
  let i = 0;
  while (i < source.length) {
    const ch = source[i];
    if (ch === "'" || ch === '"') {
      const parsed = readStaticStringLiteralValue(source, i);
      if (parsed.value && IDENTIFIER_LIKE_PROPERTY_RE.test(parsed.value)) {
        names.add(parsed.value);
      }
      i = parsed.end;
      continue;
    }
    i += 1;
  }
  return names;
}

function propertyMangleReservedNames(source) {
  return Array.from(
    new Set([...PROPERTY_MANGLE_RESERVED, ...collectIdentifierLikeStringLiterals(source)]),
  ).sort();
}

// A fixed order compresses these bundles better than frequency-weighted names.
// Terser still excludes reserved words and names already in scope.
function fixedIdentifier(index) {
  const alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ$_";
  let name = "";
  do {
    name += alphabet[index % alphabet.length];
    index = Math.floor(index / alphabet.length) - 1;
  } while (index >= 0);
  return name;
}

async function minifyJsBundle(source, outputPath) {
  const mangle = { toplevel: true, nth_identifier: { get: fixedIdentifier } };
  if (propertyManglingEnabled(process.env.ETHERNITY_KIT_MANGLE_PROPERTIES)) {
    mangle.properties = {
      keep_quoted: true,
      reserved: propertyMangleReservedNames(source),
    };
  }
  const result = await terserMinify(source, {
    compress: {
      passes: 3,
      toplevel: true,
    },
    ecma: 2020,
    mangle,
  });
  if (result.error) {
    throw result.error;
  }
  if (!result.code) {
    throw new Error("terser produced no JavaScript output");
  }
  await writeFile(outputPath, result.code, "utf8");
}

async function ensureTrailingNewline(path) {
  const text = await readFile(path, "utf8");
  if (!text.endsWith("\n")) {
    await writeFile(path, `${text}\n`, "utf8");
  }
}

const kitDir = resolve(fileURLToPath(new URL(".", import.meta.url)));
const inputPath = resolve(kitDir, process.argv[2] ?? "recovery_kit.html");
const distDir = resolve(kitDir, "dist");
const packageDir = resolve(kitDir, "..", "src", "ethernity", "resources", "kit");
const html = await readFile(inputPath, "utf8");
const scriptTagRe = /<script\b[^>]*>[\s\S]*?<\/script>/g;
const entryPoint = resolve(kitDir, "app", "index.jsx");
const microactIndexPath = resolve(kitDir, "lib", "microact", "index.js");
const microactHooksPath = resolve(kitDir, "lib", "microact", "hooks.js");
const microactJsxRuntimePath = resolve(kitDir, "lib", "microact", "jsx-runtime.js");
const scannerRuntimeImport = "#kit-scanner-runtime";
const scannerHookLeanPath = resolve(kitDir, "app", "hooks", "useQrScannerRuntime.js");
const scannerHookJsqrPath = resolve(kitDir, "app", "hooks", "useQrScannerRuntime_jsqr.js");

await mkdir(distDir, { recursive: true });
await mkdir(packageDir, { recursive: true });

async function buildBundleVariant(variant, workDir) {
  const rawBundleName = variant.bundleName.replace(/\.html$/, ".raw.html");
  const rawOutputPath = resolve(distDir, rawBundleName);
  const tmpBase = resolve(workDir, variant.id);
  const tmpOut = `${tmpBase}.min.js`;
  const scannerHookPath = scannerHookPathForMode(
    variant.scannerMode,
    scannerHookLeanPath,
    scannerHookJsqrPath,
  );
  const esbuildArgs = [
    entryPoint,
    "--bundle",
    "--format=iife",
    "--platform=browser",
    "--jsx=automatic",
    "--jsx-import-source=microact",
    "--target=es2020",
    "--minify",
    "--tree-shaking=true",
    "--legal-comments=none",
    '--define:process.env.NODE_ENV="production"',
    `--alias:microact=${microactIndexPath}`,
    `--alias:microact/hooks=${microactHooksPath}`,
    `--alias:microact/jsx-runtime=${microactJsxRuntimePath}`,
    `--alias:microact/jsx-dev-runtime=${microactJsxRuntimePath}`,
    `--alias:${scannerRuntimeImport}=${scannerHookPath}`,
    `--outfile=${tmpOut}`,
  ];
  const result = spawnSync("npx", ["--no-install", "esbuild", ...esbuildArgs], {
    stdio: "inherit",
  });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }

  const terserOut = `${tmpBase}.terser.js`;
  await minifyJsBundle(await readFile(tmpOut, "utf8"), terserOut);
  const minified = await readFile(terserOut, "utf8");
  const variantHtml = htmlForBundleVariant(html, variant);
  const metadata = JSON.stringify({
    capability: "ethernity-unanchored-rescue",
    version: 1,
    supported_document_versions: [...SUPPORTED_DOCUMENT_VERSIONS].sort(),
  });
  const inlined = variantHtml
    .replace(scriptTagRe, "")
    .replace(
      "</body>",
      () =>
        `<script>globalThis.__ETHERNITY_KIT_METADATA__??=${metadata};${minified}</script>\n</body>`,
    );

  const tmpHtml = `${tmpBase}.html`;
  await writeFile(tmpHtml, inlined, "utf8");

  const htmlMinArgs = [
    "--collapse-whitespace",
    "--remove-comments",
    "--remove-redundant-attributes",
    "--remove-script-type-attributes",
    "--remove-style-link-type-attributes",
    "--use-short-doctype",
    "--minify-css",
    "true",
    "-o",
    rawOutputPath,
    tmpHtml,
  ];
  const htmlResult = spawnSync("npx", ["--no-install", "html-minifier-terser", ...htmlMinArgs], {
    stdio: "inherit",
  });
  if (htmlResult.status !== 0) {
    process.exit(htmlResult.status ?? 1);
  }

  const rawBundle = await readFile(rawOutputPath, "utf8");
  const packedBundle = await packKitHtml(rawBundle, variant.id);
  await writeFile(rawOutputPath.replace(".raw.html", ".packed.html"), packedBundle);
  const compressions = selectedCompressions(
    process.env.ETHERNITY_KIT_COMPRESSION ?? DEFAULT_KIT_COMPRESSION,
  );
  for (const compression of compressions) {
    const compressed =
      compression === "gzip"
        ? await gzipBundlePayload(packedBundle)
        : brotliBundlePayload(packedBundle);
    console.log(
      `[${variant.id}] ${compression} compressor: ${compressed.method} (${compressed.bytes.length} bytes)`,
    );
    const payloadBase91 = base91Encode(compressed.bytes);
    const payloadBase91Safe = payloadBase91.replaceAll("</", "<\\/");
    const loaderHtml = buildCompressedLoaderHtml({
      payloadBase91Safe,
      alphabet: BASE91_ALPHABET,
      compression,
    });

    const targetBundleName = compressedBundleName(variant.bundleName, compression);
    const targetOutputPath = resolve(distDir, targetBundleName);
    const targetPackagePath = resolve(packageDir, targetBundleName);
    const tmpLoader = `${tmpBase}.${compression}.loader.html`;
    await writeFile(tmpLoader, loaderHtml, "utf8");
    const loaderMinArgs = [...htmlMinArgs];
    loaderMinArgs[loaderMinArgs.length - 2] = targetOutputPath;
    loaderMinArgs[loaderMinArgs.length - 1] = tmpLoader;
    const loaderResult = spawnSync(
      "npx",
      ["--no-install", "html-minifier-terser", ...loaderMinArgs],
      { stdio: "inherit" },
    );
    if (loaderResult.status !== 0) {
      process.exit(loaderResult.status ?? 1);
    }

    await ensureTrailingNewline(targetOutputPath);
    await copyFile(targetOutputPath, targetPackagePath);
    console.log(`[${variant.id}] Wrote ${targetOutputPath}`);
    console.log(`[${variant.id}] Wrote ${targetPackagePath}`);
  }

  await ensureTrailingNewline(rawOutputPath);
  console.log(`[${variant.id}] Wrote ${rawOutputPath}`);
}

const workDir = await mkdtemp(resolve(tmpdir(), "ethernity-kit-"));
try {
  const assembler = await buildAssemblerTemplate();
  await writeFile(resolve(distDir, "recovery_kit.assembler.html"), assembler);
  await writeFile(resolve(packageDir, "recovery_kit.assembler.html"), assembler);
  for (const variant of selectedVariants(process.env.ETHERNITY_KIT_VARIANTS ?? "both")) {
    await buildBundleVariant(variant, workDir);
  }
} finally {
  await rm(workDir, { recursive: true, force: true });
}
