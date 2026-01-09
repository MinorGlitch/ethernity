import { ActionsRow, Card, Field, StatusBlock } from "./common.jsx";

export function DecryptSection({
  passphrase,
  decryptStatus,
  onPassphraseChange,
  onDecrypt,
  canDecrypt,
  isComplete,
  onExtract,
  onDownloadEnvelope,
  canExtract,
  canDownloadEnvelope,
  children,
}) {
  const decryptActions = [
    {
      label: "Decrypt & extract",
      onClick: onDecrypt,
      disabled: !canDecrypt,
      disabledReason: passphrase.trim() ? "Collect ciphertext to decrypt." : "Enter the passphrase to decrypt.",
    },
  ];
  const envelopeActions = [
    {
      label: "Extract files",
      onClick: onExtract,
      disabled: !canExtract,
      disabledReason: "Decrypt the ciphertext first.",
    },
    {
      label: "Download envelope",
      className: "secondary",
      onClick: onDownloadEnvelope,
      disabled: !canDownloadEnvelope,
      disabledReason: "Decrypt the ciphertext first.",
    },
  ];
  return (
    <div class="step-layout">
      <Card
        title="Unlock ciphertext"
        className={isComplete && !passphrase.trim() ? "step-input input-collapsed" : "step-input"}
      >
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
        <ActionsRow actions={envelopeActions} className="actions-secondary" />
        <StatusBlock status={decryptStatus} />
      </Card>
      <div class="step-output">
        {children}
      </div>
    </div>
  );
}
