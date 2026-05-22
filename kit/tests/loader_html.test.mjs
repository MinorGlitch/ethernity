import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import { gzipSync } from "node:zlib";

import { buildCompressedLoaderHtml, buildUnsupportedLoaderHtml } from "../lib/loader_html.js";

const BASE91_ALPHABET =
  'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!#$%&()*+,./:;<=>?@[]^_`{|}~"';

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

function extractLoaderScript(html) {
  const match = html.match(/<script>([\s\S]*)<\/script>/);
  assert.ok(match);
  return match[1];
}

test("buildUnsupportedLoaderHtml renders an explicit recovery fallback page", () => {
  const html = buildUnsupportedLoaderHtml();

  assert.match(html, /Recovery kit cannot open here/);
  assert.match(html, /DecompressionStream is unavailable/);
});

test("buildCompressedLoaderHtml renders fallback content when DecompressionStream is unavailable", () => {
  const html = buildCompressedLoaderHtml({
    payloadBase91Safe: "abc123",
    alphabet: "abc123",
  });

  assert.match(html, /renderFallback\(\);return;/);
  assert.match(html, /document\.write\(fallback\)/);
  assert.match(html, /DecompressionStream is unavailable/);
  assert.doesNotMatch(html, /DecompressionStream"\)in window\)\)return/);
});

test("buildCompressedLoaderHtml rejects missing loader payload inputs", () => {
  assert.throws(
    () => buildCompressedLoaderHtml({ alphabet: BASE91_ALPHABET }),
    /payloadBase91Safe must be a non-empty string/,
  );
  assert.throws(
    () => buildCompressedLoaderHtml({ payloadBase91Safe: "abc123" }),
    /alphabet must be a non-empty string/,
  );
});

test("buildCompressedLoaderHtml accepts legacy gzBase91Safe payload input", () => {
  const html = buildCompressedLoaderHtml({
    gzBase91Safe: "abc123",
    alphabet: "abc123",
  });

  assert.match(html, /const p="abc123"/);
});

test("buildCompressedLoaderHtml decodes and renders gzip payload", async () => {
  const sourceHtml = "<!doctype html><p>ok</p>";
  const payloadBase91Safe = base91Encode(gzipSync(Buffer.from(sourceHtml))).replaceAll(
    "</",
    "<\\/",
  );
  const html = buildCompressedLoaderHtml({
    payloadBase91Safe,
    alphabet: BASE91_ALPHABET,
  });
  const written = [];
  const document = {
    open() {
      written.length = 0;
    },
    write(value) {
      written.push(value);
    },
    close() {},
  };

  await vm.runInNewContext(extractLoaderScript(html), {
    Blob,
    DecompressionStream,
    Response,
    Uint8Array,
    document,
    window: { DecompressionStream },
  });

  assert.equal(written.join(""), sourceHtml);
});
