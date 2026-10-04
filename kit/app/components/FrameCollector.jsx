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

import { CollectorStep } from "./CollectorStep.jsx";
import { DiagnosticsList, Field, StatusBlock } from "./recovery_controls.jsx";
import { QrScannerPanel } from "#kit-scanner-panel";
import { SCANNER_ENABLED } from "#kit-scanner-runtime";
import { useCollectorInput } from "../hooks/useCollectorInput.js";

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
  downloadCipherDisabledReason,
  isComplete,
  isAdding,
}) {
  const showDetails = frameDiagnostics.some((item) => item.tone === "error");
  const {
    pasteHint,
    handlePaste,
    handleChange: handlePayloadChange,
    handleAdd: handleAddFrames,
    handleScanPayload,
  } = useCollectorInput({
    value: payloadText,
    onChange: onPayloadChange,
    onAdd: onAddPayloads,
    onScannedPayload,
    scannedItemLabel: "frame",
  });
  const input = {
    body: (
      <>
        <Field
          id="payload-text"
          label="Backup text"
          value={payloadText}
          placeholder="Paste backup text or AUTH..."
          onInput={handlePayloadChange}
          onPaste={handlePaste}
          as="textarea"
          spellCheck="false"
        />
        {SCANNER_ENABLED ? <QrScannerPanel onScanPayload={handleScanPayload} /> : null}
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
        disabledReason: downloadCipherDisabledReason ?? "Add all backup data first.",
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
