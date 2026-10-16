/* Copyright (C) 2026 Alex Stoyanov. SPDX-License-Identifier: GPL-3.0-or-later */
import { detectWithJsQr } from "./decoder.js";
import { cameraErrorMessage } from "../recovery_messages.js";

function cameraSupportState() {
  if (!navigator.mediaDevices?.getUserMedia) {
    return { ok: false, reason: "This browser cannot use the camera. Paste the text instead." };
  }
  if (window.isSecureContext === false) {
    return {
      ok: false,
      reason:
        "Camera access is blocked on this page. Paste the text, or open the kit in a browser that allows camera access.",
    };
  }
  return { ok: true, reason: "" };
}

export function createCamera(video, onPayload, onChange, detect = detectWithJsQr) {
  let stream = null;
  let canvas;
  let context;
  let timer;
  let session = 0;
  let disposed = false;
  const state = { active: false, status: "", supported: cameraSupportState(), scanCount: 0 };
  const notify = () => onChange(state);
  function stop(status = "") {
    session += 1;
    clearTimeout(timer);
    timer = undefined;
    try {
      video.pause();
    } catch {}
    video.srcObject = null;
    if (stream) {
      for (const track of stream.getTracks()) track.stop();
      stream = null;
    }
    state.active = false;
    state.status = status;
    notify();
  }
  async function start() {
    if (disposed || state.active) return;
    state.supported = cameraSupportState();
    if (!state.supported.ok) {
      state.status = state.supported.reason;
      notify();
      return;
    }
    const currentSession = ++session;
    state.active = true;
    state.status = "Waiting for camera access.";
    notify();
    try {
      canvas ??= document.createElement("canvas");
      context ??= canvas.getContext("2d", { willReadFrequently: true });
      if (!context) throw new Error("QR scanner could not initialize.");
      const requested = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: "environment" } },
      });
      if (session !== currentSession) {
        for (const track of requested.getTracks()) track.stop();
        return;
      }
      stream = requested;
      video.srcObject = stream;
      await video.play();
      if (session !== currentSession) return;
      state.status = "Hold a QR code inside the box.";
      notify();
      function scan() {
        if (session !== currentSession || !stream) return;
        try {
          const payload = detect(video, canvas, context);
          if (payload?.text?.trim() || payload?.bytes?.length) {
            onPayload(payload);
            if (session !== currentSession) return;
            state.scanCount += 1;
            stop("Scan complete. Select Scan QR for the next code.");
          } else {
            timer = window.setTimeout(scan, 220);
          }
        } catch (error) {
          if (session === currentSession) stop(cameraErrorMessage(error));
        }
      }
      scan();
    } catch (error) {
      if (session === currentSession) stop(cameraErrorMessage(error));
    }
  }
  notify();
  return {
    start,
    stop,
    dispose() {
      disposed = true;
      stop();
    },
  };
}
