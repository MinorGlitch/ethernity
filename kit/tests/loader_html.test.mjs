import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { TransformStream } from "node:stream/web";
import test from "node:test";
import vm from "node:vm";
import { brotliCompressSync, brotliDecompressSync, gunzipSync, gzipSync } from "node:zlib";

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

class NodeStub {
  constructor(type, text = "") {
    this.type = type;
    this.text = text;
    this.children = [];
    this.attributes = new Map();
    this.style = {};
    this.className = "";
    this.id = "";
    this.value = "";
    this.scrollLeft = 0;
    this.scrollTop = 0;
    this.listeners = {};
  }

  appendChild(child) {
    this.children.push(child);
    child.parentNode = this;
    return child;
  }

  replaceChildren(...nodes) {
    this.children = [];
    for (const node of nodes) {
      this.appendChild(node);
    }
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === "id") {
      this.id = String(value);
    }
  }

  addEventListener(name, handler) {
    this.listeners[name] ??= [];
    this.listeners[name].push(handler);
  }

  removeEventListener() {}

  contains(node) {
    return node === this || this.children.some((child) => child.contains?.(node));
  }

  querySelector(selector) {
    return selector.startsWith("#") ? this.findById(selector.slice(1)) : null;
  }

  findById(id) {
    if (this.id === id) {
      return this;
    }
    for (const child of this.children) {
      const found = child.findById?.(id);
      if (found) {
        return found;
      }
    }
    return null;
  }

  focus() {}

  get textContent() {
    if (this.type === "#text") {
      return this.text;
    }
    return this.children.map((child) => child.textContent ?? "").join("");
  }
}

async function renderRawKitHtml(rawHtml) {
  const root = new NodeStub("div");
  root.id = "app";
  const document = {
    activeElement: null,
    getElementById(id) {
      return id === "app" ? root : null;
    },
    createDocumentFragment() {
      return new NodeStub("#fragment");
    },
    createTextNode(text) {
      return new NodeStub("#text", text);
    },
    createElement(type) {
      return new NodeStub(type);
    },
  };

  vm.runInNewContext(extractLoaderScript(rawHtml), {
    ArrayBuffer,
    Blob,
    CSS: { escape: (value) => String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&") },
    DataView,
    DecompressionStream: TestDecompressionStream,
    HTMLElement: NodeStub,
    Map,
    Promise,
    Response,
    Set,
    TextDecoder,
    TextEncoder,
    URL: {
      createObjectURL() {
        return "blob:kit-test";
      },
      revokeObjectURL() {},
    },
    Uint8Array,
    clearTimeout,
    console,
    crypto: globalThis.crypto,
    document,
    navigator: {
      mediaDevices: {
        async getUserMedia() {
          return { getTracks: () => [] };
        },
      },
      onLine: false,
    },
    queueMicrotask,
    setTimeout,
    window: {
      addEventListener() {},
      clearTimeout,
      isSecureContext: true,
      removeEventListener() {},
      setTimeout,
    },
  });

  await new Promise((resolve) => setTimeout(resolve, 10));
  return root.textContent;
}

async function decodeGeneratedBundleHtml(html) {
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

  return written.join("");
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

    const decoded = written.join("");
    assert.match(decoded, /Recovery target/);
    assert.match(decoded, /Expected head/);
    assert.match(decoded, /Recover latest among supplied pages; freshness unknown/);
    assert.match(decoded, /Unlock root only/);
    assert.match(decoded, /latest, root, index, or doc hash/);
  }
});

test("generated raw recovery kit bundles boot the app shell", async () => {
  const bundlePaths = [
    "../../src/ethernity/resources/kit/recovery_kit.bundle.html",
    "../../src/ethernity/resources/kit/recovery_kit.scanner.bundle.html",
  ];

  for (const bundlePath of bundlePaths) {
    const html = await readFile(new URL(bundlePath, import.meta.url), "utf8");
    const rendered = await renderRawKitHtml(await decodeGeneratedBundleHtml(html));

    assert.match(rendered, /Recovery Kit/);
    assert.match(rendered, /Collect backup/);
    assert.match(rendered, /Status/);
  }
});
