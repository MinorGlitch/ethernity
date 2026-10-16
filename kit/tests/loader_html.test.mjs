import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { TransformStream } from "node:stream/web";
import test from "node:test";
import vm from "node:vm";
import { brotliCompressSync, brotliDecompressSync, gunzipSync, gzipSync } from "node:zlib";

import { unpackKitHtml } from "./unpack_kit_test_helpers.mjs";

import { buildCompressedLoaderHtml, buildUnsupportedLoaderHtml } from "../lib/loader_html.js";

const BASE91_ALPHABET =
  'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!#$%&()*+,./:;<=>?@[]^_`{|}~"';

const TEST_DECOMPRESSORS = new Map([
  ["gzip", gunzipSync],
  ["brotli", brotliDecompressSync],
]);

class TestDecompressionStream {
  constructor(format) {
    const decompress = TEST_DECOMPRESSORS.get(format);
    if (!decompress) {
      throw new TypeError(`Unsupported test decompression format: ${format}`);
    }

    const chunks = [];
    const stream = new TransformStream({
      transform(chunk) {
        chunks.push(Buffer.from(chunk));
      },
      flush(controller) {
        controller.enqueue(decompress(Buffer.concat(chunks)));
      },
    });
    this.readable = stream.readable;
    this.writable = stream.writable;
  }
}

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

test("buildCompressedLoaderHtml renders fallback content when DecompressionStream is unavailable", async () => {
  const html = buildCompressedLoaderHtml({
    payloadBase91Safe: "abc123",
    alphabet: "abc123",
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
    Response,
    Uint8Array,
    document,
    window: {},
  });

  assert.match(written.join(""), /Recovery kit cannot open here/);
  assert.match(written.join(""), /DecompressionStream is unavailable/);
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

test("buildCompressedLoaderHtml rejects invalid compression values", () => {
  const validInputs = {
    payloadBase91Safe: "abc123",
    alphabet: BASE91_ALPHABET,
  };

  for (const compression of ["", null, false, 0, "zip"]) {
    assert.throws(
      () => buildCompressedLoaderHtml({ ...validInputs, compression }),
      /compression must be one of: gzip, brotli/,
    );
  }
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
  assert.match(html, /name="ethernity-kit-compression" content="gzip"/);
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
    DecompressionStream: TestDecompressionStream,
    Response,
    Uint8Array,
    document,
    window: { DecompressionStream: TestDecompressionStream },
  });

  assert.equal(written.join(""), sourceHtml);
});

test("buildCompressedLoaderHtml decodes and renders brotli payload", async () => {
  const sourceHtml = "<!doctype html><p>ok</p>";
  const payloadBase91Safe = base91Encode(brotliCompressSync(Buffer.from(sourceHtml))).replaceAll(
    "</",
    "<\\/",
  );
  const html = buildCompressedLoaderHtml({
    payloadBase91Safe,
    alphabet: BASE91_ALPHABET,
    compression: "brotli",
  });
  assert.match(html, /name="ethernity-kit-compression" content="brotli"/);
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
    DecompressionStream: TestDecompressionStream,
    Response,
    Uint8Array,
    document,
    window: { DecompressionStream: TestDecompressionStream },
  });

  assert.equal(written.join(""), sourceHtml);
});

test("generated recovery kit bundles decode to extension-capable UI", async () => {
  const bundlePaths = [
    "../../src/ethernity/resources/kit/recovery_kit.bundle.html",
    "../../src/ethernity/resources/kit/recovery_kit.scanner.bundle.html",
  ];

  for (const bundlePath of bundlePaths) {
    const html = await readFile(new URL(bundlePath, import.meta.url), "utf8");
    assert.match(html, /name="ethernity-kit-compression" content="gzip"/);
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
      DecompressionStream: TestDecompressionStream,
      Response,
      Uint8Array,
      document,
      window: { DecompressionStream: TestDecompressionStream },
    });

    const decoded = await unpackKitHtml(written.join(""));
    assert.match(decoded, /Version to recover/);
    assert.match(decoded, /Expected backup fingerprint/);
    assert.match(decoded, /I understand these pages may not include the newest update./);
    assert.match(decoded, /Recover original backup/);
    assert.match(decoded, /Use latest for the newest version added/);
  }
});
