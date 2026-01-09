import { ActionsRow, Card, Field, StatusBlock } from "./common.jsx";

export function DecryptSection({
  passphrase,
  decryptStatus,
  onPassphraseChange,
  onDecrypt,
  canDecrypt,
  onExtract,
  onDownloadEnvelope,
  canExtract,
  canDownloadEnvelope,
  children,
}) {
  const decryptActions = [
    { label: "Decrypt & extract", onClick: onDecrypt, disabled: !canDecrypt },
  ];
  const envelopeActions = [
    { label: "Extract files", onClick: onExtract, disabled: !canExtract },
    { label: "Download envelope", className: "secondary", onClick: onDownloadEnvelope, disabled: !canDownloadEnvelope },
  ];
  return (
    <div class="step-layout">
      <Card title="Unlock ciphertext" className="step-input">
        <Field
          id="passphrase-input"
          label="Passphrase"
          value={passphrase}
          placeholder="Passphrase..."
          onInput={onPassphraseChange}
          type="password"
        />
        <ActionsRow actions={decryptActions} />
      </Card>
      <Card title="Envelope status" className="step-status">
        <ActionsRow actions={envelopeActions} />
        <StatusBlock status={decryptStatus} />
      </Card>
      <div class="step-output">
        {children}
      </div>
    </div>
  );
}
