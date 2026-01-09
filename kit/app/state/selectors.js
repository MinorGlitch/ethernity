import { listMissing } from "../frames.js";
import { SHARD_KEY_PASSPHRASE, SHARD_KEY_SIGNING_SEED } from "../constants.js";

export function formatBytes(value) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unitIdx = 0;
  while (size >= 1024 && unitIdx < units.length - 1) {
    size /= 1024;
    unitIdx += 1;
  }
  const precision = size >= 100 || unitIdx === 0 ? 0 : size >= 10 ? 1 : 2;
  return `${size.toFixed(precision)} ${units[unitIdx]}`;
}

function sumFrameBytes(frames) {
  let total = 0;
  for (const frame of frames.values()) {
    total += frame.data.length;
  }
  return total;
}

export function selectFrameDiagnostics(state) {
  const missing = state.total ? listMissing(state.total, state.mainFrames) : [];
  return [
    { label: "Doc ID", value: state.docIdHex ?? "(unknown)" },
    { label: "Frames", value: `${state.mainFrames.size}/${state.total ?? "?"}` },
    { label: "Missing", value: missing.length ? missing.join(", ") : "-" },
    { label: "Duplicates", value: `${state.duplicates}` },
    { label: "Conflicts", value: `${state.conflicts}` },
    { label: "Ignored", value: `${state.ignored}` },
    { label: "Errors", value: `${state.errors}` },
    { label: "Auth status (optional)", value: state.authStatus },
  ];
}

export function selectShardKeyLabel(state) {
  if (state.shardKeyType === SHARD_KEY_PASSPHRASE) return "passphrase";
  if (state.shardKeyType === SHARD_KEY_SIGNING_SEED) return "signing key";
  return "-";
}

export function selectRecoveredLabel(state) {
  if (state.shardKeyType === SHARD_KEY_SIGNING_SEED) {
    return "Recovered signing key (hex)";
  }
  if (state.shardKeyType === SHARD_KEY_PASSPHRASE) {
    return "Recovered passphrase";
  }
  return "Recovered secret";
}

export function selectShardMatch(state) {
  if (state.docIdHex && state.shardDocIdHex) {
    return state.docIdHex === state.shardDocIdHex ? "yes" : "no";
  }
  return "-";
}

export function selectShardInputs(state) {
  return {
    docIdHex: state.shardDocIdHex || state.docIdHex || state.authDocIdHex || "",
    docHashHex: state.shardDocHashHex || state.authDocHashHex || state.cipherDocHashHex || "",
    signPubHex: state.shardSignPubHex || state.authSignPubHex || "",
  };
}

export function selectShardDiagnostics(state) {
  const shardKeyLabel = selectShardKeyLabel(state);
  const shardMatch = selectShardMatch(state);
  return [
    { label: "Key type", value: shardKeyLabel },
    { label: "Quorum", value: `${state.shardThreshold ?? "?"} of ${state.shardShares ?? "?"}` },
    { label: "Collected", value: `${state.shardFrames.size}` },
    { label: "Main doc match", value: shardMatch },
    { label: "Duplicates", value: `${state.shardDuplicates}` },
    { label: "Conflicts", value: `${state.shardConflicts}` },
    { label: "Errors", value: `${state.shardErrors}` },
  ];
}

export function selectCiphertextSource(state) {
  const available = Boolean(state.ciphertext)
    || (state.total && state.mainFrames.size === state.total);
  const size = available
    ? (state.ciphertext ? state.ciphertext.length : sumFrameBytes(state.mainFrames))
    : 0;
  const detail = available
    ? `${formatBytes(size)}  |  ${state.mainFrames.size}/${state.total ?? "?"} frames`
    : `Waiting for frames (${state.mainFrames.size}/${state.total ?? "?"})`;
  return {
    label: "Collected ciphertext",
    detail,
    available,
  };
}

export function selectEnvelopeSource(state) {
  if (state.decryptedEnvelope) {
    return {
      label: "Decrypted envelope",
      detail: `${state.decryptedEnvelopeSource || "From decrypted ciphertext"}  |  ${formatBytes(state.decryptedEnvelope.length)}`,
      available: true,
    };
  }
  return {
    label: "Decrypted envelope",
    detail: "No decrypted envelope yet",
    available: false,
  };
}

export function selectOutputSummary(state) {
  const count = state.extractedFiles.length;
  const totalBytes = state.extractedFiles.reduce((sum, file) => sum + file.data.length, 0);
  const subtitle = count
    ? `${count} file(s)  |  ${formatBytes(totalBytes)}`
    : "No files extracted yet";
  return { count, totalBytes, subtitle };
}

export function selectActionState(state) {
  const ciphertextSource = selectCiphertextSource(state);
  const decryptedEnvelopeAvailable = Boolean(state.decryptedEnvelope);
  return {
    canDownloadCipher: state.total && state.mainFrames.size === state.total,
    canDecryptCiphertext: state.agePassphrase.trim().length > 0 && ciphertextSource.available,
    canExtractEnvelope: decryptedEnvelopeAvailable,
    canDownloadEnvelope: decryptedEnvelopeAvailable,
    canCopyResult: Boolean(state.recoveredShardSecret),
    hasOutput: state.extractedFiles.length > 0,
  };
}
