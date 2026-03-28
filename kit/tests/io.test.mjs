import assert from "node:assert/strict";
import test from "node:test";

import { resolveExtractDownload } from "../app/actions_export.js";
import { downloadBlob } from "../app/io.js";

test("downloadBlob defers object URL cleanup until after click dispatch", () => {
  const calls = [];
  const originalDocument = globalThis.document;
  const originalUrl = globalThis.URL;
  const originalSetTimeout = globalThis.setTimeout;

  const anchor = {
    href: "",
    download: "",
    click() {
      calls.push("click");
    },
    remove() {
      calls.push("remove");
    },
  };

  let createdBlob = null;

  try {
    globalThis.document = {
      body: {
        appendChild(node) {
          assert.equal(node, anchor);
          calls.push("append");
        },
      },
      createElement(tag) {
        assert.equal(tag, "a");
        return anchor;
      },
    };
    globalThis.URL = {
      createObjectURL(blob) {
        createdBlob = blob;
        calls.push("create");
        return "blob:example";
      },
      revokeObjectURL(url) {
        calls.push(["revoke", url]);
      },
    };
    globalThis.setTimeout = (fn, delay) => {
      calls.push(["timeout", delay]);
      fn();
      return 1;
    };

    downloadBlob(new Blob(["payload"]), "example.bin");
  } finally {
    globalThis.document = originalDocument;
    globalThis.URL = originalUrl;
    globalThis.setTimeout = originalSetTimeout;
  }

  assert.ok(createdBlob instanceof Blob);
  assert.deepEqual(calls.slice(0, 3), ["create", "append", "click"]);
  assert.deepEqual(calls.slice(3), [["timeout", 1000], "remove", ["revoke", "blob:example"]]);
});

test("resolveExtractDownload zips nested manifest paths to preserve directory semantics", () => {
  const nestedFile = { path: "docs/a.txt", data: new Uint8Array([1, 2, 3]) };

  const download = resolveExtractDownload(nestedFile);

  assert.equal(download.kind, "zip");
  assert.equal(download.filename, "a.txt.zip");
  assert.ok(download.blob instanceof Blob);
});

test("resolveExtractDownload keeps root files as raw downloads", () => {
  const rootFile = { path: "a.txt", data: new Uint8Array([1, 2, 3]) };

  const download = resolveExtractDownload(rootFile);

  assert.deepEqual(download, {
    kind: "raw",
    filename: "a.txt",
    bytes: rootFile.data,
  });
});
