/* Copyright (C) 2026 Alex Stoyanov. SPDX-License-Identifier: GPL-3.0-or-later */
export function connectCollector(input, hint, addButton, { change, add, scanned, addLabel }) {
  function showHint(text) {
    hint.textContent = text;
    hint.hidden = !text;
  }
  input.onpaste = (event) => {
    if (payloadLines(event.clipboardData?.getData("text/plain")).length) {
      showHint(`Choose "${addLabel}" to read this text.`);
    }
  };
  input.oninput = () => {
    showHint("");
    change(input.value);
  };
  addButton.onclick = () => {
    showHint("");
    add();
  };
  return {
    clearHint: () => showHint(""),
    scan(payload) {
      if (payload?.bytes instanceof Uint8Array && payload.bytes.length) {
        scanned(payload);
        showHint("");
        return;
      }
      const lines = payloadLines(payload?.text);
      if (!lines.length) {
        showHint("This QR code contains no text.");
        return;
      }
      const prefix = input.value && !input.value.endsWith("\n") ? "\n" : "";
      change(`${input.value}${prefix}${lines.join("\n")}`);
      showHint(`Text added above. Choose "${addLabel}" to read it.`);
    },
  };
}

function payloadLines(value) {
  return String(value ?? "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}
