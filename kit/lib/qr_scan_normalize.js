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

import { bytesToUnpaddedBase64, decodePayloadString } from "./encoding.js";

function asciiFromBytes(bytes) {
  let text = "";
  for (const value of bytes) {
    if (value > 0x7f) return null;
    text += String.fromCharCode(value);
  }
  return text;
}

export function normalizeJsQrPayload(hit) {
  if (!hit) return null;
  const text = typeof hit.data === "string" ? hit.data.trim() : "";
  const binaryData = hit.binaryData;
  if (binaryData && binaryData.length) {
    const bytes = binaryData instanceof Uint8Array ? binaryData : Uint8Array.from(binaryData);
    if (text) {
      const textDecoded = decodePayloadString(text);
      if (textDecoded !== null) {
        const rawAscii = asciiFromBytes(bytes);
        const cleanedText = text.replace(/\s+/g, "");
        if (rawAscii !== null && rawAscii === cleanedText) {
          return text;
        }
      }
    }
    const encoded = bytesToUnpaddedBase64(bytes);
    if (encoded) return encoded;
  }
  if (text) return text;
  return null;
}
