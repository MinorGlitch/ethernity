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

import { useQrScannerRuntime } from "../hooks/useQrScannerRuntime.js";

export function QrScannerPanel({ onScanText }) {
  const {
    active,
    status,
    supported,
    scanCount,
    videoRef,
    startScanner,
    stopScanner,
  } = useQrScannerRuntime(onScanText);

  return (
    <div class="scan-panel">
      <div class="row">
        <button type="button" class="secondary" onClick={startScanner} disabled={active || !supported.ok}>
          Scan QR
        </button>
        <button type="button" class="ghost" onClick={stopScanner} disabled={!active}>
          Stop
        </button>
        <div class="hint">{scanCount ? `Scanned: ${scanCount}` : "Camera (optional)"}</div>
      </div>
      <video class="scan-video" ref={videoRef} muted hidden={!active} />
      {status ? <div class="hint scan-status">{status}</div> : null}
      {!supported.ok && !active ? <div class="hint scan-status">{supported.reason}</div> : null}
    </div>
  );
}
