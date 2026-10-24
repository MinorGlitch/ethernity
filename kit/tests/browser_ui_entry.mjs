import { mountApp } from "../app/app.js";
import { createCamera } from "../app/scanner/camera.js";
import { createView } from "../app/ui/view.js";
import { createInitialState } from "../app/state/initial.js";
import { checkDiagnosticUpdates } from "./browser/diagnostics.mjs";

function check(condition, message) {
  if (!condition) throw new Error(message);
}
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

function checkView(root) {
  const downloads = [];
  const view = createView(root, (index) => downloads.push(index));
  const state = createInitialState();
  view.update(state);
  view.lock(false);
  const input = view.get("payload-text");
  const details = view.get("recovery-options");
  input.value = state.payloadText = "abc";
  input.focus();
  input.setSelectionRange(1, 2);
  details.open = true;
  const literal = '<img src=x onerror="window.injected=true">';
  state.frameStatus = { lines: [literal], details: [literal], type: "error" };
  state.extractedFiles = [{ path: literal, data: new Uint8Array([1]) }];
  view.update(state);
  check(
    document.activeElement === input && input.selectionStart === 1 && input.selectionEnd === 2,
    "View update moved the caret",
  );
  check(details.open && details === view.get("recovery-options"), "View update replaced details");
  check(
    !root.querySelector("img") && root.querySelector("tbody").textContent.includes(literal),
    "Recovered data was interpreted as HTML",
  );
  const download = root.querySelector("tbody button");
  download.focus();
  view.update({ ...state, agePassphrase: "edited" });
  check(
    document.activeElement === download && root.querySelector("tbody button") === download,
    "Unrelated edits replaced a download button",
  );
  download.click();
  check(downloads.length === 1 && downloads[0] === 0, "File action fired incorrectly");
  view.update(createInitialState());
  check(
    !root.querySelector("tbody button") && input.value === "",
    "Reset retained output or input",
  );
  check(view.get("decrypt").disabled, "Reset left recovery enabled");
  const failed = createInitialState();
  failed.extractStatus = { lines: ["Could not extract files."], type: "error" };
  view.update(failed);
  check(
    root.querySelectorAll(".status.error").length === 1 &&
      !view.get("files-output").hidden &&
      view.get("files-table").hidden,
    "Extraction failure was hidden or duplicated",
  );
  view.dispose();
}

async function checkApp(root) {
  const dispose = mountApp(root);
  root.querySelector("#use-online").click();
  const input = root.querySelector("#payload-text");
  const video = root.querySelector("video");
  const stream = new MediaStream();
  video.srcObject = stream;
  input.value = "invalid";
  input.focus();
  input.setSelectionRange(1, 3);
  input.dispatchEvent(new Event("input"));
  root.querySelector("#backup-add").click();
  await tick();
  check(
    root.querySelector("#payload-text") === input &&
      document.activeElement === input &&
      input.selectionStart === 1,
    "App changed input identity or selection",
  );
  check(
    root.querySelector("video") === video && video.srcObject === stream,
    "App replaced the camera preview",
  );
  check(
    root.querySelectorAll(".status.error").length === 1,
    "Collector did not report exactly one error",
  );
  const draft = "01. ybnr\t fghj  1934\n02. kmnp @";
  input.value = draft;
  input.dispatchEvent(new Event("input"));
  check(input.value === draft, "Highlighting rewrote the draft");
  const editor = input.parentElement;
  check(editor.querySelectorAll(".recovery-line-number").length === 2, "Missing line gutter");
  check(editor.querySelector(".recovery-label").textContent === "01. ", "Label was not marked");
  check(editor.querySelectorAll(".recovery-group").length > 1, "Missing group highlights");
  check(
    editor.querySelector(".recovery-invalid").textContent === "@",
    "Invalid character was hidden",
  );
  root.querySelector("#payload-text-tidy").click();
  check(input.value === "ybnr fghj 1934\nkmnp @", "Tidy altered payload digits or retained labels");
  root.querySelector("#payload-text-tidy").click();
  check(input.value === draft, "Undo tidy lost the original draft");
  input.value = "<img src=x onerror=alert(1)>";
  input.dispatchEvent(new Event("input"));
  check(!editor.querySelector("img"), "Highlighting interpreted input as HTML");
  input.value = "ybnr ".repeat(12000);
  input.dispatchEvent(new Event("input"));
  check(
    editor.classList.contains("recovery-plain") && !editor.querySelector(".recovery-line"),
    "Large input created unbounded highlights",
  );
  check(input.value.length === 60000, "Large input was truncated");
  root.querySelector("#reset").click();
  check(
    input.value === "" && !editor.classList.contains("recovery-plain"),
    "Reset retained editor state",
  );
  check(
    root.querySelector("#payload-text-tidy").textContent === "Tidy",
    "Reset retained undo state",
  );
  dispose();
  window.dispatchEvent(new Event("online"));
  check(!root.childNodes.length, "Disposed app responded to network changes");
  const disposeAgain = mountApp(root);
  root.querySelector("#use-online").click();
  check(root.querySelector("#payload-text").value === "", "New app retained disposed state");
  disposeAgain();
}

async function checkCamera() {
  const original = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");
  const requests = [];
  const plays = [];
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia() {
        const request = deferred();
        requests.push(request);
        return request.promise;
      },
    },
  });
  const video = {
    srcObject: null,
    pause() {},
    play() {
      const play = deferred();
      plays.push(play);
      return play.promise;
    },
  };
  function stream() {
    const track = {
      stopped: false,
      stop() {
        this.stopped = true;
      },
    };
    return { getTracks: () => [track], track };
  }
  let camera;
  try {
    let snapshot;
    let nextPayload = null;
    const received = [];
    camera = createCamera(
      video,
      (payload) => received.push(payload),
      (state) => {
        snapshot = { ...state };
      },
      () => nextPayload,
    );
    const abandoned = camera.start();
    await camera.start();
    check(requests.length === 1, "Repeated Start requested multiple cameras");
    camera.stop();
    const lateStream = stream();
    requests[0].resolve(lateStream);
    await abandoned;
    check(
      lateStream.track.stopped && !snapshot.active && !video.srcObject,
      "Late permission restarted a stopped camera",
    );

    const first = camera.start();
    const firstStream = stream();
    requests[1].resolve(firstStream);
    await tick();
    camera.stop();
    const second = camera.start();
    const secondStream = stream();
    requests[2].resolve(secondStream);
    await tick();
    plays[0].reject(new Error("Old playback failed"));
    await first;
    check(
      snapshot.active && video.srcObject === secondStream && !secondStream.track.stopped,
      "Old playback failure stopped the new camera",
    );
    nextPayload = { bytes: new Uint8Array([0, 255, 1]), text: "binary" };
    plays[1].resolve();
    await second;
    check(
      firstStream.track.stopped &&
        secondStream.track.stopped &&
        !snapshot.active &&
        snapshot.scanCount === 1,
      "Successful scan did not close camera exactly once",
    );
    check(
      received.length === 1 && received[0] === nextPayload,
      "Scanner changed or repeated a binary payload",
    );

    nextPayload = { text: "YQ" };
    const textScan = camera.start();
    requests[3].resolve(stream());
    await tick();
    plays[2].resolve();
    await textScan;
    check(received.length === 2 && received[1].text === "YQ", "Scanner dropped a text payload");

    const pending = camera.start();
    camera.dispose();
    const disposedStream = stream();
    requests[4].resolve(disposedStream);
    await pending;
    await camera.start();
    check(
      disposedStream.track.stopped && !snapshot.active && requests.length === 5,
      "Disposed camera leaked or restarted",
    );
  } finally {
    camera?.dispose();
    if (original) Object.defineProperty(navigator, "mediaDevices", original);
    else delete navigator.mediaDevices;
  }
}

async function run() {
  const root = document.createElement("div");
  document.body.replaceChildren(root);
  checkView(root);
  checkDiagnosticUpdates(root);
  await checkApp(root);
  await checkCamera();
}
run().then(
  () => {
    document.body.textContent = "ui-lifecycle-ok";
  },
  (error) => {
    document.body.textContent = `ui-lifecycle-error: ${error.stack ?? error}`;
  },
);
