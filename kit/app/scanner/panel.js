/* Copyright (C) 2026 Alex Stoyanov. SPDX-License-Identifier: GPL-3.0-or-later */
import { createCamera } from "./camera.js";
import { setText } from "../ui/controls.js";

export const SCANNER_ENABLED = true;

export function createScanner(panel, onPayload) {
  panel.innerHTML = `<div class="row"><button type="button" class="secondary">Scan QR</button>
    <button type="button" class="ghost" hidden>Stop</button><div class="hint"></div></div>
    <div class="scan-preview" hidden><video class="scan-video" muted playsinline hidden></video><div class="scan-box" aria-hidden="true"></div></div>
    <div class="hint scan-status" role="status" hidden></div>`;
  const [start, stop] = panel.querySelectorAll("button");
  const count = panel.querySelector(".hint");
  const preview = panel.querySelector(".scan-preview");
  const video = panel.querySelector("video");
  const status = panel.querySelector(".scan-status");
  video.muted = true;
  const camera = createCamera(video, onPayload, (state) => {
    panel.classList.toggle(
      "scan-panel--expanded",
      state.active || Boolean(state.status) || !state.supported.ok,
    );
    start.disabled = state.active || !state.supported.ok;
    stop.disabled = !state.active;
    stop.hidden = !state.active;
    preview.hidden = !state.active;
    video.hidden = !state.active;
    setText(count, state.scanCount ? `Scanned: ${state.scanCount}` : "");
    setText(status, state.status || state.supported.reason);
    status.hidden = !status.textContent;
  });
  start.onclick = camera.start;
  stop.onclick = () => camera.stop("Camera stopped.");
  return camera;
}
