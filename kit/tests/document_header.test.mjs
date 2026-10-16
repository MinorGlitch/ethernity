import assert from "node:assert/strict";
import test from "node:test";
import { readDocumentHeader } from "../app/document_header.js";
import { extractFiles } from "../app/backup_document.js";
import { decodeExtensionDocument } from "../app/extensions/document.js";
import { buildRootPlaintext, buildExtensionPlaintext } from "./extension_test_data.mjs";

const bytes = (...values) => Uint8Array.of(0x41, 0x59, ...values);

test("released v1 has an implicit backup kind without consuming body bytes", () => {
  assert.deepEqual(readDocumentHeader(bytes(1, 2)), { version: 1, kind: 1, bodyOffset: 3 });
});

test("v2 shares one version with distinct backup and update kinds", async () => {
  const files = [{ path: "f.txt", data: Uint8Array.of(1, 2, 3), mtime: null }];
  const root = buildRootPlaintext(files);
  assert.deepEqual(readDocumentHeader(root), { version: 2, kind: 1, bodyOffset: 4 });
  assert.equal((await extractFiles(root)).files.length, 1);
  await assert.rejects(decodeExtensionDocument(root), /expected update document kind/);
  const update = buildExtensionPlaintext({
    index: 1,
    rootDocHash: new Uint8Array(32),
    parentDocHash: new Uint8Array(32),
    files,
  });
  assert.deepEqual(readDocumentHeader(update), { version: 2, kind: 2, bodyOffset: 4 });
  assert.equal((await decodeExtensionDocument(update)).files.length, 1);
  await assert.rejects(extractFiles(update), /expected standalone backup document kind/);
  for (const doc of [root, update]) {
    const wrongKind = doc.slice();
    wrongKind[3] = doc[3] === 1 ? 2 : 1;
    await assert.rejects(
      wrongKind[3] === 1 ? extractFiles(wrongKind) : decodeExtensionDocument(wrongKind),
    );
  }
});

test("both readers reject missing, unknown, overflowing and noncanonical prefix fields", async () => {
  for (const prefix of [
    new Uint8Array(),
    bytes(),
    Uint8Array.of(0, 0, 2, 1),
    bytes(0),
    bytes(3),
    bytes(0x82, 0, 1),
    bytes(2),
    bytes(2, 0),
    bytes(2, 3),
    bytes(2, 0x81, 0),
    bytes(2, 0x82, 0),
    bytes(2, ...new Array(10).fill(0xff), 1),
  ]) {
    assert.throws(() => readDocumentHeader(prefix));
    await assert.rejects(extractFiles(prefix));
    await assert.rejects(decodeExtensionDocument(prefix));
  }
});
