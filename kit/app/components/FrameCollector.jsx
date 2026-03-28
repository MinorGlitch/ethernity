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

import { useState } from "microact/hooks";
import { CollectorStep } from "./CollectorStep.jsx";
import { DiagnosticsList, Field, StatusBlock } from "./common.jsx";
import { QrScannerPanel } from "./QrScannerPanel.jsx";

export function FrameCollector({
  payloadText,
  frameStatus,
  frameDiagnostics,
  onPayloadChange,
  onAddPayloads,
  onScannedPayload,
  onReset,
  onDownloadCipher,
  canDownloadCipher,
  isComplete,
  isAdding,
}) {
  const showDetails = frameDiagnostics.some((item) => item.tone === "error");
  const [pasteHint, setPasteHint] = useState("");
  const handlePaste = (event) => {
    const text = event.clipboardData?.getData("text/plain") ?? "";
    const lines = text
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    if (lines.length) {
      setPasteHint(`Pasted ${lines.length} line(s). Click Add.`);
    }
  };
  const handlePayloadChange = (event) => {
    setPasteHint("");
    onPayloadChange(event);
  };
  const handleAddFrames = () => {
    setPasteHint("");
    onAddPayloads();
  };
  const handleScanPayload = (scannedPayload) => {
    const hasBytes =
      scannedPayload &&
      scannedPayload.bytes instanceof Uint8Array &&
      scannedPayload.bytes.length > 0;
    if (hasBytes && typeof onScannedPayload === "function") {
      onScannedPayload(scannedPayload);
      setPasteHint("Scanned 1 frame. Added automatically.");
      return;
    }

    const lines = String(scannedPayload?.text ?? "")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    if (!lines.length) {
      setPasteHint("Scanned QR was empty.");
      return;
    }
    const prefix = payloadText && !payloadText.endsWith("\n") ? "\n" : "";
    const nextValue = `${payloadText ?? ""}${prefix}${lines.join("\n")}`;
    onPayloadChange({ currentTarget: { value: nextValue } });
    setPasteHint(`Scanned ${lines.length} line(s). Click Add.`);
  };
  const input = {
    body: (
      <>
        <Field
          id="payload-text"
          label="Backup text"
          value={payloadText}
          placeholder="Paste backup text (include AUTH if available)..."
          onInput={handlePayloadChange}
          onPaste={handlePaste}
          as="textarea"
          spellCheck="false"
        />
        <QrScannerPanel onScanPayload={handleScanPayload} />
        {pasteHint ? <div class="hint">{pasteHint}</div> : null}
      </>
    ),
    actions: [
      { label: isAdding ? "Adding..." : "Add data", onClick: handleAddFrames, disabled: isAdding },
    ],
    secondaryActions: [
      {
        label: "Download encrypted file",
        className: "secondary",
        onClick: onDownloadCipher,
        disabled: !canDownloadCipher,
        disabledReason: "Add all backup data first.",
      },
      { label: "Start over", className: "ghost", onClick: onReset },
    ],
    className: isComplete && !payloadText.trim() ? "input-collapsed" : "",
  };
  const status = {
    title: "Status",
    body: (
      <>
        <StatusBlock status={frameStatus} />
        <DiagnosticsList items={frameDiagnostics} compact />
        <details class="details" open={showDetails}>
          <summary>All details</summary>
          <DiagnosticsList items={frameDiagnostics} />
        </details>
      </>
    ),
  };
  return <CollectorStep className="step-layout--compact" input={input} status={status} />;
}
