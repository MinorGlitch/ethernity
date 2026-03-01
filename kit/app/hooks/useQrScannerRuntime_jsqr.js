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

import { useEffect, useRef, useState } from "microact/hooks";
import jsQR from "jsqr";
import { bytesToUnpaddedBase64 } from "../../lib/encoding.js";

function cameraSupportState() {
  if (typeof window === "undefined") return { ok: false, reason: "No browser context." };
  if (!navigator.mediaDevices?.getUserMedia) {
    return { ok: false, reason: "Camera API is not available. Paste text instead." };
  }
  if (window.isSecureContext === false) {
    return { ok: false, reason: "Camera scanning requires HTTPS or localhost. Paste text instead." };
  }
  return { ok: true, reason: "" };
}

function centerScanRegion(width, height) {
  const side = Math.max(32, Math.floor(Math.min(width, height) * 0.68));
  const x = Math.max(0, Math.floor((width - side) / 2));
  const y = Math.max(0, Math.floor((height - side) / 2));
  return { x, y, width: Math.min(side, width), height: Math.min(side, height) };
}

function _normalizeJsQrPayload(hit) {
  if (!hit) return null;
  const binaryData = hit.binaryData;
  if (binaryData && binaryData.length) {
    const bytes = binaryData instanceof Uint8Array ? binaryData : Uint8Array.from(binaryData);
    const encoded = bytesToUnpaddedBase64(bytes);
    if (encoded) return encoded;
  }
  const text = hit.data;
  if (typeof text === "string" && text.trim()) {
    return text.trim();
  }
  return null;
}

function detectWithJsQr(video, canvas, ctx) {
  const width = video.videoWidth | 0;
  const height = video.videoHeight | 0;
  if (width <= 0 || height <= 0) return null;
  canvas.width = width;
  canvas.height = height;
  ctx.drawImage(video, 0, 0, width, height);

  const region = centerScanRegion(width, height);
  const regionImage = ctx.getImageData(region.x, region.y, region.width, region.height);
  const centerHit = jsQR(regionImage.data, region.width, region.height, {
    inversionAttempts: "dontInvert",
  });
  return _normalizeJsQrPayload(centerHit);
}

export function useQrScannerRuntime(onScanText) {
  const [active, setActive] = useState(false);
  const [status, setStatus] = useState("");
  const [supported, setSupported] = useState(() => cameraSupportState());
  const [scanCount, setScanCount] = useState(0);
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const canvasRef = useRef(null);
  const canvasCtxRef = useRef(null);
  const stopRef = useRef(null);
  const timerRef = useRef(0);
  const sessionRef = useRef(0);

  const stopScanner = async () => {
    sessionRef.current += 1;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = 0;
    }
    const video = videoRef.current;
    if (video) {
      try {
        video.pause?.();
      } catch {}
      video.srcObject = null;
    }
    const stream = streamRef.current;
    streamRef.current = null;
    if (stream) {
      for (const track of stream.getTracks()) {
        track.stop();
      }
    }
    setActive(false);
  };
  stopRef.current = stopScanner;

  useEffect(() => () => {
    stopRef.current?.();
  }, []);

  useEffect(() => {
    if (!active) return;
    const video = videoRef.current;
    const stream = streamRef.current;
    if (!video || !stream || video.srcObject === stream) return;
    video.srcObject = stream;
    video.setAttribute("playsinline", "true");
    video.play?.().catch(() => {});
  });

  const startScanner = async () => {
    const support = cameraSupportState();
    setSupported(support);
    if (!support.ok) {
      setStatus(support.reason);
      return;
    }
    if (active) return;
    const sessionId = sessionRef.current + 1;
    sessionRef.current = sessionId;
    try {
      if (!canvasRef.current && typeof document !== "undefined") {
        canvasRef.current = document.createElement("canvas");
      }
      if (canvasRef.current && !canvasCtxRef.current) {
        canvasCtxRef.current = canvasRef.current.getContext("2d", { willReadFrequently: true });
      }
      if (!canvasRef.current || !canvasCtxRef.current) {
        throw new Error("QR scanner could not initialize.");
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: "environment" } },
      });
      if (sessionRef.current !== sessionId) {
        for (const track of stream.getTracks()) track.stop();
        return;
      }
      const video = videoRef.current;
      if (!video) {
        for (const track of stream.getTracks()) track.stop();
        throw new Error("Scanner preview is not ready.");
      }
      streamRef.current = stream;
      video.srcObject = stream;
      video.setAttribute("playsinline", "true");
      await video.play();
      setStatus("Camera active (jsQR). Align code in the box.");
      setActive(true);

      const scanLoop = async () => {
        if (!streamRef.current || !videoRef.current) return;
        if (sessionRef.current !== sessionId) return;
        try {
          const scannedText = detectWithJsQr(
            videoRef.current,
            canvasRef.current,
            canvasCtxRef.current
          );
          if (sessionRef.current !== sessionId || !streamRef.current || !videoRef.current) {
            return;
          }
          if (!scannedText || typeof scannedText !== "string" || !scannedText.trim()) {
            timerRef.current = window.setTimeout(scanLoop, 220);
            return;
          }
          onScanText(scannedText);
          setScanCount((value) => value + 1);
          setStatus("Scanned 1 QR (jsQR). Camera stopped.");
          await stopRef.current?.();
          return;
        } catch (error) {
          setStatus(error instanceof Error ? error.message : String(error));
          await stopRef.current?.();
          return;
        }
      };
      scanLoop();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
      await stopRef.current?.();
    }
  };

  const handleStop = () => {
    setStatus("Camera stopped.");
    stopRef.current?.();
  };

  return {
    active,
    status,
    supported,
    scanCount,
    videoRef,
    startScanner,
    stopScanner: handleStop,
  };
}
