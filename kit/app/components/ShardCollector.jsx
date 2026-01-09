import { ActionsRow, Card, DiagnosticsList, Field, StatusBlock } from "./common.jsx";

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
  const actions = [
    { label: "Add shard payloads", onClick: onAddShardPayloads },
    { label: "Copy result", className: "secondary", onClick: onCopyResult, disabled: !canCopyResult },
  ];
  return (
    <div class="step-layout">
      <Card title="Shard payloads" className="step-input">
        <Field
          id="shard-payload-text"
          label="Shard inputs"
          value={shardPayloadText}
          placeholder="Paste shard payloads or fallback text here..."
          onInput={onShardPayloadChange}
          as="textarea"
        />
      </Card>
      <div class="action-bar step-actions">
        <div class="label">Actions</div>
        <ActionsRow actions={actions} />
      </div>
      <Card title="Status &amp; validation" className="step-status">
        <StatusBlock status={shardStatus} />
        <div class="label">Validation details</div>
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
        <div class="label">Shard status</div>
        <DiagnosticsList items={shardDiagnostics} />
      </Card>
      <Card title="Recovered secret" className="step-output">
        <Field
          id="recovered-secret"
          label={recoveredLabel}
          value={recoveredSecret}
          placeholder="Recovered secret will appear here..."
          readOnly
          as="textarea"
        />
      </Card>
    </div>
  );
}
