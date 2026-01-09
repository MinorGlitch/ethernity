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
}) {
  const input = {
    title: "Shard payloads",
    body: (
      <Field
        id="shard-payload-text"
        label="Shard inputs"
        value={shardPayloadText}
        placeholder="Paste shard payloads or fallback text here..."
        onInput={onShardPayloadChange}
        as="textarea"
      />
    ),
    actions: [{ label: "Add shard payloads", onClick: onAddShardPayloads }],
  };
  const status = {
    title: "Status &amp; validation",
    body: (
      <>
        <StatusBlock status={shardStatus} />
        <div class="label">Validation</div>
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
      { label: "Copy result", className: "secondary", onClick: onCopyResult, disabled: !canCopyResult },
    ],
  };
  return (
    <CollectorStep className="step-layout--status-right" input={input} status={status} output={output} />
  );
}
