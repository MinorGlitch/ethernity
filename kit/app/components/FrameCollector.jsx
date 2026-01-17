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

import { useState } from "preact/hooks";

import { DiagnosticsList, Field, StatusBlock } from "./common.jsx";
import { CollectorStep } from "./CollectorStep.jsx";

export function FrameCollector({
  payloadText,
  frameStatus,
  frameDiagnostics,
  onPayloadChange,
  onAddPayloads,
  onReset,
  onDownloadCipher,
  canDownloadCipher,
  isComplete,
}) {
  const showDetails = frameDiagnostics.some((item) => item.tone === "error");
  const [pasteHint, setPasteHint] = useState("");
  const handlePaste = (event) => {
    const text = event.clipboardData?.getData("text/plain") ?? "";
    const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (lines.length) {
      setPasteHint(`Pasted ${lines.length} line(s). Click Add frames.`);
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
  const input = {
    title: "Backup data",
    body: (
      <>
        <Field
          id="payload-text"
          label="Recovery text"
          value={payloadText}
          placeholder="Paste the text from your recovery document here (including the AUTH section if available)..."
          onInput={handlePayloadChange}
          onPaste={handlePaste}
          as="textarea"
        />
        {pasteHint ? <div class="hint">{pasteHint}</div> : null}
      </>
    ),
    actions: [{ label: "Add data", onClick: handleAddFrames }],
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
        <details class="details" open={showDetails}>
          <summary>Validation details</summary>
          <DiagnosticsList items={frameDiagnostics} />
        </details>
      </>
    ),
  };
  return (
    <CollectorStep className="step-layout--compact" input={input} status={status} />
  );
}
