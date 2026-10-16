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

export const DEFAULT_KIT_COMPRESSION = "gzip";

const SUPPORTED_COMPRESSIONS = new Set(["gzip", "brotli"]);

export function selectedCompressions(requested = DEFAULT_KIT_COMPRESSION) {
  const normalized = String(requested).toLowerCase();
  if (normalized === "both") {
    return [DEFAULT_KIT_COMPRESSION, "brotli"];
  }
  if (normalized === "brotli") {
    return [DEFAULT_KIT_COMPRESSION, "brotli"];
  }
  if (SUPPORTED_COMPRESSIONS.has(normalized)) {
    return [normalized];
  }
  throw new Error("ETHERNITY_KIT_COMPRESSION must be one of: gzip, brotli, both");
}

export function compressedBundleName(bundleName, compression) {
  const normalized = String(compression).toLowerCase();
  if (!SUPPORTED_COMPRESSIONS.has(normalized)) {
    throw new Error("compression must be one of: gzip, brotli");
  }
  if (normalized === DEFAULT_KIT_COMPRESSION) {
    return bundleName;
  }
  return bundleName.replace(/\.bundle\.html$/u, `.${normalized}.bundle.html`);
}
