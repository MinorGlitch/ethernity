import fs from "node:fs";
import path from "node:path";
import process from "node:process";

import { extractFiles } from "../app/backup_document.js";

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

async function main() {
  const input = process.argv[2];
  if (!input) {
    fail("usage: node kit/scripts/run_extract_backup.mjs <document-bytes-file>");
  }
  const backupPath = path.resolve(input);
  const documentBytes = new Uint8Array(fs.readFileSync(backupPath));
  const result = await extractFiles(documentBytes);
  const files = result.files.map((file) => ({
    path: file.path,
    data_base64: Buffer.from(file.data).toString("base64"),
  }));
  process.stdout.write(`${JSON.stringify({ files })}\n`);
}

await main();
