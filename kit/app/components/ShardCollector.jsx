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

import { DiagnosticsList, Field, StatusBlock } from "./common.jsx";
import { CollectorStep } from "./CollectorStep.jsx";
import { QrScannerPanel } from "./QrScannerPanel.jsx";

export function ShardCollector({
  shardPayloadText,
  shardStatus,
  shardDiagnostics,
  recoveredLabel,
  recoveredSecret,
  shardDocHash,
  shardDocId,
  shardSignPub,
  onShardPayloadChange,
  onAddShardPayloads,
  onScannedShardPayload,
  onCopyResult,
  canCopyResult,
  isComplete,
}) {
  const showDetails = shardDiagnostics.some((item) => item.tone === "error");
  const [pasteHint, setPasteHint] = useState("");
  const handlePaste = (event) => {
    const text = event.clipboardData?.getData("text/plain") ?? "";
    const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (lines.length) {
      setPasteHint(`Pasted ${lines.length} line(s). Click Add.`);
    }
  };
  const handleShardChange = (event) => {
    setPasteHint("");
    onShardPayloadChange(event);
  };
  const handleAddShards = () => {
    setPasteHint("");
    onAddShardPayloads();
  };
  const handleScanPayload = (scannedPayload) => {
    const hasBytes =
      scannedPayload &&
      scannedPayload.bytes instanceof Uint8Array &&
      scannedPayload.bytes.length > 0;
    if (hasBytes && typeof onScannedShardPayload === "function") {
      onScannedShardPayload(scannedPayload);
      setPasteHint("Scanned 1 shard frame. Added automatically.");
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
    const prefix = shardPayloadText && !shardPayloadText.endsWith("\n") ? "\n" : "";
    const nextValue = `${shardPayloadText ?? ""}${prefix}${lines.join("\n")}`;
    onShardPayloadChange({ currentTarget: { value: nextValue } });
    setPasteHint(`Scanned ${lines.length} line(s). Click Add.`);
  };
  const input = {
    title: "Recovery shares",
    body: (
      <>
        <Field
          id="shard-payload-text"
          label="Share text"
          value={shardPayloadText}
          placeholder="Paste shard text..."
          onInput={handleShardChange}
          onPaste={handlePaste}
          as="textarea"
        />
        <QrScannerPanel onScanPayload={handleScanPayload} />
        {pasteHint ? <div class="hint">{pasteHint}</div> : null}
        <div class="hint">Skip if you already have the full passphrase.</div>
      </>
    ),
    actions: [{ label: "Add shares", onClick: handleAddShards }],
    className: isComplete && !shardPayloadText.trim() ? "input-collapsed" : "",
  };
  const status = {
    title: "Status",
    body: (
      <>
        <StatusBlock status={shardStatus} />
        <DiagnosticsList items={shardDiagnostics} compact />
        <details class="details" open={showDetails}>
          <summary>All details</summary>
          <Field
            id="shard-doc-hash"
            label="Doc hash (hex)"
            value={shardDocHash}
            placeholder="32-byte hash..."
            readOnly
            className="code"
          />
          <Field
            id="shard-doc-id"
            label="Doc ID (hex)"
            value={shardDocId}
            placeholder="16-byte id..."
            readOnly
            className="code"
          />
          <Field
            id="shard-sign-pub"
            label="Signing public key (hex)"
            value={shardSignPub}
            placeholder="32-byte pubkey..."
            readOnly
            className="code"
          />
          <DiagnosticsList items={shardDiagnostics} />
        </details>
      </>
    ),
  };
  const output = {
    title: "Recovered secret",
    body: (
      <Field
        id="recovered-secret"
        label={recoveredLabel}
        value={recoveredSecret}
        placeholder="Recovered secret appears here..."
        readOnly
        as="textarea"
      />
    ),
    actions: [
      {
        label: "Copy secret",
        className: "secondary",
        onClick: onCopyResult,
        disabled: !canCopyResult,
        disabledReason: "Combine enough shares first.",
      },
    ],
  };
  return (
    <CollectorStep className="step-layout--status-right" input={input} status={status} output={output} />
  );
}
