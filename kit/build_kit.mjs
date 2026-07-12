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

import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { brotliCompressSync, constants as zlibConstants } from "node:zlib";

import { minify as terserMinify } from "terser";

import {
  compressedBundleName,
  DEFAULT_KIT_COMPRESSION,
  selectedCompressions,
} from "./lib/build_compression.mjs";
import { scannerHookPathForMode, selectedVariants } from "./lib/build_variants.mjs";
import { buildCompressedLoaderHtml } from "./lib/loader_html.js";
// 91 printable ASCII chars excluding double quote, backslash, and less-than.
// This keeps Base91 density while avoiding JS string and </script> escaping overhead.
const BASE91_ALPHABET =
  "!#$%&'()*+,-./0123456789:;=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_`abcdefghijklmnopqrstuvwxyz{|}~";
const DEFAULT_KIT_PROPERTY_MANGLE = "true";
const STYLE_TAG_RE = /<style\b[^>]*>([\s\S]*?)<\/style>/i;
const SCANNER_ONLY_CSS_RE =
  /\s*\/\* ETHERNITY_SCANNER_CSS_START \*\/[\s\S]*?\/\* ETHERNITY_SCANNER_CSS_END \*\//gu;
const CSS_CLASS_RE = /\.([A-Za-z_-][A-Za-z0-9_-]*)/g;
const CLASS_TOKEN_RE = /[a-z0-9_-]+/g;
const CLASS_VALUE_RE = /^[a-z0-9 _-]+$/;
const PRESERVE_CLASS_TOKENS = new Set(["ok", "warn", "error", "progress", "idle"]);
const CLASS_TOKEN_FIRST = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
const CLASS_TOKEN_NEXT = `${CLASS_TOKEN_FIRST}0123456789`;
const IDENTIFIER_LIKE_PROPERTY_RE = /^[A-Za-z_$][A-Za-z0-9_$]*$/;
const PROPERTY_MANGLE_RESERVED = [
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

function* classTokenGenerator() {
  for (const ch of CLASS_TOKEN_FIRST) {
    if (!PRESERVE_CLASS_TOKENS.has(ch)) {
      yield ch;
    }
  }
  for (const first of CLASS_TOKEN_FIRST) {
    for (const second of CLASS_TOKEN_NEXT) {
      const token = `${first}${second}`;
      if (!PRESERVE_CLASS_TOKENS.has(token)) {
        yield token;
      }
    }
  }
  for (const first of CLASS_TOKEN_FIRST) {
    for (const second of CLASS_TOKEN_NEXT) {
      for (const third of CLASS_TOKEN_NEXT) {
        const token = `${first}${second}${third}`;
        if (!PRESERVE_CLASS_TOKENS.has(token)) {
          yield token;
        }
      }
    }
  }
}

function buildClassMap(css) {
  const names = new Set();
  CSS_CLASS_RE.lastIndex = 0;
  let match = null;
  while (true) {
    match = CSS_CLASS_RE.exec(css);
    if (!match) {
      break;
    }
    const name = match[1];
    if (!PRESERVE_CLASS_TOKENS.has(name)) {
      names.add(name);
    }
  }
  const sorted = Array.from(names).sort();
  const map = {};
  const tokens = classTokenGenerator();
  for (const name of sorted) {
    const next = tokens.next();
    if (next.done) {
      throw new Error("ran out of class name tokens");
    }
    map[name] = next.value;
  }
  return map;
}

function replaceCssClasses(css, map) {
  CSS_CLASS_RE.lastIndex = 0;
  return css.replace(CSS_CLASS_RE, (full, name) => {
    const mapped = map[name];
    return mapped ? `.${mapped}` : full;
  });
}

function replaceClassTokens(value, map, classTokens) {
  if (!value || !CLASS_VALUE_RE.test(value)) return value;
  CLASS_TOKEN_RE.lastIndex = 0;
  let hasKnown = false;
  let hasToken = false;
  value.replace(CLASS_TOKEN_RE, (token) => {
    hasToken = true;
    if (classTokens.has(token)) {
      hasKnown = true;
    }
    return token;
  });
  if (!hasToken || !hasKnown) return value;
  CLASS_TOKEN_RE.lastIndex = 0;
  return value.replace(CLASS_TOKEN_RE, (token) => map[token] ?? token);
}

function readStringLiteral(source, start, map, classTokens) {
  const quote = source[start];
  let i = start + 1;
  while (i < source.length) {
    const ch = source[i];
    if (ch === "\\") {
      i += 2;
      continue;
    }
    if (ch === quote) break;
    i += 1;
  }
  const raw = source.slice(start + 1, i);
  const replaced = map ? replaceClassTokens(raw, map, classTokens) : raw;
  return { text: `${quote}${replaced}${quote}`, end: i + 1 };
}

function readTemplateExpression(source, start) {
  let i = start;
  let depth = 1;
  let out = "";
  while (i < source.length) {
    const ch = source[i];
    if (ch === "'" || ch === '"') {
      const parsed = readStringLiteral(source, i);
      out += parsed.text;
      i = parsed.end;
      continue;
    }
    if (ch === "`") {
      const parsed = readTemplateLiteral(source, i);
      out += parsed.text;
      i = parsed.end;
      continue;
    }
    if (ch === "/" && source[i + 1] === "/") {
      const end = source.indexOf("\n", i + 2);
      if (end === -1) {
        out += source.slice(i);
        return { text: out, end: source.length };
      }
      out += source.slice(i, end);
      i = end;
      continue;
    }
    if (ch === "/" && source[i + 1] === "*") {
      const end = source.indexOf("*/", i + 2);
      if (end === -1) {
        out += source.slice(i);
        return { text: out, end: source.length };
      }
      out += source.slice(i, end + 2);
      i = end + 2;
      continue;
    }
    if (ch === "{") depth += 1;
    if (ch === "}") {
      depth -= 1;
      out += ch;
      i += 1;
      if (depth === 0) {
        return { text: out, end: i };
      }
      continue;
    }
    out += ch;
    i += 1;
  }
  return { text: out, end: i };
}

function readTemplateLiteral(source, start, map, classTokens) {
  let i = start + 1;
  let out = "`";
  let chunkStart = i;
  while (i < source.length) {
    const ch = source[i];
    if (ch === "\\") {
      i += 2;
      continue;
    }
    if (ch === "`") {
      const chunk = source.slice(chunkStart, i);
      out += map ? replaceClassTokens(chunk, map, classTokens) : chunk;
      out += "`";
      return { text: out, end: i + 1 };
    }
    if (ch === "$" && source[i + 1] === "{") {
      const chunk = source.slice(chunkStart, i);
      out += map ? replaceClassTokens(chunk, map, classTokens) : chunk;
      out += "${";
      i += 2;
      const expr = readTemplateExpression(source, i);
      out += expr.text;
      i = expr.end;
      chunkStart = i;
      continue;
    }
    i += 1;
  }
  return { text: out, end: i };
}

function replaceClassNamesInJs(source, map, classTokens) {
  if (!map || !Object.keys(map).length) return source;
  let out = "";
  let i = 0;
  while (i < source.length) {
    const ch = source[i];
    if (ch === "'" || ch === '"') {
      const parsed = readStringLiteral(source, i, map, classTokens);
      out += parsed.text;
      i = parsed.end;
      continue;
    }
    if (ch === "`") {
      const parsed = readTemplateLiteral(source, i, map, classTokens);
      out += parsed.text;
      i = parsed.end;
      continue;
    }
    if (ch === "/" && source[i + 1] === "/") {
      const end = source.indexOf("\n", i + 2);
      if (end === -1) {
        out += source.slice(i);
        break;
      }
      out += source.slice(i, end);
      i = end;
      continue;
    }
    if (ch === "/" && source[i + 1] === "*") {
      const end = source.indexOf("*/", i + 2);
      if (end === -1) {
        out += source.slice(i);
        break;
      }
      out += source.slice(i, end + 2);
      i = end + 2;
      continue;
    }
    out += ch;
    i += 1;
  }
  return out;
}

function minifyClassNames(html, js) {
  const match = html.match(STYLE_TAG_RE);
  if (!match) {
    return { html, js };
  }
  const css = match[1];
  const map = buildClassMap(css);
  const classTokens = new Set([...Object.keys(map), ...PRESERVE_CLASS_TOKENS]);
  const replacedCss = replaceCssClasses(css, map);
  const updatedHtml = html.replace(STYLE_TAG_RE, (full) => full.replace(css, replacedCss));
  const updatedJs = replaceClassNamesInJs(js, map, classTokens);
  return { html: updatedHtml, js: updatedJs };
}

function htmlForBundleVariant(source, variant) {
  if (variant.scannerMode === "jsqr") {
    return source;
  }
  return source.replace(SCANNER_ONLY_CSS_RE, "");
}

function canonicalizeGzipHeader(gzBytes) {
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

async function gzipWithLibdeflate(rawBundle, tmpBase) {
  const inputPath = `${tmpBase}.libdeflate-input.html`;
  await writeFile(inputPath, rawBundle, "utf8");
  const levelRaw = process.env.ETHERNITY_KIT_LIBDEFLATE_LEVEL ?? "12";
  const level = Number.parseInt(levelRaw, 10);
  if (!Number.isInteger(level) || level < 1 || level > 12) {
    throw new Error(`invalid ETHERNITY_KIT_LIBDEFLATE_LEVEL: ${levelRaw}`);
  }
  const result = spawnSync("libdeflate-gzip", [`-${level}`, "-c", inputPath], {
    stdio: ["ignore", "pipe", "pipe"],
  });
  if (result.error && result.error.code === "ENOENT") {
    return null;
  }
  if (result.status !== 0) {
    const details = [result.stdout, result.stderr]
      .map((part) => (part ? Buffer.from(part).toString("utf8") : ""))
      .filter(Boolean)
      .join("\n")
      .trim();
    throw new Error(`libdeflate-gzip failed${details ? `: ${details}` : ""}`);
  }
  return canonicalizeGzipHeader(new Uint8Array(result.stdout));
}

async function gzipBundlePayload(rawBundle, tmpBase) {
  const requested = (process.env.ETHERNITY_KIT_GZIP_COMPRESSOR ?? "libdeflate").toLowerCase();
  if (requested !== "libdeflate") {
    throw new Error(
      "ETHERNITY_KIT_GZIP_COMPRESSOR must be 'libdeflate' (other compressors are not supported)",
    );
  }
  const libdeflateBytes = await gzipWithLibdeflate(rawBundle, tmpBase);
  if (!libdeflateBytes) {
    throw new Error("libdeflate-gzip CLI was not found in PATH");
  }
  return { bytes: libdeflateBytes, method: "libdeflate" };
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

async function minifyJsBundle(source, outputPath) {
  const mangle = { toplevel: true };
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

function buildScryptWorkerSource(tmpBase) {
  const workerEntry = resolve(kitDir, "lib", "age_scrypt_worker.js");
  const workerOutput = `${tmpBase}.scrypt-worker.js`;
  const result = spawnSync(
    "npx",
    [
      "--no-install",
      "esbuild",
      workerEntry,
      "--bundle",
      "--format=iife",
      "--platform=browser",
      "--target=es2020",
      "--minify",
      "--legal-comments=none",
      `--outfile=${workerOutput}`,
    ],
    { stdio: "inherit" },
  );
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
  return readFile(workerOutput, "utf8");
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
const scannerPanelImport = "#kit-scanner-panel";
const scannerHookLeanPath = resolve(kitDir, "app", "hooks", "useQrScannerRuntime.js");
const scannerHookJsqrPath = resolve(kitDir, "app", "hooks", "useQrScannerRuntime_jsqr.js");
const scannerPanelFullPath = resolve(kitDir, "app", "components", "QrScannerPanel.jsx");
const scannerPanelNonePath = resolve(kitDir, "app", "components", "QrScannerPanel_none.jsx");

await mkdir(distDir, { recursive: true });
await mkdir(packageDir, { recursive: true });

async function buildBundleVariant(variant) {
  const rawBundleName = variant.bundleName.replace(/\.html$/, ".raw.html");
  const rawOutputPath = resolve(distDir, rawBundleName);
  const tmpBase = resolve(tmpdir(), `ethernity-kit-${variant.id}-${Date.now()}`);
  const tmpOut = `${tmpBase}.min.js`;
  const scannerHookPath = scannerHookPathForMode(
    variant.scannerMode,
    scannerHookLeanPath,
    scannerHookJsqrPath,
  );
  const scannerPanelPath =
    variant.scannerMode === "jsqr" ? scannerPanelFullPath : scannerPanelNonePath;

  const scryptWorkerSource = await buildScryptWorkerSource(tmpBase);
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
    `--define:__ETHERNITY_SCRYPT_WORKER_SOURCE__=${JSON.stringify(scryptWorkerSource)}`,
    "--define:__ETHERNITY_SYNC_SCRYPT_ENABLED__=false",
    `--alias:microact=${microactIndexPath}`,
    `--alias:microact/hooks=${microactHooksPath}`,
    `--alias:microact/jsx-runtime=${microactJsxRuntimePath}`,
    `--alias:microact/jsx-dev-runtime=${microactJsxRuntimePath}`,
    `--alias:${scannerRuntimeImport}=${scannerHookPath}`,
    `--alias:${scannerPanelImport}=${scannerPanelPath}`,
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
  const minifiedClasses = minifyClassNames(variantHtml, minified);
  const inlined = minifiedClasses.html
    .replace(scriptTagRe, "")
    .replace("</body>", () => `<script>${minifiedClasses.js}</script>\n</body>`);

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
  const compressions = selectedCompressions(
    process.env.ETHERNITY_KIT_COMPRESSION ?? DEFAULT_KIT_COMPRESSION,
  );
  for (const compression of compressions) {
    const compressed =
      compression === "gzip"
        ? await gzipBundlePayload(rawBundle, tmpBase)
        : brotliBundlePayload(rawBundle);
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

for (const variant of selectedVariants(process.env.ETHERNITY_KIT_VARIANTS ?? "both")) {
  await buildBundleVariant(variant);
}
