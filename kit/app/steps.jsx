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

import { DecryptSection } from "./components/DecryptSection.jsx";
import { FrameCollector } from "./components/FrameCollector.jsx";
import { RecoveredFiles } from "./components/RecoveredFiles.jsx";
import { ShardCollector } from "./components/ShardCollector.jsx";

export const STEPS = [
  {
    id: "frames",
    title: "Enter backup data",
    summary: "Paste the text from your recovery document or scanned QR codes. Include the verification code if available.",
    render: (ctx) => (
      <FrameCollector
        payloadText={ctx.state.payloadText}
        frameStatus={ctx.state.frameStatus}
        frameDiagnostics={ctx.frameDiagnostics}
        onPayloadChange={ctx.onPayloadChange}
        onAddPayloads={ctx.onAddPayloads}
        isComplete={Boolean(ctx.state.total && ctx.state.mainFrames.size === ctx.state.total)}
        onReset={ctx.onReset}
        onDownloadCipher={ctx.onDownloadCipher}
        canDownloadCipher={ctx.actionState.canDownloadCipher}
      />
    ),
  },
  {
    id: "shards",
    title: "Combine recovery shares",
    summary: "If your passphrase was split into shares, enter them here to reconstruct it. Skip this step if you have the full passphrase.",
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
        isComplete={Boolean(ctx.state.recoveredShardSecret)}
        onCopyResult={ctx.onCopyResult}
        canCopyResult={ctx.actionState.canCopyResult}
      />
    ),
  },
  {
    id: "decrypt",
    title: "Unlock & download",
    summary: "Enter your passphrase to decrypt and download your recovered files.",
    render: (ctx) => (
      <DecryptSection
        passphrase={ctx.state.agePassphrase}
        decryptStatus={ctx.state.decryptStatus}
        onPassphraseChange={ctx.onPassphraseChange}
        onDecrypt={ctx.onDecrypt}
        canDecrypt={ctx.actionState.canDecryptCiphertext}
        isComplete={ctx.actionState.hasOutput || Boolean(ctx.state.decryptedEnvelope)}
        isDecrypting={ctx.state.isDecrypting}
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
          recoveryComplete={ctx.state.recoveryComplete}
        />
      </DecryptSection>
    ),
  },
];
