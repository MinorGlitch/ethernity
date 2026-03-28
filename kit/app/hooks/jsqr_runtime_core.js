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

import jsQR from "jsqr";
import { normalizeJsQrPayload } from "../../lib/qr_scan_normalize.js";

function centerScanRegion(width, height) {
  const side = Math.max(32, Math.floor(Math.min(width, height) * 0.68));
  const x = Math.max(0, Math.floor((width - side) / 2));
  const y = Math.max(0, Math.floor((height - side) / 2));
  return { x, y, width: Math.min(side, width), height: Math.min(side, height) };
}

function readScanRegion(ctx, width, height, region = null) {
  if (region === null) {
    return { image: ctx.getImageData(0, 0, width, height), width, height };
  }
  return {
    image: ctx.getImageData(region.x, region.y, region.width, region.height),
    width: region.width,
    height: region.height,
  };
}

export function detectWithJsQr(video, canvas, ctx, detector = jsQR) {
  const width = video.videoWidth | 0;
  const height = video.videoHeight | 0;
  if (width <= 0 || height <= 0) return null;
  canvas.width = width;
  canvas.height = height;
  ctx.drawImage(video, 0, 0, width, height);

  const attempts = [centerScanRegion(width, height), null];
  for (const region of attempts) {
    const scanRegion = readScanRegion(ctx, width, height, region);
    const hit = detector(scanRegion.image.data, scanRegion.width, scanRegion.height, {
      inversionAttempts: "attemptBoth",
    });
    const normalized = normalizeJsQrPayload(hit);
    if (normalized !== null) {
      return normalized;
    }
  }
  return null;
}
