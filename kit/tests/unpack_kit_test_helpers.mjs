import assert from "node:assert/strict";
import vm from "node:vm";
import { decodePackedKit } from "../lib/decode_packed_kit.mjs";

const cache = new Map();

export function unpackKitHtml(html) {
  if (!cache.has(html)) cache.set(html, unpack(html));
  return cache.get(html);
}

async function unpack(html) {
  const decoder = html.match(/<script id=packed type=text\/plain>([\s\S]*?)<\/script>/)?.[1];
  assert.ok(decoder, "kit must contain the packed worker source");
  const loader = html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
  let workerSource;
  let terminated = false;
  let revoked = false;
  let finished;
  let failed;
  const result = new Promise((resolve, reject) => {
    finished = resolve;
    failed = reject;
  });
  const document = {
    getElementById(id) {
      if (id === "packed") return { textContent: decoder, remove() {} };
      return {
        set textContent(value) {
          failed(Error(value));
        },
      };
    },
    open() {},
    write(value) {
      assert.ok(terminated && revoked, "worker and blob must be released before app startup");
      finished(value);
    },
    close() {},
  };
  class Worker {
    constructor() {
      queueMicrotask(async () => {
        try {
          this.onmessage({ data: await decodePackedKit(await workerSource.text()) });
        } catch (error) {
          failed(error);
        }
      });
    }
    terminate() {
      terminated = true;
    }
  }
  vm.runInNewContext(loader, {
    Blob,
    document,
    Worker,
    URL: {
      createObjectURL(blob) {
        workerSource = blob;
        return "blob:test";
      },
      revokeObjectURL() {
        revoked = true;
      },
    },
  });
  return result;
}
