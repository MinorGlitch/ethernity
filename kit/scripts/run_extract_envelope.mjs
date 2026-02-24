import fs from "node:fs";
import path from "node:path";
import process from "node:process";

import { extractFiles } from "../app/envelope.js";

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

function main() {
  const input = process.argv[2];
  if (!input) {
    fail("usage: node kit/scripts/run_extract_envelope.mjs <envelope-bytes-file>");
  }
  const envelopePath = path.resolve(input);
  const envelopeBytes = new Uint8Array(fs.readFileSync(envelopePath));
  const result = extractFiles(envelopeBytes);
  const files = result.files.map(file => ({
    path: file.path,
    data_base64: Buffer.from(file.data).toString("base64"),
  }));
  process.stdout.write(`${JSON.stringify({ files })}\n`);
}

main();
