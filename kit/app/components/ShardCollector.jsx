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
  isAdding,
}) {
  const showDetails = shardDiagnostics.some((item) => item.tone === "error");
  const {
    pasteHint,
    handlePaste,
    handleChange: handleShardChange,
    handleAdd: handleAddShards,
    handleScanPayload,
  } = useCollectorInput({
    value: shardPayloadText,
    onChange: onShardPayloadChange,
    onAdd: onAddShardPayloads,
    onScannedPayload: onScannedShardPayload,
    scannedItemLabel: "shard frame",
  });
  const input = {
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
          spellCheck="false"
        />
        {SCANNER_ENABLED ? <QrScannerPanel onScanPayload={handleScanPayload} /> : null}
        {pasteHint ? <div class="hint">{pasteHint}</div> : null}
        <div class="hint">Skip if you have the full passphrase.</div>
      </>
    ),
    actions: [
      {
        label: isAdding ? "Adding..." : "Add shares",
        onClick: handleAddShards,
        disabled: isAdding,
      },
    ],
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
    <CollectorStep
      className="step-layout--status-right"
      input={input}
      status={status}
      output={output}
    />
  );
}
