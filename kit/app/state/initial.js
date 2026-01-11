export function createBaseState() {
  return {
    mainFrames: new Map(),
    docIdHex: null,
    total: null,
    duplicates: 0,
    conflicts: 0,
    ignored: 0,
    errors: 0,
    shardFrames: new Map(),
    shardDocIdHex: null,
    shardDocHashHex: null,
    shardSignPubHex: null,
    shardThreshold: null,
    shardShares: null,
    shardKeyType: null,
    shardSecretLen: null,
    shardDuplicates: 0,
    shardConflicts: 0,
    shardErrors: 0,
    recoveredShardSecret: "",
    authPayload: null,
    authDocIdHex: null,
    authDocHashHex: null,
    authSignPubHex: null,
    authSignatureHex: null,
    authStatus: "missing",
    authDuplicates: 0,
    authConflicts: 0,
    authErrors: 0,
    cipherDocHashHex: null,
    ciphertext: null,
    decryptedEnvelope: null,
    decryptedEnvelopeSource: "",
    extractedFiles: [],
    frameStatus: { lines: [], type: "" },
    shardStatus: { lines: [], type: "" },
    extractStatus: { lines: [], type: "" },
    payloadText: "",
    shardPayloadText: "",
    agePassphrase: "",
    decryptStatus: { lines: [], type: "" },
    isDecrypting: false,
    recoveryComplete: false,
  };
}

export function createInitialState() {
  const state = createBaseState();
  setStatus(state, "frameStatus", ["State cleared."]);
  setStatus(state, "shardStatus", ["Shard state cleared."]);
  setStatus(state, "extractStatus", []);
  setStatus(state, "decryptStatus", []);
  return state;
}

export function setStatus(state, key, lines, type = "") {
  state[key] = { lines, type };
}

export function resetState(state) {
  Object.assign(state, createBaseState());
  setStatus(state, "frameStatus", ["State cleared."]);
  setStatus(state, "shardStatus", ["Shard state cleared."]);
  setStatus(state, "extractStatus", []);
  setStatus(state, "decryptStatus", []);
}

export function bumpError(state, key) {
  state[key] += 1;
}

export function cloneState(state) {
  return {
    ...state,
    mainFrames: new Map(state.mainFrames),
    shardFrames: new Map(state.shardFrames),
    extractedFiles: state.extractedFiles.slice(),
    frameStatus: { ...state.frameStatus },
    shardStatus: { ...state.shardStatus },
    extractStatus: { ...state.extractStatus },
    decryptStatus: { ...state.decryptStatus },
  };
}
