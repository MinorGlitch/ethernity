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

import { MAX_PATH_BYTES } from "../app/constants.js";

function utf8ByteLength(value) {
  return new TextEncoder().encode(value).length;
}

export function validateManifestPath(path, label = "manifest file path") {
  if (typeof path !== "string" || !path) {
    throw new Error(`${label} must be a non-empty string`);
  }
  const normalized = path.normalize("NFC");
  if (normalized.startsWith("/") || normalized.startsWith("\\")) {
    throw new Error(`${label} must be relative`);
  }
  if (/^[A-Za-z]:/.test(normalized)) {
    throw new Error(`${label} must be relative`);
  }
  if (normalized.includes("\\")) {
    throw new Error(`${label} must use POSIX separators ('/')`);
  }
  const segments = normalized.split("/");
  if (segments.some((segment) => segment.length === 0)) {
    throw new Error(`${label} must not contain empty path segments`);
  }
  if (segments.some((segment) => segment === "." || segment === "..")) {
    throw new Error(`${label} must not contain '.' or '..' path segments`);
  }
  const pathBytes = utf8ByteLength(normalized);
  if (pathBytes > MAX_PATH_BYTES) {
    throw new Error(
      `${label} exceeds MAX_PATH_BYTES (${MAX_PATH_BYTES} bytes): ${pathBytes} bytes`,
    );
  }
  return normalized;
}
