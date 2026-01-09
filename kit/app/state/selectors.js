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

function describeMissingFrames(state) {
  if (!state.total) {
    return {
      value: "Waiting for frame count",
      detail: "Add at least one main frame to detect total.",
      tone: "idle",
    };
  }
  const missingCount = Math.max(0, state.total - state.mainFrames.size);
  if (missingCount === 0) {
    return {
      value: "0 (complete)",
      detail: "All main frames collected.",
      tone: "ok",
    };
  }
  const missingList = listMissing(state.total, state.mainFrames);
  const preview = missingList.slice(0, 8);
  const extra = missingList.length - preview.length;
  const detail = preview.length
    ? `Missing indices: ${preview.join(", ")}${extra > 0 ? ` +${extra} more` : ""}`
    : "";
  return {
    value: `${missingCount} remaining`,
    detail,
    tone: "warn",
  };
}

function describeValidationSummary(state) {
  const hasErrors = state.errors > 0 || state.conflicts > 0;
  const hasFrames = state.mainFrames.size > 0;
  const totalKnown = Boolean(state.total);
  const missingCount = totalKnown ? Math.max(0, state.total - state.mainFrames.size) : null;
  if (hasErrors) {
    return {
      value: "Issues detected",
      detail: "Resolve conflicts or errors before decrypting.",
      tone: "error",
    };
  }
  if (totalKnown && missingCount === 0) {
    return {
      value: "Ready to decrypt",
      detail: "All main frames collected.",
      tone: "ok",
    };
  }
  if (hasFrames) {
    return {
      value: "Collecting frames",
      detail: missingCount === null ? "Waiting for frame count." : `${missingCount} missing.`,
      tone: "progress",
    };
  }
  return {
    value: "Waiting for frames",
    detail: "Paste main frame payloads to begin.",
    tone: "idle",
  };
}

function describeAuthStatus(state) {
  const status = state.authStatus || "missing";
  if (status === "verified") {
    return { value: "Verified", tone: "ok" };
  }
  if (status === "missing") {
    return {
      value: "Missing (optional)",
      detail: "Add auth frame to verify signature.",
      tone: "idle",
    };
  }
  if (status === "pending") {
    return { value: "Pending verification", tone: "progress" };
  }
  if (status === "waiting for main frames") {
    return { value: "Waiting for main frames", tone: "progress" };
  }
  if (status === "doc_hash matches; signature not verified") {
    return {
      value: "Doc hash matches; signature not verified",
      detail: "Browser cannot verify signature.",
      tone: "warn",
    };
  }
  if (status === "invalid signature" || status.includes("mismatch") || status.includes("conflict")) {
    return { value: status, tone: "error" };
  }
  if (status === "invalid payload") {
    return { value: "Invalid auth payload", tone: "error" };
  }
  return { value: status, tone: "idle" };
}

function sumFrameBytes(frames) {
  let total = 0;
  for (const frame of frames.values()) {
    total += frame.data.length;
  }
  return total;
}

function selectFrameStatusItems(state) {
  const validationSummary = describeValidationSummary(state);
  const missingInfo = describeMissingFrames(state);
  const authInfo = describeAuthStatus(state);
  const framesTone = state.total && state.mainFrames.size === state.total
    ? "ok"
    : state.mainFrames.size
      ? "progress"
      : "idle";
  const missingCount = state.total ? Math.max(0, state.total - state.mainFrames.size) : null;
  const readyToDecrypt = Boolean(state.total)
    && missingCount === 0
    && state.errors === 0
    && state.conflicts === 0;
  const authMissing = authInfo.value?.toLowerCase?.().startsWith("missing");
  const authItem = readyToDecrypt && authMissing
    ? {
      label: "Auth frame",
      value: "Missing (optional)",
      subLabel: "Ready to decrypt; signature not verified.",
      tone: "warn",
    }
    : {
      label: "Auth frame",
      value: authInfo.value,
      subLabel: authInfo.detail,
      tone: authInfo.tone,
    };
  const framesDetail = state.total ? `${state.total} total frames` : "Total unknown";
  return [
    {
      label: "Validation",
      value: validationSummary.value,
      subLabel: validationSummary.detail,
      tone: validationSummary.tone,
    },
    {
      label: "Frames",
      value: `${state.mainFrames.size}/${state.total ?? "?"}`,
      subLabel: framesDetail,
      tone: framesTone,
    },
    {
      label: "Missing",
      value: missingInfo.value,
      subLabel: missingInfo.detail,
      tone: missingInfo.tone,
    },
    authItem,
  ];
}

export function selectFrameDiagnostics(state) {
  return [
    { label: "Conflicts", value: `${state.conflicts}`, tone: state.conflicts > 0 ? "error" : "ok" },
    { label: "Errors", value: `${state.errors}`, tone: state.errors > 0 ? "error" : "ok" },
    { label: "Duplicates", value: `${state.duplicates}`, tone: state.duplicates > 0 ? "warn" : "ok" },
    { label: "Ignored", value: `${state.ignored}`, tone: state.ignored > 0 ? "warn" : "ok" },
    { label: "Doc ID", value: state.docIdHex ?? "(unknown)", tone: state.docIdHex ? "ok" : "idle", code: true },
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

function selectShardStatusItems(state) {
  const shardKeyLabel = selectShardKeyLabel(state);
  const shardMatch = selectShardMatch(state);
  const collectedTone = state.shardThreshold
    ? state.shardFrames.size >= state.shardThreshold
      ? "ok"
      : state.shardFrames.size
        ? "progress"
        : "idle"
    : state.shardFrames.size
      ? "progress"
      : "idle";
  const matchTone = shardMatch === "yes" ? "ok" : shardMatch === "no" ? "error" : "idle";
  const keyValue = shardKeyLabel === "-" ? "Unknown" : shardKeyLabel;
  const quorumValue = state.shardThreshold
    ? `${state.shardThreshold} of ${state.shardShares ?? "?"}`
    : "Unknown";
  const collectedValue = state.shardThreshold
    ? `${state.shardFrames.size}/${state.shardThreshold}`
    : `${state.shardFrames.size}`;
  return [
    {
      label: "Key type",
      value: keyValue,
      subLabel: shardKeyLabel === "-" ? "Waiting for shard metadata." : undefined,
      tone: shardKeyLabel === "-" ? "idle" : "ok",
    },
    {
      label: "Quorum",
      value: quorumValue,
      subLabel: state.shardShares ? `${state.shardShares} total shares` : undefined,
      tone: state.shardThreshold ? "ok" : "idle",
    },
    {
      label: "Collected",
      value: collectedValue,
      subLabel: state.shardFrames.size ? "Shard inputs collected." : "No shard inputs yet.",
      tone: collectedTone,
    },
    {
      label: "Main doc match",
      value: shardMatch,
      subLabel: shardMatch === "-" ? "Waiting for doc IDs." : undefined,
      tone: matchTone,
    },
  ];
}

export function selectShardDiagnostics(state) {
  return [
    { label: "Conflicts", value: `${state.shardConflicts}`, tone: state.shardConflicts > 0 ? "error" : "ok" },
    { label: "Errors", value: `${state.shardErrors}`, tone: state.shardErrors > 0 ? "error" : "ok" },
    { label: "Duplicates", value: `${state.shardDuplicates}`, tone: state.shardDuplicates > 0 ? "warn" : "ok" },
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

function selectDecryptStatusItems(state) {
  const ciphertextSource = selectCiphertextSource(state);
  const envelopeSource = selectEnvelopeSource(state);
  const outputSummary = selectOutputSummary(state);
  const actionState = selectActionState(state);
  const ciphertextTone = ciphertextSource.available
    ? "ok"
    : state.mainFrames.size
      ? "progress"
      : "idle";
  const passphraseProvided = state.agePassphrase.trim().length > 0;
  const passphraseTone = passphraseProvided ? "ok" : "warn";
  const envelopeTone = state.decryptedEnvelope
    ? "ok"
    : actionState.canDecryptCiphertext
      ? "progress"
      : "idle";
  const outputTone = outputSummary.count
    ? "ok"
    : state.decryptedEnvelope
      ? "progress"
      : "idle";
  const outputDetail = outputSummary.count
    ? formatBytes(outputSummary.totalBytes)
    : "Decrypt and extract to recover files.";
  return [
    {
      label: "Ciphertext",
      value: ciphertextSource.available ? "Ready" : "Waiting",
      subLabel: ciphertextSource.detail,
      tone: ciphertextTone,
    },
    {
      label: "Passphrase",
      value: passphraseProvided ? "Provided" : "Missing",
      subLabel: passphraseProvided ? "Ready to decrypt." : "Required to decrypt.",
      tone: passphraseTone,
    },
    {
      label: "Envelope",
      value: state.decryptedEnvelope ? "Decrypted" : "Locked",
      subLabel: envelopeSource.detail,
      tone: envelopeTone,
    },
    {
      label: "Output",
      value: outputSummary.count ? `${outputSummary.count} file(s)` : "No files",
      subLabel: outputDetail,
      tone: outputTone,
    },
  ];
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

export function selectStatusItemsForStep(state, stepId) {
  if (stepId === "frames") return selectFrameStatusItems(state);
  if (stepId === "shards") return selectShardStatusItems(state);
  if (stepId === "decrypt") return selectDecryptStatusItems(state);
  return [];
}
