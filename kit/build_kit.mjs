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
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
const BASE91_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!#$%&()*+,./:;<=>?@[]^_`{|}~\"";
const STYLE_TAG_RE = /<style\b[^>]*>([\s\S]*?)<\/style>/i;
const CSS_CLASS_RE = /\.([A-Za-z_-][A-Za-z0-9_-]*)/g;
const CLASS_TOKEN_RE = /[a-z0-9_-]+/g;
const CLASS_VALUE_RE = /^[a-z0-9 _-]+$/;
const PRESERVE_CLASS_TOKENS = new Set(["ok", "warn", "error", "progress", "idle"]);
const CLASS_TOKEN_FIRST = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
const CLASS_TOKEN_NEXT = `${CLASS_TOKEN_FIRST}0123456789`;

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
  while ((match = CSS_CLASS_RE.exec(css))) {
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
    if (ch === "'" || ch === "\"") {
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
    if (ch === "'" || ch === "\"") {
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

function canonicalizeGzipHeader(gzBytes) {
  if (gzBytes.length < 10) return gzBytes;
  // RFC 1952 OS byte is informational; normalize for deterministic cross-OS output.
  if (gzBytes[0] === 0x1f && gzBytes[1] === 0x8b) {
    gzBytes[9] = 0xff;
  }
  return gzBytes;
}

async function ensureTrailingNewline(path) {
  const text = await readFile(path, "utf8");
  if (!text.endsWith("\n")) {
    await writeFile(path, `${text}\n`, "utf8");
  }
}

const kitDir = resolve(fileURLToPath(new URL(".", import.meta.url)));
const inputPath = resolve(kitDir, process.argv[2] ?? "recovery_kit.html");
const bundleName = process.argv[3] ?? "recovery_kit.bundle.html";
const rawBundleName = bundleName.replace(/\.html$/, ".raw.html");

// Build outputs go to kit/dist/
const distDir = resolve(kitDir, "dist");
const rawOutputPath = resolve(distDir, rawBundleName);
const outputPath = resolve(distDir, bundleName);

// Canonical location for Python package (src/ethernity/kit/)
const packagePath = resolve(kitDir, "..", "src", "ethernity", "kit", bundleName);

await mkdir(distDir, { recursive: true });

const html = await readFile(inputPath, "utf8");
const scriptTagRe = /<script\b[^>]*>[\s\S]*?<\/script>/g;

const tmpBase = resolve(tmpdir(), `ethernity-kit-${Date.now()}`);
const tmpOut = `${tmpBase}.min.js`;
const entryPoint = resolve(kitDir, "app", "index.jsx");

const esbuildArgs = [
  entryPoint,
  "--bundle",
  "--format=iife",
  "--platform=browser",
  "--jsx=automatic",
  "--jsx-import-source=preact",
  "--target=es2020",
  "--minify",
  "--tree-shaking=true",
  "--legal-comments=none",
  "--define:process.env.NODE_ENV=\"production\"",
  `--outfile=${tmpOut}`,
];
const result = spawnSync("npx", ["--no-install", "esbuild", ...esbuildArgs], {
  stdio: "inherit",
});
if (result.status !== 0) {
  process.exit(result.status ?? 1);
}

const minified = await readFile(tmpOut, "utf8");
const minifiedClasses = minifyClassNames(html, minified);
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
const gzPayload = canonicalizeGzipHeader(gzipSync(Buffer.from(rawBundle, "utf8"), { level: 9 }));
const gzBase91 = base91Encode(gzPayload);
const gzBase91Safe = gzBase91.replaceAll("</", "<\\/");
const loaderHtml = `<!doctype html><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Ethernity Recovery Kit</title><script>(async()=>{const p=${JSON.stringify(gzBase91Safe)};if(!(\"DecompressionStream\"in window))return;const a=${JSON.stringify(BASE91_ALPHABET)};const d=t=>{let b=0,n=0,v=-1,o=[];for(let i=0;i<t.length;i++){const c=a.indexOf(t[i]);if(c===-1)continue;if(v<0){v=c;continue}v+=c*91;b|=v<<n;n+=(v&8191)>88?13:14;while(n>7){o.push(b&255);b>>=8;n-=8}v=-1}if(v>=0)o.push((b|v<<n)&255);return new Uint8Array(o)};const b=d(p);const ds=new DecompressionStream(\"gzip\");const s=new Blob([b]).stream().pipeThrough(ds);const t=await new Response(s).text();document.open();document.write(t);document.close();})();</script>`;

const tmpLoader = `${tmpBase}.loader.html`;
await writeFile(tmpLoader, loaderHtml, "utf8");
const loaderMinArgs = [...htmlMinArgs];
loaderMinArgs[loaderMinArgs.length - 2] = outputPath;
loaderMinArgs[loaderMinArgs.length - 1] = tmpLoader;
const loaderResult = spawnSync("npx", ["--no-install", "html-minifier-terser", ...loaderMinArgs], {
  stdio: "inherit",
});
if (loaderResult.status !== 0) {
  process.exit(loaderResult.status ?? 1);
}

await ensureTrailingNewline(rawOutputPath);
await ensureTrailingNewline(outputPath);

await mkdir(dirname(packagePath), { recursive: true });
await copyFile(outputPath, packagePath);

console.log(`Wrote ${rawOutputPath}`);
console.log(`Wrote ${outputPath}`);
console.log(`Wrote ${packagePath}`);
