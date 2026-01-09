import { useState } from "preact/hooks";

import { DiagnosticsList, Field, StatusBlock } from "./common.jsx";
import { CollectorStep } from "./CollectorStep.jsx";

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
      setPasteHint(`Pasted ${lines.length} line(s). Click Add shard frames.`);
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
  const input = {
    title: "Shard frames",
    body: (
      <>
        <Field
          id="shard-payload-text"
          label="Shard frames"
          value={shardPayloadText}
          placeholder="Paste shard frames or fallback text here..."
          onInput={handleShardChange}
          onPaste={handlePaste}
          as="textarea"
        />
        {pasteHint ? <div class="hint">{pasteHint}</div> : null}
      </>
    ),
    actions: [{ label: "Add shard frames", onClick: handleAddShards }],
    className: isComplete && !shardPayloadText.trim() ? "input-collapsed" : "",
  };
  const status = {
    title: "Status",
    body: (
      <>
        <StatusBlock status={shardStatus} />
        <details class="details" open={showDetails}>
          <summary>Validation details</summary>
          <Field
            id="shard-doc-hash"
            label="Doc hash (hex)"
            value={shardDocHash}
            placeholder="32-byte doc hash..."
            readOnly
            className="code"
          />
          <Field
            id="shard-doc-id"
            label="Doc ID (hex)"
            value={shardDocId}
            placeholder="16-byte doc id..."
            readOnly
            className="code"
          />
          <Field
            id="shard-sign-pub"
            label="Signing public key (hex)"
            value={shardSignPub}
            placeholder="32-byte signing public key..."
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
        placeholder="Recovered secret will appear here..."
        readOnly
        as="textarea"
      />
    ),
    actions: [
      {
        label: "Copy result",
        className: "secondary",
        onClick: onCopyResult,
        disabled: !canCopyResult,
        disabledReason: "Recover the secret first.",
      },
    ],
  };
  return (
    <CollectorStep className="step-layout--status-right" input={input} status={status} output={output} />
  );
}
