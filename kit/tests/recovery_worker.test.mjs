import assert from "node:assert/strict";
import test from "node:test";
import {
  configureRecoveryWorker,
  recoverInWorker,
  SCRYPT_WORKER_WALL_TIME_MS,
} from "../app/recovery_worker.js";
import { RecoveryError } from "../lib/errors.js";

function workerEnvironment(t, { constructorError = false, postError = false } = {}) {
  const workers = [];
  const revoked = [];
  const urls = [];
  const timers = new Map();
  let nextTimer = 0;
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "Worker");
  class FakeWorker {
    constructor(url) {
      if (constructorError) throw new Error("worker blocked");
      this.url = url;
      this.terminations = 0;
      workers.push(this);
    }
    postMessage(request) {
      if (postError) throw new Error("message could not be cloned");
      this.request = structuredClone(request);
    }
    terminate() {
      this.terminations += 1;
    }
    receive(data) {
      this.onmessage({ data: structuredClone(data) });
    }
  }
  Object.defineProperty(globalThis, "Worker", { value: FakeWorker, configurable: true });
  t.after(() => {
    if (descriptor) Object.defineProperty(globalThis, "Worker", descriptor);
    else delete globalThis.Worker;
    configureRecoveryWorker("");
  });
  t.mock.method(URL, "createObjectURL", (blob) => {
    urls.push(blob);
    return `blob:worker-${urls.length}`;
  });
  t.mock.method(URL, "revokeObjectURL", (url) => revoked.push(url));
  t.mock.method(globalThis, "setTimeout", (callback, delay) => {
    const id = ++nextTimer;
    timers.set(id, { callback, delay });
    return id;
  });
  t.mock.method(globalThis, "clearTimeout", (id) => timers.delete(id));
  configureRecoveryWorker("compiled recovery script");
  return { workers, revoked, urls, timers };
}

const rejectsCode = (promise, code) =>
  assert.rejects(promise, (error) => error instanceof RecoveryError && error.code === code);

test("worker sends recovery selection and preserves file bytes without moving collected input", async (t) => {
  const { workers, revoked, urls, timers } = workerEnvironment(t);
  const controller = new AbortController();
  const documents = [{ ciphertext: Uint8Array.of(1, 2, 3) }];
  const promise = recoverInWorker(documents, "secret", {
    extensionTarget: { kind: "root" },
    freshnessUnknownAcknowledged: true,
    signal: controller.signal,
  });
  const worker = workers[0];
  assert.equal(await urls[0].text(), "compiled recovery script");
  assert.deepEqual(worker.request, {
    documents,
    passphrase: "secret",
    options: { extensionTarget: { kind: "root" }, freshnessUnknownAcknowledged: true },
  });
  worker.receive({ type: "ready" });
  const result = { files: [{ path: "a.txt", data: Uint8Array.of(4, 5) }] };
  worker.receive({ type: "result", result });
  assert.deepEqual(await promise, result);
  controller.abort();
  worker.receive({ type: "error", code: "DOCUMENT_INVALID", message: "late error" });
  assert.equal(worker.terminations, 1);
  assert.deepEqual(revoked, [worker.url]);
  assert.equal(timers.size, 0);
  assert.deepEqual(documents[0].ciphertext, Uint8Array.of(1, 2, 3));
});

test("worker failure retains the error code used for passphrase retry", async (t) => {
  const { workers, revoked, timers } = workerEnvironment(t);
  const promise = recoverInWorker([], "wrong");
  const rejected = assert.rejects(promise, (error) => {
    assert.ok(error instanceof RecoveryError);
    assert.equal(error.code, "PASSPHRASE_AUTH_FAILED");
    assert.equal(error.stage, "unlock");
    assert.equal(error.message, "invalid passphrase");
    return true;
  });
  workers[0].receive({
    type: "error",
    code: "PASSPHRASE_AUTH_FAILED",
    message: "invalid passphrase",
  });
  await rejected;
  assert.equal(workers[0].terminations, 1);
  assert.equal(revoked.length, 1);
  assert.equal(timers.size, 0);
});

for (const stage of ["before-start", "startup", "scrypt", "reconstruction"]) {
  test(`cancel recovery during ${stage} and ignore late results`, async (t) => {
    const { workers, revoked, timers } = workerEnvironment(t);
    const controller = new AbortController();
    if (stage === "before-start") controller.abort();
    const promise = recoverInWorker([], "secret", { signal: controller.signal });
    const rejected = rejectsCode(promise, "CANCELLED");
    const worker = workers[0];
    if (stage === "scrypt" || stage === "reconstruction") {
      worker.receive({ type: "ready" });
      worker.receive({ type: "scrypt", active: true });
      if (stage === "reconstruction") worker.receive({ type: "scrypt", active: false });
    }
    controller.abort();
    worker?.receive({ type: "result", result: {} });
    await rejected;
    assert.equal(worker?.terminations ?? 0, stage === "before-start" ? 0 : 1);
    assert.equal(revoked.length, workers.length);
    assert.equal(timers.size, 0);
  });
}

test("each scrypt call gets its own watchdog without timing out a whole update chain", async (t) => {
  const { workers, timers } = workerEnvironment(t);
  const promise = recoverInWorker([], "secret");
  const rejected = rejectsCode(promise, "RECOVERY_RESOURCE_LIMIT");
  const worker = workers[0];
  worker.receive({ type: "ready" });
  assert.equal(timers.size, 0);
  for (let index = 0; index < 3; index += 1) {
    worker.receive({ type: "scrypt", active: true });
    assert.equal(timers.size, 1);
    assert.equal([...timers.values()][0].delay, SCRYPT_WORKER_WALL_TIME_MS);
    worker.receive({ type: "scrypt", active: false });
    assert.equal(timers.size, 0);
  }
  worker.receive({ type: "scrypt", active: true });
  [...timers.values()][0].callback();
  await rejected;
  assert.equal(worker.terminations, 1);
  assert.equal(timers.size, 0);
});

for (const failure of [
  "source",
  "constructor",
  "post",
  "runtime",
  "clone",
  "protocol",
  "startup-timeout",
]) {
  test(`worker ${failure} failure releases resources and never falls back to main-thread crypto`, async (t) => {
    const { workers, revoked, urls, timers } = workerEnvironment(t, {
      constructorError: failure === "constructor",
      postError: failure === "post",
    });
    if (failure === "source") configureRecoveryWorker("");
    const promise = recoverInWorker([], "secret");
    const rejected = rejectsCode(promise, "SCRYPT_UNAVAILABLE");
    const worker = workers[0];
    if (failure === "runtime") worker.onerror(new Error("crashed"));
    if (failure === "clone") worker.onmessageerror();
    if (failure === "protocol") worker.receive({ type: "unknown" });
    if (failure === "startup-timeout") [...timers.values()][0].callback();
    await rejected;
    assert.equal(revoked.length, urls.length);
    assert.equal(worker?.terminations ?? 0, workers.length);
    assert.equal(timers.size, 0);
  });
}
