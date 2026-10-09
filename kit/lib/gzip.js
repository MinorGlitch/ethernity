/*
 * Copyright (C) 2026 Alex Stoyanov
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along with this program.
 * If not, see <https://www.gnu.org/licenses/>.
 */

import { concatByteParts } from "./bytes.js";

const GZIP_CHUNK_MESSAGES = [
  "gzip extension chunks require DecompressionStream support",
  "decoded chunk exceeds raw_len",
  "decoded chunk length does not match raw_len",
  "invalid gzip chunk",
];

export async function gunzipBytesBounded(
  bytes,
  expectedLen,
  [unsupported, tooLarge, wrongLength, invalid] = GZIP_CHUNK_MESSAGES,
) {
  if (typeof DecompressionStream !== "function") {
    throw new Error(unsupported);
  }
  // WebKit cannot read Blob streams inside workers started from local HTML files.
  // Feed bounded chunks so the reader can check output size between writes.
  let offset = 0;
  const input = new ReadableStream({
    pull(controller) {
      const end = Math.min(offset + 64 * 1024, bytes.length);
      controller.enqueue(bytes.subarray(offset, end));
      offset = end;
      if (offset === bytes.length) controller.close();
    },
  });
  // DecompressionStream validates gzip framing, checksums, and the single-member boundary.
  const stream = input.pipeThrough(new DecompressionStream("gzip"));
  const reader = stream.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      if (!(value instanceof Uint8Array)) continue;
      total += value.length;
      if (total > expectedLen) {
        throw new Error(tooLarge);
      }
      chunks.push(value);
    }
  } catch (err) {
    try {
      await reader.cancel();
    } catch {
      // Ignore cancellation failures while surfacing the primary decode error.
    }
    if (err instanceof Error && err.message === tooLarge) {
      throw err;
    }
    throw new Error(invalid);
  } finally {
    reader.releaseLock();
  }
  if (total !== expectedLen) {
    throw new Error(wrongLength);
  }
  return concatByteParts(chunks);
}
