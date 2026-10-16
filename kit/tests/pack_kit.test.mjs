import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import { packKitHtml } from "../lib/pack_kit.mjs";
import { unpackKitHtml } from "./unpack_kit_test_helpers.mjs";

const original = '<!doctype html><p>Recovery kit</p><script>document.title="Test"</script>';
const packed = await packKitHtml(original, "lean");

test("packed HTML restores the exact app and releases its worker", async () => {
  assert.equal(await unpackKitHtml(packed), original);
});

for (const variant of ["lean", "scanner"]) {
  test(`${variant} packing is deterministic and preserves the complete app`, async () => {
    const first = await packKitHtml(original, variant);
    assert.equal(await packKitHtml(original, variant), first);
    assert.equal(await unpackKitHtml(first), original);
  });
}

test("packing rejects an unknown variant instead of choosing the wrong preset", async () => {
  await assert.rejects(packKitHtml(original, "unknown"), /Unknown kit packing variant/);
});

for (const unavailable of [true, false]) {
  test(`packed loader reports ${unavailable ? "unavailable" : "failed"} workers`, () => {
    const status = { textContent: "Opening kit" };
    let worker;
    let revoked = false;
    let terminated = false;
    class Worker {
      constructor() {
        if (unavailable) throw Error("Workers unavailable");
        worker = this;
      }
      terminate() {
        terminated = true;
      }
    }
    const loader = packed.match(/<script>([\s\S]*?)<\/script>/)[1];
    vm.runInNewContext(loader, {
      Blob,
      Worker,
      document: {
        getElementById(id) {
          return id === "status" ? status : { textContent: "invalid decoder", remove() {} };
        },
        open() {
          assert.fail("A failed worker must not replace the page");
        },
      },
      URL: {
        createObjectURL: () => "blob:test",
        revokeObjectURL() {
          revoked = true;
        },
      },
    });
    if (!unavailable) worker.onerror();
    assert.match(status.textContent, /Could not open the kit/);
    assert.equal(revoked, true);
    assert.equal(terminated, !unavailable);
  });
}
