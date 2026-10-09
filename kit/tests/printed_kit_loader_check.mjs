import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

// Exercise the exact Python-generated startup codes and fragments, including their
// compression and checksums. The browser checks also exercise native downloads.
for (const item of JSON.parse(await readFile(process.argv[2], "utf8"))) {
  const script = item.shell.match(/<script>([\s\S]*?)<\/script>/)[1];
  const nodes = Object.fromEntries(
    ["scans", "status", "notice", "save", "add", "file", "code"].map((id) => [
      id,
      { value: "", textContent: "", disabled: id === "save" || id === "add" },
    ]),
  );
  nodes.code.value = `\n ${item.code.match(/.{1,71}/g).join("\r\n")} \t`;
  let load;
  let download;
  let decompressions = 0;
  const decoded = [];
  const context = vm.createContext({
    Uint8Array,
    Blob,
    Response,
    atob,
    DecompressionStream: item.unsupported
      ? undefined
      : class {
          constructor(format) {
            decompressions++;
            // Inspect arbitrary decoded bytes before gzip, using the real serialized
            // Base44 decoder. Startup decompression always uses the native stream.
            const stream =
              item.decoded_hex !== undefined && decompressions === 2
                ? new TransformStream({
                    transform(chunk, controller) {
                      decoded.push(chunk);
                      controller.enqueue(new TextEncoder().encode("decoded"));
                    },
                  })
                : new DecompressionStream(format);
            this.readable = stream.readable;
            this.writable = stream.writable;
          }
        },
    setTimeout() {},
    URL: {
      createObjectURL(blob) {
        download = blob;
        return "blob:test";
      },
      revokeObjectURL() {},
    },
    addEventListener(name, callback) {
      assert.equal(name, "load");
      load = callback;
    },
    document: {
      getElementById: (id) => nodes[id],
      createElement() {
        return {
          click() {
            assert.equal(this.download, "recovery_kit.bundle.html");
          },
        };
      },
    },
  });
  vm.runInContext(script, context);
  await load();
  if (!item.unsupported) {
    assert.equal(nodes.add.disabled, false, item.name);
    if (item.files)
      await nodes.file.onchange({ target: { files: item.files.map((text) => new Blob([text])) } });
    for (const scan of item.scans) {
      if (item.file) await nodes.file.onchange({ target: { files: [new Blob([scan])] } });
      else {
        nodes.scans.value = scan;
        nodes.add.onclick();
      }
    }
  }
  if (item.error) {
    assert.ok(
      nodes.notice.textContent.includes(item.error),
      `${item.name}: ${nodes.notice.textContent}`,
    );
    if (item.collected !== undefined)
      assert.ok(nodes.status.textContent.startsWith(`${item.collected} of`));
  } else if (item.missing) {
    assert.equal(nodes.save.disabled, true);
    assert.match(nodes.status.textContent, /Missing QR:/);
  } else {
    assert.equal(nodes.save.disabled, false, `${item.name}: ${nodes.notice.textContent}`);
    await nodes.save.onclick();
    if (item.save_error) {
      assert.equal(download, undefined);
      assert.match(nodes.notice.textContent, /Could not rebuild/);
      if (item.invalid_base44) assert.equal(decompressions, 1, item.name);
    } else {
      assert.equal(await download.text(), item.expected, item.name);
      assert.match(nodes.notice.textContent, /Saved/);
      if (item.decoded_hex !== undefined)
        assert.equal(Buffer.concat(decoded).toString("hex"), item.decoded_hex, item.name);
    }
  }
}
process.stdout.write("Printed kit assembler checks passed.\n");
