import { DecryptSection } from "./components/DecryptSection.jsx";
import { FrameCollector } from "./components/FrameCollector.jsx";
import { RecoveredFiles } from "./components/RecoveredFiles.jsx";
import { ShardCollector } from "./components/ShardCollector.jsx";

export const STEPS = [
  {
    id: "frames",
    title: "Collect frames",
    render: (ctx) => (
      <FrameCollector
        payloadText={ctx.state.payloadText}
        frameStatus={ctx.state.frameStatus}
        frameDiagnostics={ctx.frameDiagnostics}
        onPayloadChange={ctx.onPayloadChange}
        onAddPayloads={ctx.onAddPayloads}
        onReset={ctx.onReset}
        onDownloadCipher={ctx.onDownloadCipher}
        canDownloadCipher={ctx.actionState.canDownloadCipher}
      />
    ),
  },
  {
    id: "shards",
    title: "Recover shards",
    render: (ctx) => (
      <ShardCollector
        shardPayloadText={ctx.state.shardPayloadText}
        shardStatus={ctx.state.shardStatus}
        shardDiagnostics={ctx.shardDiagnostics}
        recoveredLabel={ctx.recoveredLabel}
        recoveredSecret={ctx.state.recoveredShardSecret}
        shardDocHash={ctx.shardInputs.docHashHex}
        shardDocId={ctx.shardInputs.docIdHex}
        shardSignPub={ctx.shardInputs.signPubHex}
        onShardPayloadChange={ctx.onShardPayloadChange}
        onAddShardPayloads={ctx.onAddShardPayloads}
        onCopyResult={ctx.onCopyResult}
        canCopyResult={ctx.actionState.canCopyResult}
      />
    ),
  },
  {
    id: "decrypt",
    title: "Decrypt & extract",
    render: (ctx) => (
      <DecryptSection
        ciphertextSource={ctx.ciphertextSource}
        passphrase={ctx.state.agePassphrase}
        decryptStatus={ctx.state.decryptStatus}
        onPassphraseChange={ctx.onPassphraseChange}
        onDecrypt={ctx.onDecrypt}
        canDecrypt={ctx.actionState.canDecryptCiphertext}
        envelopeSource={ctx.envelopeSource}
        onExtract={ctx.onExtract}
        onDownloadEnvelope={ctx.onDownloadEnvelope}
        canExtract={ctx.actionState.canExtractEnvelope}
        canDownloadEnvelope={ctx.actionState.canDownloadEnvelope}
      >
        <RecoveredFiles
          extractStatus={ctx.state.extractStatus}
          outputSubtitle={ctx.outputSummary.subtitle}
          files={ctx.state.extractedFiles}
          onClearOutput={ctx.onClearOutput}
          onDownloadZip={ctx.onDownloadZip}
          onDownloadFile={ctx.onDownloadFile}
          hasOutput={ctx.actionState.hasOutput}
        />
      </DecryptSection>
    ),
  },
];
