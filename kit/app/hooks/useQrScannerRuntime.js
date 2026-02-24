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

function cameraSupportState() {
  if (typeof window === "undefined") return { ok: false, reason: "No browser context." };
  if (typeof window.BarcodeDetector !== "function") {
    return { ok: false, reason: "BarcodeDetector is not available. Paste text instead." };
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return { ok: false, reason: "Camera API is not available. Paste text instead." };
  }
  if (window.isSecureContext === false) {
    return { ok: false, reason: "Camera scanning requires HTTPS or localhost. Paste text instead." };
  }
  return { ok: true, reason: "" };
}

export function useQrScannerRuntime(onScanText) {
  const [active, setActive] = useState(false);
  const [status, setStatus] = useState("");
  const [supported, setSupported] = useState(() => cameraSupportState());
  const [scanCount, setScanCount] = useState(0);
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const detectorRef = useRef(null);
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
      if (!detectorRef.current) {
        if (typeof window.BarcodeDetector.getSupportedFormats === "function") {
          const formats = await window.BarcodeDetector.getSupportedFormats();
          if (sessionRef.current !== sessionId) return;
          if (!formats.includes("qr_code")) {
            const next = { ok: false, reason: "This browser camera scanner does not support QR codes." };
            setSupported(next);
            setStatus(next.reason);
            return;
          }
        }
        detectorRef.current = new window.BarcodeDetector({ formats: ["qr_code"] });
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
      setStatus("Camera active. Present one QR code.");
      setActive(true);

      const scanLoop = async () => {
        if (!streamRef.current || !videoRef.current || !detectorRef.current) return;
        if (sessionRef.current !== sessionId) return;
        try {
          const hits = await detectorRef.current.detect(videoRef.current);
          if (
            sessionRef.current !== sessionId ||
            !streamRef.current ||
            !videoRef.current ||
            !detectorRef.current
          ) {
            return;
          }
          const hit = hits.find((item) => typeof item?.rawValue === "string" && item.rawValue.trim());
          if (hit) {
            onScanText(hit.rawValue);
            setScanCount((value) => value + 1);
            setStatus("Scanned 1 QR. Camera stopped.");
            await stopRef.current?.();
            return;
          }
        } catch (error) {
          setStatus(error instanceof Error ? error.message : String(error));
          await stopRef.current?.();
          return;
        }
        timerRef.current = window.setTimeout(scanLoop, 180);
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
